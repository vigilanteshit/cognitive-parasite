"""Offline SQLite re-embedding into a new directory; the source is never modified."""

import json
import sqlite3
from pathlib import Path

from .memory import MemoryRecord, SQLiteMemoryStore
from .runtime import instance_lock


async def reindex_sqlite(source: Path, target: Path, provider) -> int:
    source, target = source.resolve(), target.resolve()
    if not (source / "memories.sqlite").is_file():
        raise ValueError("Source memory database does not exist")
    if target.exists() or target == source or source in target.parents:
        raise ValueError("Choose a new target directory outside the source directory")
    settings = provider.settings
    manifest = {
        "status": "incomplete",
        "embedding_model": f"{settings.embedding_provider}:{settings.embedding_model}",
        "dimensions": settings.embedding_dimensions,
    }
    # Lock the source before examining it, so running servers cannot race the copy.
    with instance_lock(source):
        journal = source / "sessions.sqlite"
        if journal.exists():
            with sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("SELECT count(*) FROM runs WHERE status != 'completed'").fetchone()[
                    0
                ]:
                    raise ValueError("Finish or delete interrupted runs before reindexing")
        target.mkdir(parents=True)
        (target / "reindex.json").write_text(json.dumps(manifest), encoding="utf-8")
        with instance_lock(target):
            destination = SQLiteMemoryStore(
                target / "memories.sqlite",
                embedding_model=manifest["embedding_model"],
                embedding_dimensions=settings.embedding_dimensions,
            )
            count = 0
            original = sqlite3.connect((source / "memories.sqlite").as_uri() + "?mode=ro", uri=True)
            try:
                cursor = original.execute(
                    "SELECT session_id,data FROM memories ORDER BY session_id,created_at"
                )
                while batch := cursor.fetchmany(32):
                    records = [
                        (session, MemoryRecord.model_validate_json(data)) for session, data in batch
                    ]
                    texts = [
                        r.content
                        + "\n"
                        + (r.state or "")
                        + "\n"
                        + (r.action or "")
                        + "\n"
                        + " ".join(r.keywords)
                        for _, r in records
                    ]
                    vectors = await provider.embed(texts)
                    with destination._connect() as db:
                        for (session, record), vector in zip(records, vectors, strict=True):
                            record.embedding, record.embedding_model = (
                                vector,
                                manifest["embedding_model"],
                            )
                            destination._validate_embedding(record)
                            db.execute(
                                "INSERT INTO memories(session_id,id,kind,data,legacy,created_at) VALUES (?,?,?,?,?,?)",
                                (
                                    session,
                                    record.id,
                                    record.kind,
                                    json.dumps(record.storage_dict()),
                                    int(record.legacy),
                                    record.created_at,
                                ),
                            )
                            count += 1
            finally:
                original.close()
            # SQLite backup copies consistent committed state, including WAL contents.
            for name in ("sessions.sqlite", "sessions.sqlite.checkpoints.sqlite"):
                file = source / name
                if file.exists():
                    before = sqlite3.connect(file.as_uri() + "?mode=ro", uri=True)
                    after = sqlite3.connect(target / name)
                    try:
                        before.backup(after)
                    finally:
                        before.close()
                        after.close()
            manifest.update(status="complete", records=count)
            (target / "reindex.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return count
