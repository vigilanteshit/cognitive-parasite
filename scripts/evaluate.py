"""Reproducible synthetic retrieval regression; no private data or live API calls."""

import argparse
import asyncio
import json
import re
import tempfile
import time
from pathlib import Path

from data_parasite.config import Settings
from data_parasite.memory import MemoryRecord, SQLiteMemoryStore
from data_parasite.providers import ModelRouter

CORPUS = [
    {
        "id": "pump",
        "content": "The training pump needs a pressure inspection every twelve months.",
        "kind": "semantic",
    },
    {
        "id": "bearing",
        "content": "Bearing vibration is checked with the vibration sensor before lubrication.",
        "kind": "semantic",
    },
    {"id": "city-old", "content": "I live in Graz.", "kind": "episodic"},
    {"id": "city", "content": "I live in Vienna.", "kind": "episodic", "supersedes": "city-old"},
    {"id": "tea", "content": "I prefer green tea.", "kind": "episodic"},
]
QUERIES = [
    ("pressure inspection training pump", "pump"),
    ("vibration sensor bearing", "bearing"),
    ("where do I live Vienna", "city"),
    ("green tea preference", "tea"),
]


async def evaluate():
    provider = ModelRouter(Settings(_env_file=None, models_file=Path("__no_profiles__")))
    with tempfile.TemporaryDirectory(prefix="parasite-eval-") as folder:
        memory = SQLiteMemoryStore(
            Path(folder) / "memory.sqlite", embedding_model="demo:hash-v1", embedding_dimensions=64
        )
        for item in CORPUS:
            vector = (await provider.embed([item["content"]]))[0]
            await memory.upsert(
                "synthetic",
                MemoryRecord(
                    **item,
                    source="synthetic:fixture",
                    embedding=vector,
                    embedding_model="demo:hash-v1",
                ),
            )
        hits = 0
        baseline_hits = 0
        latency = []
        rows = []
        for query, expected in QUERIES:
            tokens = set(re.findall(r"\w+", query.lower()))
            # Explicitly naive comparison: lexical overlap with no temporal filter.
            naive = max(
                CORPUS,
                key=lambda row: len(tokens & set(re.findall(r"\w+", row["content"].lower()))),
            )["id"]
            baseline_hits += naive == expected
            vector = (await provider.embed([query]))[0]
            started = time.perf_counter()
            result = await memory.retrieve("synthetic", query, embedding=vector, limit=3)
            elapsed = (time.perf_counter() - started) * 1000
            latency.append(elapsed)
            found = result[0].id if result else None
            hits += found == expected
            rows.append(
                {
                    "query": query,
                    "expected": expected,
                    "top_result": found,
                    "sources": [r.id for r in result],
                }
            )
        isolated = await memory.retrieve("other-session", "green tea", limit=3)
        active = await memory.list("synthetic")
        return {
            "mode": "deterministic synthetic retrieval; no LLM benchmark",
            "cases": len(QUERIES),
            "recall_at_1": hits / len(QUERIES),
            "naive_lexical_recall_at_1": baseline_hits / len(QUERIES),
            "mean_retrieval_ms": round(sum(latency) / len(latency), 3),
            "session_isolation": not isolated,
            "legacy_excluded": "city-old" not in [r.id for r in active],
            "external_api_calls": 0,
            "results": rows,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if (
        result["recall_at_1"] < 1
        or not result["session_isolation"]
        or not result["legacy_excluded"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
