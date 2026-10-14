import pytest

from data_parasite.config import Settings
from data_parasite.memory import MemoryRecord, SQLiteMemoryStore
from data_parasite.providers import ModelRouter
from data_parasite.reindex import reindex_sqlite


async def test_reindex_preserves_temporal_links_and_original(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    memory = SQLiteMemoryStore(source / "memories.sqlite")
    await memory.upsert("s", MemoryRecord(id="old", content="I live in Graz", source="test"))
    await memory.upsert(
        "s", MemoryRecord(id="new", content="I live in Vienna", source="test", supersedes="old")
    )
    router = ModelRouter(Settings(_env_file=None, models_file=tmp_path / "none"))
    assert await reindex_sqlite(source, target, router) == 2
    upgraded = SQLiteMemoryStore(
        target / "memories.sqlite", embedding_model="demo:hash-v1", embedding_dimensions=64
    )
    assert (await upgraded.list("s"))[0].supersedes == "old"
    assert len(await upgraded.list("s", include_legacy=True)) == 2
    assert (await memory.list("s"))[0].embedding == []
    assert len((await upgraded.list("s"))[0].embedding) == 64


async def test_reindex_refuses_existing_target(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    SQLiteMemoryStore(source / "memories.sqlite")
    target.mkdir()
    router = ModelRouter(Settings(_env_file=None, models_file=tmp_path / "none"))
    with pytest.raises(ValueError, match="new target"):
        await reindex_sqlite(source, target, router)
