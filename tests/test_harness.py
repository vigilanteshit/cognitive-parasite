import asyncio
from types import SimpleNamespace

import pytest

from data_parasite.harness import Harness, HarnessLimits
from data_parasite.memory import SQLiteMemoryStore
from data_parasite.persistence import RunStore


class FixtureProvider:
    def __init__(self, *, repeat=False, fail_extraction=False):
        self.repeat, self.fail_extraction = repeat, fail_extraction
        self.calls = []

    def profile(self, role, override=None):
        return SimpleNamespace(id="fixture", context_window=32000, max_output_tokens=1024)

    async def complete(
        self,
        messages,
        *,
        role="answer",
        profile=None,
        schema=None,
        max_output_tokens=None,
        on_token=None,
    ):
        self.calls.append((role, messages))
        if schema and schema.__name__ == "SupervisorDecision":
            done = (
                "episodic_memory_retrieval"
                in messages[-1]["content"].split("Completed actions:")[-1]
            )
            parsed = schema(
                next_action="episodic_memory_retrieval"
                if self.repeat or not done
                else "final_answer"
            )
        elif schema:
            if self.fail_extraction:
                raise RuntimeError("secret-key-never-expose")
            parsed = schema(
                memories=[
                    {
                        "content": "Pump filter cleaned",
                        "category": "career",
                        "importance": 0.8,
                        "keywords": ["pump"],
                        "state": "Pump overheated",
                        "action": "Cleaned filter",
                        "machine": "P1",
                    }
                ]
            )
        else:
            parsed = None
            if on_token:
                await on_token("Pump repaired.")
        return SimpleNamespace(
            text="Pump repaired.", parsed=parsed, input_tokens=30, output_tokens=10
        )

    async def embed(self, texts):
        return [[1.0, 0.0] for text in texts]


@pytest.mark.asyncio
async def test_harness_persists_career_pair_usage_events_and_isolation(tmp_path):
    journal = RunStore(tmp_path / "runs.db")
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    provider = FixtureProvider()
    harness = Harness(provider, memory, journal)
    result = await harness.run("a", "Pump overheated; I cleaned its filter", run_id="run1")
    assert result.status == "completed"
    assert result.answer == "Pump repaired."
    pair = (await memory.list("a"))[0]
    assert (pair.state, pair.action, pair.source) == (
        "Pump overheated",
        "Cleaned filter",
        "user:run1",
    )
    assert await memory.list("b") == []
    events = journal.events("a", "run1")
    assert any(e["type"] == "token" for e in events)
    assert all("reasoning" not in str(e) for e in events)
    assert result.usage["calls"] >= 3
    again = await harness.run("a", "Pump overheated; I cleaned its filter", run_id="run1")
    assert again.status == "completed"
    assert len(journal.history("a")) == 2


@pytest.mark.asyncio
async def test_repeated_supervisor_action_is_bounded(tmp_path):
    provider = FixtureProvider(repeat=True)
    harness = Harness(
        provider,
        SQLiteMemoryStore(tmp_path / "memory.db"),
        RunStore(tmp_path / "runs.db"),
    )
    result = await harness.run("a", "pump")
    assert result.status == "completed"
    assert result.usage["steps"] <= 8


@pytest.mark.asyncio
async def test_error_is_typed_and_checkpoint_resume_has_no_duplicate_messages(tmp_path):
    journal = RunStore(tmp_path / "runs.db")
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    provider = FixtureProvider(fail_extraction=True)
    first = await Harness(provider, memory, journal, limits=HarnessLimits(max_retries=0)).run(
        "a", "pump", run_id="r"
    )
    assert first.status == "failed"
    assert first.error["code"] == "provider_error"
    assert "secret-key" not in str(journal.events("a", "r"))
    provider.fail_extraction = False
    result = await Harness(provider, memory, RunStore(tmp_path / "runs.db")).resume("a", "r")
    assert result.status == "completed"
    assert len(journal.history("a")) == 2
    assert len(await memory.list("a")) == 1


