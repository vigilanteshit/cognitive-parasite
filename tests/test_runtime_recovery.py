import asyncio
import threading
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from data_parasite.api import create_app
from data_parasite.config import Settings
from data_parasite.harness import Harness, HarnessLimits
from data_parasite.memory import MemoryRecord, SQLiteMemoryStore
from data_parasite.persistence import RunStore
from data_parasite.providers import ModelRouter
from data_parasite.runtime import instance_lock


def test_second_server_cannot_recover_live_journal(tmp_path):
    with instance_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already using"):
            with instance_lock(tmp_path):
                pass
    with instance_lock(tmp_path):
        pass


def test_replay_after_resume_returns_latest_attempt(tmp_path):
    with TestClient(
        create_app(Settings(_env_file=None, data_dir=tmp_path)), base_url="http://localhost"
    ) as client:
        store = client.app.state.store
        session = store.create_session()["id"]
        store.claim_run(session, "run", "hello", "demo", "owner", 5)
        store.append_event(session, "run", {"type": "done", "status": "cancelled"})
        store.append_event(session, "run", {"type": "status", "resumed": True, "status": "running"})
        store.append_event(
            session, "run", {"type": "done", "status": "completed", "answer": "Recovered"}
        )
        store.finish_run(session, "run", status="completed", answer="Recovered")
        response = client.get("/api/runs/run/events")
        assert '"status": "completed"' in response.text
        assert '"status": "cancelled"' not in response.text


async def test_cancellation_drains_sqlite_write_before_deletion(tmp_path):
    memory = SQLiteMemoryStore(tmp_path / "memory.sqlite")
    connect = memory._connect
    entered, release = threading.Event(), threading.Event()

    @contextmanager
    def delayed_connect():
        entered.set()
        release.wait(timeout=5)
        with connect() as db:
            yield db

    memory._connect = delayed_connect
    task = asyncio.create_task(
        memory.upsert("session", MemoryRecord(content="Synthetic fact", source="test"))
    )
    await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0.03)
    assert not task.done(), "Ownership must wait until the atomic write completes"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    memory._connect = connect
    await memory.delete_session("session")
    assert await memory.list("session") == []


async def test_time_limit_is_not_replenished_on_resume(tmp_path):
    provider = ModelRouter(Settings(_env_file=None, models_file=tmp_path / "none.toml"))
    calls = 0

    async def slow(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    provider.complete = slow
    store = RunStore(tmp_path / "journal.sqlite")
    harness = Harness(
        provider,
        SQLiteMemoryStore(tmp_path / "memory.sqlite"),
        store,
        limits=HarnessLimits(max_seconds=0.2, max_retries=0),
    )
    first = await harness.run("session", "hello", run_id="run")
    assert first.status == "limited"
    calls_before = calls
    second = await harness.resume("session", "run")
    assert second.status == "limited"
    assert calls == calls_before


async def test_older_lexical_memory_survives_candidate_window(tmp_path):
    memory = SQLiteMemoryStore(tmp_path / "memory.sqlite", candidate_limit=2)
    await memory.upsert(
        "s",
        MemoryRecord(
            id="old",
            content="Unique zephyr calibration procedure",
            source="test",
            created_at="2020-01-01",
        ),
    )
    for index in range(3):
        await memory.upsert("s", MemoryRecord(content=f"New unrelated fact {index}", source="test"))
    result = await memory.retrieve("s", "zephyr")
    assert result[0].id == "old"


async def test_ingestion_reserves_session_until_write_finishes(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            session = (await client.post("/api/sessions", json={})).json()["id"]
            entered, release = asyncio.Event(), asyncio.Event()
            original = app.state.router.embed

            async def delayed(texts):
                entered.set()
                await release.wait()
                return await original(texts)

            app.state.router.embed = delayed
            pending = asyncio.create_task(
                client.post(
                    "/api/documents",
                    json={"session_id": session, "title": "Test", "text": "Synthetic pump manual"},
                )
            )
            await entered.wait()
            assert (await client.delete(f"/api/sessions/{session}")).status_code == 409
            assert (
                await client.post(f"/api/sessions/{session}/runs", json={"message": "hello"})
            ).status_code == 409
            release.set()
            assert (await pending).status_code == 201
            assert (await client.delete(f"/api/sessions/{session}")).status_code == 204
            assert await app.state.memory.list(session) == []
