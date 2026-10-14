"""Isolated semantic and episodic memories with temporal provenance."""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


async def _atomic_thread(operation):
    """Cancellation cannot release ownership while a SQLite write is still running."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


class MemoryError(RuntimeError):
    pass


class MemoryUnavailable(MemoryError):
    pass


class MemoryConflict(MemoryError):
    pass


class EmbeddingMismatch(MemoryError):
    pass


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    kind: Literal["semantic", "episodic"] = "episodic"
    content: str = Field(min_length=1, max_length=12000)
    category: Literal["health", "relationships", "career", "personal", "other"] = "other"
    importance: float = Field(default=0.5, ge=0, le=1)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    state: str | None = Field(default=None, max_length=6000)
    action: str | None = Field(default=None, max_length=6000)
    machine: str | None = Field(default=None, max_length=256)
    source: str = Field(min_length=1, max_length=1024)
    document: str | None = Field(default=None, max_length=1024)
    page: int | None = Field(default=None, ge=1)
    chunk_order: int | None = Field(default=None, ge=0)
    created_at: str = Field(default_factory=timestamp)
    legacy: bool = False
    supersedes: str | None = None
    superseded_by: str | None = None
    retrieval_count: int = 0
    embedding: list[float] = Field(default_factory=list, exclude=True)
    embedding_model: str | None = None

    @model_validator(mode="after")
    def validate_pair(self):
        if (
            self.category == "career"
            and self.kind == "episodic"
            and bool(self.state) != bool(self.action)
        ):
            raise ValueError(
                "Career memory needs both state and action; use NP for an unknown counterpart"
            )
        if any(not math.isfinite(v) for v in self.embedding):
            raise ValueError("Embedding values must be finite")
        if self.supersedes == self.id:
            raise ValueError("A memory cannot supersede itself")
        return self

    def storage_dict(self) -> dict:
        return {**self.model_dump(), "embedding": self.embedding}

    def evidence(self) -> str:
        return json.dumps(self.model_dump(exclude={"retrieval_count"}), ensure_ascii=False)


class MemoryStore(Protocol):
    async def retrieve(
        self,
        session_id: str,
        query: str,
        *,
        kind: str | None = None,
        embedding: list[float] | None = None,
        limit: int = 12,
    ) -> list[MemoryRecord]: ...
    async def upsert(self, session_id: str, record: MemoryRecord) -> MemoryRecord: ...
    async def list(
        self, session_id: str, *, include_legacy: bool = False, limit: int = 100
    ) -> list[MemoryRecord]: ...
    async def delete(self, session_id: str, memory_id: str) -> bool: ...
    async def delete_session(self, session_id: str) -> int: ...


def _cosine(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(v * v for v in a) * sum(v * v for v in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / denom if denom else 0.0


def _rank(
    records: list[MemoryRecord], query: str, embedding: list[float] | None, limit: int
) -> list[MemoryRecord]:
    words = set(re.findall(r"\w+", query.casefold()))
    scored = []
    for record in records:
        haystack = " ".join(
            [record.content, record.state or "", record.action or "", *record.keywords]
        ).casefold()
        lexical = sum(word in haystack for word in words) / max(len(words), 1)
        vector = _cosine(embedding, record.embedding) if embedding and record.embedding else 0
        if lexical > 0 or vector >= 0.35 or not query:
            scored.append(
                (
                    lexical + max(vector, 0) + record.importance * 0.1,
                    record.created_at,
                    record,
                )
            )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [r for _, _, r in scored[:limit]]


class SQLiteMemoryStore:
    """Bounded local store. Neo4j uses the same record and isolation contract."""

    def __init__(
        self,
        path: str | Path,
        *,
        embedding_model: str = "demo-v1",
        embedding_dimensions: int = 0,
        candidate_limit: int = 1000,
    ):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.candidate_limit = max(1, min(candidate_limit, 5000))
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (session_id TEXT NOT NULL, id TEXT NOT NULL,
                    kind TEXT NOT NULL, legacy INTEGER NOT NULL, created_at TEXT NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(session_id,id));
                CREATE INDEX IF NOT EXISTS memory_scope ON memories(session_id,kind,legacy,created_at);
            """)
            stored = dict(db.execute("SELECT key,value FROM memory_config"))
            expected = {
                "embedding_model": embedding_model,
                "embedding_dimensions": str(embedding_dimensions),
            }
            if stored and stored != expected:
                raise EmbeddingMismatch(
                    "Stored embedding configuration differs; reindex explicitly"
                )
            db.executemany("INSERT OR IGNORE INTO memory_config VALUES (?,?)", expected.items())

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def _validate_embedding(
        self, record: MemoryRecord | None = None, embedding: list[float] | None = None
    ):
        values = record.embedding if record is not None else embedding
        if values:
            if len(values) != self.embedding_dimensions or any(
                not math.isfinite(v) for v in values
            ):
                raise EmbeddingMismatch("Embedding dimension does not match store configuration")
            if record and record.embedding_model != self.embedding_model:
                raise EmbeddingMismatch(
                    "Embedding model/version does not match store configuration"
                )

    async def upsert(self, session_id: str, record: MemoryRecord) -> MemoryRecord:
        self._validate_embedding(record)

        def write():
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT data FROM memories WHERE session_id=? AND id=?",
                    (session_id, record.id),
                ).fetchone()
                if existing:
                    stored = MemoryRecord.model_validate_json(existing[0])
                    if (stored.content, stored.source, stored.supersedes) != (
                        record.content,
                        record.source,
                        record.supersedes,
                    ):
                        raise MemoryConflict("Memory ID already has different content")
                    return stored
                if record.supersedes:
                    old_row = db.execute(
                        "SELECT data FROM memories WHERE session_id=? AND id=?",
                        (session_id, record.supersedes),
                    ).fetchone()
                    if not old_row:
                        raise MemoryConflict("Superseded memory does not exist in this session")
                    old = MemoryRecord.model_validate_json(old_row[0])
                    if old.legacy or old.kind != record.kind or old.category != record.category:
                        raise MemoryConflict(
                            "Superseded memory is inactive or belongs to another category"
                        )
                    old.legacy, old.superseded_by = True, record.id
                    db.execute(
                        "UPDATE memories SET legacy=1,data=? WHERE session_id=? AND id=?",
                        (json.dumps(old.storage_dict()), session_id, old.id),
                    )
                db.execute(
                    "INSERT INTO memories VALUES (?,?,?,?,?,?)",
                    (
                        session_id,
                        record.id,
                        record.kind,
                        int(record.legacy),
                        record.created_at,
                        json.dumps(record.storage_dict()),
                    ),
                )
                return record

        return await _atomic_thread(write)

    async def list(
        self, session_id: str, *, include_legacy: bool = False, limit: int = 100
    ) -> list[MemoryRecord]:
        def read():
            with self._connect() as db:
                rows = db.execute(
                    "SELECT data FROM memories WHERE session_id=? AND (? OR legacy=0) ORDER BY created_at DESC LIMIT ?",
                    (session_id, int(include_legacy), min(max(limit, 1), 5000)),
                ).fetchall()
            return [MemoryRecord.model_validate_json(row[0]) for row in rows]

        return await asyncio.to_thread(read)

    async def retrieve(
        self,
        session_id: str,
        query: str,
        *,
        kind: str | None = None,
        embedding: list[float] | None = None,
        limit: int = 12,
    ) -> list[MemoryRecord]:
        self._validate_embedding(embedding=embedding)
        records = await self.list(session_id, limit=self.candidate_limit)
        words = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))[:20]
        if words:

            def lexical_candidates():
                field = "lower(json_extract(data,'$.content') || ' ' || coalesce(json_extract(data,'$.state'),'') || ' ' || coalesce(json_extract(data,'$.action'),'') || ' ' || json_extract(data,'$.keywords'))"
                conditions = " OR ".join(f"{field} LIKE ?" for _ in words)
                with self._connect() as db:
                    rows = db.execute(
                        "SELECT data FROM memories WHERE session_id=? AND legacy=0 AND ("
                        + conditions
                        + ") ORDER BY created_at DESC LIMIT ?",
                        (session_id, *[f"%{word}%" for word in words], self.candidate_limit),
                    ).fetchall()
                return [MemoryRecord.model_validate_json(row[0]) for row in rows]

            lexical = await asyncio.to_thread(lexical_candidates)
            records = list({record.id: record for record in [*records, *lexical]}.values())
        records = [r for r in records if kind is None or r.kind == kind]
        found = _rank(records, query, embedding, min(max(limit, 1), 100))
        if found:

            def count():
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for record in found:
                        row = db.execute(
                            "SELECT data FROM memories WHERE session_id=? AND id=?",
                            (session_id, record.id),
                        ).fetchone()
                        if row:
                            current = MemoryRecord.model_validate_json(row[0])
                            current.retrieval_count += 1
                            db.execute(
                                "UPDATE memories SET data=? WHERE session_id=? AND id=?",
                                (
                                    json.dumps(current.storage_dict()),
                                    session_id,
                                    record.id,
                                ),
                            )

            await _atomic_thread(count)
        return found

    async def delete(self, session_id: str, memory_id: str) -> bool:
        def remove():
            with self._connect() as db:
                return (
                    db.execute(
                        "DELETE FROM memories WHERE session_id=? AND id=?",
                        (session_id, memory_id),
                    ).rowcount
                    > 0
                )

        return await _atomic_thread(remove)

    async def edit(
        self,
        session_id: str,
        memory_id: str,
        *,
        content: str,
        source: str = "user:edit",
    ) -> MemoryRecord:
        records = await self.list(session_id, limit=5000)
        old = next((r for r in records if r.id == memory_id), None)
        if not old:
            raise MemoryConflict("Active memory does not exist")
        new = old.model_copy(
            update={
                "id": str(uuid4()),
                "content": content,
                "source": source,
                "supersedes": memory_id,
                "created_at": timestamp(),
                "retrieval_count": 0,
                "embedding": [],
                "embedding_model": None,
            }
        )
        return await self.upsert(session_id, MemoryRecord.model_validate(new.storage_dict()))

    async def delete_session(self, session_id: str) -> int:
        def remove():
            with self._connect() as db:
                return db.execute("DELETE FROM memories WHERE session_id=?", (session_id,)).rowcount

        return await _atomic_thread(remove)