@pytest.mark.asyncio
async def test_cancel_before_call_and_token_budget_stop_before_provider(tmp_path):
    provider = FixtureProvider()
    journal = RunStore(tmp_path / "runs.db")
    harness = Harness(
        provider,
        SQLiteMemoryStore(tmp_path / "memory.db"),
        journal,
        limits=HarnessLimits(max_total_tokens=5),
    )
    result = await harness.run("a", "pump", run_id="r")
    assert result.status == "limited"
    assert result.error["code"] == "token_limit"
    assert provider.calls == []
    event = asyncio.Event()
    event.set()
    cancelled = await harness.run("b", "pump", cancel_event=event)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_retrieval_failure_is_not_empty_memory(tmp_path):
    class BrokenMemory(SQLiteMemoryStore):
        async def retrieve(self, *args, **kwargs):
            raise OSError("database offline")

    journal = RunStore(tmp_path / "runs.db")
    result = await Harness(FixtureProvider(), BrokenMemory(tmp_path / "memory.db"), journal).run(
        "a", "pump"
    )
    assert result.status == "failed"
    assert result.error["code"] == "memory_unavailable"


@pytest.mark.asyncio
async def test_cancellation_interrupts_inflight_request_and_resume_replays_checkpoint(
    tmp_path,
):
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowProvider(FixtureProvider):
        async def complete(self, *args, **kwargs):
            if not release.is_set():
                entered.set()
                await release.wait()
            return await super().complete(*args, **kwargs)

    provider = SlowProvider()
    journal = RunStore(tmp_path / "runs.db")
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    cancel = asyncio.Event()
    harness = Harness(provider, memory, journal)
    task = asyncio.create_task(harness.run("a", "pump", run_id="cancelled", cancel_event=cancel))
    await asyncio.wait_for(entered.wait(), 2)
    cancel.set()
    result = await asyncio.wait_for(task, 2)
    assert result.status == "cancelled"
    release.set()
    resumed = await Harness(provider, memory, RunStore(tmp_path / "runs.db")).resume(
        "a", "cancelled"
    )
    assert resumed.status == "completed"
    assert len(journal.history("a")) == 2


@pytest.mark.asyncio
async def test_step_limit_persists_and_requires_explicit_budget_increase(tmp_path):
    provider = FixtureProvider()
    journal = RunStore(tmp_path / "runs.db")
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    first = await Harness(provider, memory, journal, limits=HarnessLimits(max_steps=2)).run(
        "a", "pump", run_id="limit"
    )
    assert first.error["code"] == "step_limit"
    old_calls = len(provider.calls)
    second = await Harness(provider, memory, journal, limits=HarnessLimits(max_steps=2)).resume(
        "a", "limit"
    )
    assert second.status == "limited"
    assert len(provider.calls) == old_calls
    third = await Harness(provider, memory, journal, limits=HarnessLimits(max_steps=16)).resume(
        "a", "limit"
    )
    assert third.status == "completed"


@pytest.mark.asyncio
async def test_session_deletion_removes_journal_events_and_checkpoints(tmp_path):
    journal = RunStore(tmp_path / "runs.db")
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    await Harness(FixtureProvider(), memory, journal).run("a", "pump", run_id="delete-me")
    assert await journal.delete_session("a")
    assert journal.find_run("delete-me") is None
    assert journal.history("a") == []
    assert journal.events("a", "delete-me") == []
    assert journal.get_session("a") is None


@pytest.mark.asyncio
async def test_cancellation_preserves_streamed_partial_answer(tmp_path):
    entered = asyncio.Event()

    class StreamingProvider(FixtureProvider):
        async def complete(self, *args, **kwargs):
            if kwargs.get("on_token"):
                await kwargs["on_token"]("Observed partial answer")
                entered.set()
                await asyncio.Event().wait()
            return await super().complete(*args, **kwargs)

    journal = RunStore(tmp_path / "runs.db")
    harness = Harness(StreamingProvider(), SQLiteMemoryStore(tmp_path / "memory.db"), journal)
    cancel = asyncio.Event()
    task = asyncio.create_task(
        harness.run("a", "pump", run_id="stream-cancel", cancel_event=cancel)
    )
    await asyncio.wait_for(entered.wait(), 2)
    cancel.set()
    result = await asyncio.wait_for(task, 2)
    assert result.status == "cancelled"
    assert result.answer == "Observed partial answer"
    assert journal.get_run("a", "stream-cancel")["answer"] == result.answer
    assert len(journal.history("a")) == 1
