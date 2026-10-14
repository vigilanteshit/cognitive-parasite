import pytest

from data_parasite.memory import (
    EmbeddingMismatch,
    MemoryConflict,
    MemoryRecord,
    MemoryUnavailable,
    Neo4jMemoryStore,
    SQLiteMemoryStore,
)


@pytest.mark.asyncio
async def test_temporal_supersession_is_atomic_and_session_scoped(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    old = MemoryRecord(id="old", content="I live in Berlin", category="personal", source="user:r1")
    await store.upsert("a", old)
    await store.upsert("b", old)
    new = MemoryRecord(
        id="new",
        content="I live in Vienna",
        category="personal",
        source="user:r2",
        supersedes="old",
    )
    await store.upsert("a", new)
    assert [m.id for m in await store.retrieve("a", "live")] == ["new"]
    assert [m.id for m in await store.retrieve("b", "live")] == ["old"]
    legacy = await store.list("a", include_legacy=True)
    assert next(m for m in legacy if m.id == "old").legacy
    await store.upsert("a", new)
    assert len(await store.list("a", include_legacy=True)) == 2
    with pytest.raises(MemoryConflict):
        await store.upsert(
            "a",
            MemoryRecord(id="other", content="Paris", source="r3", supersedes="old"),
        )
    assert len(await store.list("a", include_legacy=True)) == 2


@pytest.mark.asyncio
async def test_embedding_version_dimension_and_career_pair_survive_reopen(tmp_path):
    path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(path, embedding_model="fixture-v1", embedding_dimensions=2)
    await store.upsert(
        "a",
        MemoryRecord(
            id="pair",
            content="Pump failure fixed",
            category="career",
            state="Pump overheating",
            action="Cleaned filter",
            machine="P1",
            source="user:r1",
            embedding=[1.0, 0.0],
            embedding_model="fixture-v1",
        ),
    )
    reopened = SQLiteMemoryStore(path, embedding_model="fixture-v1", embedding_dimensions=2)
    found = await reopened.retrieve("a", "pump", embedding=[1.0, 0.0])
    assert (found[0].state, found[0].action, found[0].machine) == (
        "Pump overheating",
        "Cleaned filter",
        "P1",
    )
    with pytest.raises(EmbeddingMismatch):
        await reopened.upsert(
            "a",
            MemoryRecord(
                id="bad",
                content="bad",
                source="r",
                embedding=[1],
                embedding_model="fixture-v1",
            ),
        )
    with pytest.raises(EmbeddingMismatch):
        SQLiteMemoryStore(path, embedding_model="fixture-v2", embedding_dimensions=2)


@pytest.mark.asyncio
async def test_delete_is_scoped_and_bounded_retrieval_has_provenance(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    for i in range(20):
        await store.upsert(
            "a",
            MemoryRecord(
                id=str(i),
                content=f"maintenance pump {i}",
                source=f"document:manual.pdf:p{i}",
            ),
        )
    assert len(await store.retrieve("a", "pump", limit=3)) == 3
    assert await store.delete("b", "1") is False
    assert await store.delete("a", "1") is True
    assert all(m.source.startswith("document:") for m in await store.retrieve("a", "pump"))


@pytest.mark.asyncio
async def test_bulk_deletion_has_no_list_limit_and_keeps_other_session(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    for i in range(105):
        await store.upsert("a", MemoryRecord(id=str(i), content="fact", source="user:test"))
    await store.upsert("b", MemoryRecord(id="keep", content="fact", source="user:test"))
    assert await store.delete_session("a") == 105
    assert await store.list("a", include_legacy=True) == []
    assert len(await store.list("b")) == 1


@pytest.mark.asyncio
async def test_neo4j_keyword_and_vector_queries_are_parameterized_scoped_and_bounded():
    class Result:
        def __aiter__(self):
            async def rows():
                if False:
                    yield None

            return rows()

    class Session:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def run(self, query, **params):
            self.calls.append((query, params))
            return Result()

    session = Session()

    class Driver:
        def session(self, **kwargs):
            return session

    store = Neo4jMemoryStore(
        "unused",
        "unused",
        "unused",
        driver=Driver(),
        embedding_model="m:v1",
        embedding_dimensions=2,
        candidate_limit=15,
    )
    malicious = "x') MATCH (n) DETACH DELETE n //"
    assert await store.retrieve(malicious, malicious, embedding=[1, 0], limit=3) == []
    assert len(session.calls) == 2
    for query, params in session.calls:
        assert malicious not in query
        assert params["session"] == malicious
        assert params["limit"] == 15
        assert "session" in query and "legacy" in query
    with pytest.raises(EmbeddingMismatch):
        await store.retrieve("a", "q", embedding=[1])


@pytest.mark.asyncio
async def test_neo4j_connection_failure_is_explicit():
    class Driver:
        def session(self, **kwargs):
            raise OSError("credentials-must-not-be-public")

    store = Neo4jMemoryStore(
        "unused",
        "unused",
        "unused",
        driver=Driver(),
        embedding_model="m:v1",
        embedding_dimensions=2,
    )
    with pytest.raises(MemoryUnavailable, match="Neo4j retrieval failed"):
        await store.retrieve("a", "q")
