"""SQLite session/run/event journal, separate from long-term memory."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .memory import timestamp


class RunConflict(ValueError):
    pass


class RunStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.checkpoint_path = self.path + ".checkpoints.sqlite"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,message TEXT NOT NULL,
                    status TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',error TEXT,model_profile TEXT,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,usage TEXT NOT NULL,
                    memory_ids TEXT NOT NULL DEFAULT '[]',lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id,created_at);
                CREATE TABLE IF NOT EXISTS messages(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,
                    UNIQUE(run_id,role));
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(session_id,run_id,seq);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def create_session(
        self, session_id: str | None = None, title: str = "New conversation"
    ) -> dict:
        session_id = session_id or str(uuid4())
        if not session_id or len(session_id) > 128:
            raise ValueError("Invalid session ID")
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO sessions(id,title,created_at) VALUES (?,?,?)",
                (session_id, title[:256], timestamp()),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT s.*,coalesce((SELECT max(r.updated_at) FROM runs r WHERE r.session_id=s.id),s.created_at) AS updated_at FROM sessions s WHERE id=?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT s.*,coalesce((SELECT max(r.updated_at) FROM runs r WHERE r.session_id=s.id),s.created_at) AS updated_at FROM sessions s ORDER BY updated_at DESC LIMIT ?",
                    (min(max(limit, 1), 1000),),
                )
            ]

    def find_run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            return self._decode_run(
                db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            )

    def recover_interrupted(self) -> int:
        """Only at single-worker startup, after ensuring the old worker is stopped."""
        with self.connect() as db:
            error = json.dumps(
                {
                    "code": "interrupted",
                    "message": "Server stopped during this run; resume saved progress",
                    "resumable": True,
                }
            )
            return db.execute(
                "UPDATE runs SET status='cancelled',error=?,lease_owner=NULL,lease_until=0 WHERE status='running'",
                (error,),
            ).rowcount

    async def delete_session(self, session_id: str) -> bool:
        """Delete journal and LangGraph checkpoints after caller stops active runs."""
        import hashlib

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # Fetch all IDs separately; public list limits do not limit privacy deletion.
        with self.connect() as db:
            runs = [
                dict(r) for r in db.execute("SELECT id FROM runs WHERE session_id=?", (session_id,))
            ]
        if Path(self.checkpoint_path).exists():
            async with AsyncSqliteSaver.from_conn_string(self.checkpoint_path) as saver:
                for run in runs:
                    thread = hashlib.sha256(f"{session_id}:{run['id']}".encode()).hexdigest()
                    await saver.adelete_thread(thread)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for table in ["events", "messages", "runs"]:
                db.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
            return db.execute("DELETE FROM sessions WHERE id=?", (session_id,)).rowcount > 0

    def history(self, session_id: str, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT role,content,run_id FROM messages WHERE session_id=? ORDER BY seq DESC LIMIT ?",
                (session_id, min(max(limit, 1), 1000)),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def append_message(self, session_id: str, run_id: str, role: str, content: str):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO messages(session_id,run_id,role,content,created_at) VALUES (?,?,?,?,?)",
                (session_id, run_id, role, content, timestamp()),
            )

    @staticmethod
    def _decode_run(row) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["run_id"] = item["id"]
        for key in ["error", "usage", "memory_ids"]:
            item[key] = json.loads(item[key]) if item[key] else None
        item.pop("lease_owner", None)
        item.pop("lease_until", None)
        return item

    def get_run(self, session_id: str, run_id: str) -> dict | None:
        with self.connect() as db:
            return self._decode_run(
                db.execute(
                    "SELECT * FROM runs WHERE session_id=? AND id=?",
                    (session_id, run_id),
                ).fetchone()
            )

    def list_runs(self, session_id: str, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [
                self._decode_run(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                    (session_id, min(max(limit, 1), 1000)),
                )
            ]

    def claim_run(
        self,
        session_id: str,
        run_id: str,
        message: str,
        profile: str | None,
        owner: str,
        ttl: float,
    ) -> dict:
        self.create_session(session_id)
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row and (row["session_id"] != session_id or row["message"] != message):
                raise RunConflict("Run ID belongs to different input or session")
            active = db.execute(
                "SELECT id FROM runs WHERE session_id=? AND lease_until>?",
                (session_id, now),
            ).fetchone()
            if active:
                raise RunConflict("A run is already active for this session")
            if row and row["status"] == "completed":
                return self._decode_run(row)
            if row is None:
                at = timestamp()
                db.execute(
                    "INSERT INTO runs(id,session_id,message,status,model_profile,created_at,updated_at,usage) VALUES (?,?,?,'pending',?,?,?,?)",
                    (
                        run_id,
                        session_id,
                        message,
                        profile,
                        at,
                        at,
                        json.dumps(
                            {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "steps": 0,
                                "calls": 0,
                                "reserved_tokens": 0,
                            }
                        ),
                    ),
                )
            db.execute(
                "UPDATE runs SET status='running',error=NULL,updated_at=?,model_profile=?,lease_owner=?,lease_until=? WHERE id=?",
                (timestamp(), profile, owner, now + ttl, run_id),
            )
        self.append_message(session_id, run_id, "user", message)
        return self.get_run(session_id, run_id)

    def increment_usage(self, session_id: str, run_id: str, **increments: int) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT usage FROM runs WHERE session_id=? AND id=?",
                (session_id, run_id),
            ).fetchone()
            usage = json.loads(row["usage"])
            for key, value in increments.items():
                usage[key] = usage.get(key, 0) + value
            db.execute(
                "UPDATE runs SET usage=?,updated_at=? WHERE session_id=? AND id=?",
                (json.dumps(usage), timestamp(), session_id, run_id),
            )
            return usage

    def finish_run(
        self,
        session_id: str,
        run_id: str,
        *,
        status: str,
        answer: str = "",
        error: dict | None = None,
        memory_ids: list[str] = (),
    ) -> dict:
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status=?,answer=?,error=?,memory_ids=?,updated_at=?,lease_owner=NULL,lease_until=0 WHERE session_id=? AND id=?",
                (
                    status,
                    answer,
                    json.dumps(error) if error else None,
                    json.dumps(list(memory_ids)),
                    timestamp(),
                    session_id,
                    run_id,
                ),
            )
        if status == "completed":
            self.append_message(session_id, run_id, "assistant", answer)
        return self.get_run(session_id, run_id)

    def append_event(self, session_id: str, run_id: str, event: dict) -> dict:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO events(session_id,run_id,data) VALUES (?,?,?)",
                (session_id, run_id, json.dumps(event)),
            )
            seq = cur.lastrowid
        return {**event, "seq": seq, "run_id": run_id, "session_id": session_id}

    def event_cursor(self, session_id: str, run_id: str, *, attempt: bool = False) -> int:
        condition = (
            " AND json_extract(data,'$.resumed')=1 AND json_extract(data,'$.type')='status'"
            if attempt
            else ""
        )
        with self.connect() as db:
            return db.execute(
                "SELECT coalesce(max(seq),0) FROM events WHERE session_id=? AND run_id=?"
                + condition,
                (session_id, run_id),
            ).fetchone()[0]

    def events(self, session_id: str, run_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT seq,data FROM events WHERE session_id=? AND run_id=? AND seq>? ORDER BY seq LIMIT 10000",
                (session_id, run_id, after),
            ).fetchall()
            return [
                {
                    **json.loads(r["data"]),
                    "seq": r["seq"],
                    "run_id": run_id,
                    "session_id": session_id,
                }
                for r in rows
            ]

    def set_summary(self, session_id: str, summary: str):
        with self.connect() as db:
            db.execute("UPDATE sessions SET summary=? WHERE id=?", (summary[:4000], session_id))

    def set_title(self, session_id: str, title: str):
        with self.connect() as db:
            db.execute("UPDATE sessions SET title=? WHERE id=?", (title[:120], session_id))