class Neo4jMemoryStore:
    """Parameterized Neo4j graph/vector/keyword store; no import-time connections.

    Call initialize once before serving requests. Documents and state/action pairs
    remain explicit graph entities while the complete record is stored for parity.
    """

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        *,
        database: str = "neo4j",
        embedding_model: str,
        embedding_dimensions: int,
        driver=None,
        candidate_limit: int = 200,
    ):
        if driver is None:
            from neo4j import AsyncGraphDatabase

            driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
        self.driver, self.database = driver, database
        self.embedding_model, self.embedding_dimensions = (
            embedding_model,
            embedding_dimensions,
        )
        self.candidate_limit = min(max(candidate_limit, 1), 1000)

    async def initialize(self):
        try:
            async with self.driver.session(database=self.database) as session:
                for query in [
                    "CREATE CONSTRAINT dp_memory IF NOT EXISTS FOR (m:DPMemory) REQUIRE (m.session_id,m.id) IS UNIQUE",
                    "CREATE CONSTRAINT dp_embedding IF NOT EXISTS FOR (c:DPEmbeddingConfig) REQUIRE c.id IS UNIQUE",
                ]:
                    await session.run(query)
                result = await session.run(
                    "MERGE (c:DPEmbeddingConfig {id:'default'}) ON CREATE SET c.model=$model,c.dimensions=$dimensions RETURN c.model AS model,c.dimensions AS dimensions",
                    model=self.embedding_model,
                    dimensions=self.embedding_dimensions,
                )
                record = await result.single()
                if (
                    record["model"] != self.embedding_model
                    or record["dimensions"] != self.embedding_dimensions
                ):
                    raise EmbeddingMismatch(
                        "Neo4j embedding configuration differs; explicit reindex required"
                    )
                await session.run(
                    "CREATE VECTOR INDEX dp_memory_vector IF NOT EXISTS FOR (m:DPMemory) ON (m.embedding) OPTIONS {indexConfig: {`vector.dimensions`: $dimensions, `vector.similarity_function`: 'cosine'}}",
                    dimensions=self.embedding_dimensions,
                )
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryUnavailable("Neo4j initialization failed") from exc

    def _validate(self, values, model=None):
        if values and (
            len(values) != self.embedding_dimensions or any(not math.isfinite(v) for v in values)
        ):
            raise EmbeddingMismatch("Embedding dimension differs from Neo4j index")
        if values and model and model != self.embedding_model:
            raise EmbeddingMismatch("Embedding model/version differs from Neo4j index")

    async def upsert(self, session_id: str, record: MemoryRecord) -> MemoryRecord:
        self._validate(record.embedding, record.embedding_model)

        async def write(tx):
            result = await tx.run(
                "MATCH (m:DPMemory {session_id:$session,id:$id}) RETURN m.data AS data",
                session=session_id,
                id=record.id,
            )
            existing = await result.single()
            if existing:
                stored = MemoryRecord.model_validate_json(existing["data"])
                if (stored.content, stored.source, stored.supersedes) != (
                    record.content,
                    record.source,
                    record.supersedes,
                ):
                    raise MemoryConflict("Memory ID already has different content")
                return stored
            if record.supersedes:
                result = await tx.run(
                    "MATCH (m:DPMemory {session_id:$session,id:$old}) SET m.lock=coalesce(m.lock,0)+1 RETURN m.data AS data",
                    session=session_id,
                    old=record.supersedes,
                )
                old_row = await result.single()
                if not old_row:
                    raise MemoryConflict("Superseded memory not found")
                old = MemoryRecord.model_validate_json(old_row["data"])
                if old.legacy or old.kind != record.kind or old.category != record.category:
                    raise MemoryConflict("Superseded memory inactive or category differs")
                old.legacy, old.superseded_by = True, record.id
                await tx.run(
                    "MATCH (m:DPMemory {session_id:$session,id:$old}) SET m.legacy=true,m.data=$data",
                    session=session_id,
                    old=old.id,
                    data=json.dumps(old.storage_dict()),
                )
            await tx.run(
                """CREATE (m:DPMemory {session_id:$session,id:$id,kind:$kind,category:$category,
                legacy:false,created_at:$time,content:$content,keywords:$keywords,embedding:$embedding,data:$data})
                WITH m MERGE (c:DPCategory {session_id:$session,name:$category}) MERGE (m)-[:IN_CATEGORY]->(c)
                FOREACH (keyword IN $keywords | MERGE (k:DPKeyword {session_id:$session,name:keyword}) MERGE (m)-[:HAS_KEYWORD]->(k))""",
                session=session_id,
                id=record.id,
                kind=record.kind,
                category=record.category,
                time=record.created_at,
                content=record.content,
                keywords=record.keywords,
                embedding=record.embedding,
                data=json.dumps(record.storage_dict()),
            )
            if record.state:
                await tx.run(
                    "MATCH (m:DPMemory {session_id:$session,id:$id}) CREATE (s:DPState {description:$state,machine:$machine}) CREATE (a:DPAction {steps:$action,machine:$machine}) CREATE (m)-[:HAS_STATE]->(s) CREATE (s)-[:RESOLVED_BY]->(a)",
                    session=session_id,
                    id=record.id,
                    state=record.state,
                    action=record.action,
                    machine=record.machine,
                )
            if record.document:
                await tx.run(
                    "MATCH (m:DPMemory {session_id:$session,id:$id}) MERGE (d:DPDocument {session_id:$session,name:$document}) CREATE (m)-[:FROM_DOCUMENT {page:$page,chunk_order:$order}]->(d)",
                    session=session_id,
                    id=record.id,
                    document=record.document,
                    page=record.page,
                    order=record.chunk_order,
                )
            if record.supersedes:
                await tx.run(
                    "MATCH (a:DPMemory {session_id:$session,id:$old}),(b:DPMemory {session_id:$session,id:$id}) CREATE (a)-[:SUPERSEDED_BY]->(b)",
                    session=session_id,
                    old=record.supersedes,
                    id=record.id,
                )
            return record

        try:
            async with self.driver.session(database=self.database) as session:
                return await session.execute_write(write)
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryUnavailable("Neo4j memory write failed") from exc

    async def list(
        self, session_id: str, *, include_legacy: bool = False, limit: int = 100
    ) -> list[MemoryRecord]:
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    "MATCH (m:DPMemory {session_id:$session}) WHERE $legacy OR NOT m.legacy RETURN m.data AS data ORDER BY m.created_at DESC LIMIT $limit",
                    session=session_id,
                    legacy=include_legacy,
                    limit=min(max(limit, 1), 5000),
                )
                return [MemoryRecord.model_validate_json(row["data"]) async for row in result]
        except Exception as exc:
            raise MemoryUnavailable("Neo4j memory listing failed") from exc

    async def retrieve(
        self,
        session_id: str,
        query: str,
        *,
        kind: str | None = None,
        embedding: list[float] | None = None,
        limit: int = 12,
    ) -> list[MemoryRecord]:
        self._validate(embedding)
        words = re.findall(r"\w+", query.casefold())[:20]
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    """MATCH (m:DPMemory {session_id:$session})
                    WHERE NOT m.legacy AND ($kind IS NULL OR m.kind=$kind)
                    AND (size($words)=0 OR any(w IN $words WHERE toLower(m.content) CONTAINS w OR any(k IN m.keywords WHERE toLower(k) CONTAINS w)))
                    RETURN m.data AS data ORDER BY m.created_at DESC LIMIT $limit""",
                    session=session_id,
                    kind=kind,
                    words=words,
                    limit=self.candidate_limit,
                )
                records = {
                    r.id: r
                    for r in [MemoryRecord.model_validate_json(row["data"]) async for row in result]
                }
                if embedding:
                    result = await session.run(
                        "CALL db.index.vector.queryNodes($index,$limit,$embedding) YIELD node,score WHERE node.session_id=$session AND NOT node.legacy AND ($kind IS NULL OR node.kind=$kind) RETURN node.data AS data",
                        index="dp_memory_vector",
                        limit=self.candidate_limit,
                        embedding=embedding,
                        session=session_id,
                        kind=kind,
                    )
                    async for row in result:
                        memory = MemoryRecord.model_validate_json(row["data"])
                        records[memory.id] = memory
                found = _rank(list(records.values()), query, embedding, min(max(limit, 1), 100))
                for memory in found:
                    # Persist counter in record and property atomically without stale data replacement.
                    await session.run(
                        "MATCH (m:DPMemory {session_id:$session,id:$id}) SET m.retrieval_count=coalesce(m.retrieval_count,0)+1",
                        session=session_id,
                        id=memory.id,
                    )
                return found
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryUnavailable("Neo4j retrieval failed") from exc

    async def delete(self, session_id: str, memory_id: str) -> bool:
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    "MATCH (m:DPMemory {session_id:$session,id:$id}) OPTIONAL MATCH (m)-[:HAS_STATE]->(s)-[:RESOLVED_BY]->(a) WITH collect(DISTINCT m)+collect(DISTINCT s)+collect(DISTINCT a) AS nodes FOREACH(n IN nodes | DETACH DELETE n) RETURN size(nodes)>0 AS deleted",
                    session=session_id,
                    id=memory_id,
                )
                return (await result.single())["deleted"]
        except Exception as exc:
            raise MemoryUnavailable("Neo4j memory deletion failed") from exc

    async def edit(
        self,
        session_id: str,
        memory_id: str,
        *,
        content: str,
        source: str = "user:edit",
    ) -> MemoryRecord:
        old = next(
            (m for m in await self.list(session_id, limit=5000) if m.id == memory_id),
            None,
        )
        if old is None:
            raise MemoryConflict("Active memory not found")
        values = old.storage_dict()
        values.update(
            id=str(uuid4()),
            content=content,
            source=source,
            supersedes=memory_id,
            created_at=timestamp(),
            embedding=[],
            embedding_model=None,
            retrieval_count=0,
        )
        return await self.upsert(session_id, MemoryRecord.model_validate(values))

    async def close(self):
        await self.driver.close()

    async def delete_session(self, session_id: str) -> int:
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(
                    """MATCH (m:DPMemory {session_id:$session})
                    OPTIONAL MATCH (m)-[:HAS_STATE]->(s)-[:RESOLVED_BY]->(a)
                    WITH count(DISTINCT m) AS count,collect(DISTINCT m)+collect(DISTINCT s)+collect(DISTINCT a) AS nodes
                    FOREACH(n IN nodes | DETACH DELETE n) RETURN count""",
                    session=session_id,
                )
                count = (await result.single())["count"]
                await session.run(
                    "MATCH (n) WHERE n.session_id=$session AND (n:DPCategory OR n:DPKeyword OR n:DPDocument) DETACH DELETE n",
                    session=session_id,
                )
                return count
        except Exception as exc:
            raise MemoryUnavailable("Neo4j session deletion failed") from exc
