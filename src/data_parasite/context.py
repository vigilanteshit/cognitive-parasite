"""Conservative model-independent context accounting for every LLM role."""

import json
from collections.abc import Iterable
from dataclasses import dataclass


class ContextBudgetError(ValueError):
    """Required instructions and the latest message do not fit the model."""


def count_tokens(text: str) -> int:
    # One UTF-8 byte per token is a conservative bound for byte-level tokenizers.
    # It also avoids a network download or an incompatible model tokenizer.
    return len(text.encode("utf-8"))


def message_tokens(messages: Iterable[dict]) -> int:
    return sum(count_tokens(str(m["content"])) + 32 for m in messages) + 256


@dataclass(frozen=True)
class Context:
    messages: list[dict]
    input_tokens: int
    output_tokens: int
    schema_tokens: int
    omitted_history: int = 0
    omitted_memories: int = 0


def build_context(
    *,
    system: str,
    user: str,
    context_window: int,
    output_tokens: int,
    history: Iterable[dict] = (),
    memories: Iterable[str] = (),
    schema: dict | None = None,
    summary: str = "",
) -> Context:
    """Keep mandatory input intact; add complete evidence and newest history as fits.

    Retrieved evidence is explicitly untrusted, and cannot override instructions.
    No oversized current user input is silently truncated.
    """
    if context_window <= 0 or not 0 < output_tokens < context_window:
        raise ContextBudgetError("Invalid context/output budget")
    schema_tokens = count_tokens(json.dumps(schema)) + 256 if schema else 0
    allowed = context_window - output_tokens - schema_tokens
    mandatory = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if message_tokens(mandatory) > allowed:
        raise ContextBudgetError("Instructions, schema, and current message exceed model context")
    evidence = []
    history = list(history)
    memories = list(memories)
    for item in memories:
        candidate = {
            "role": "user",
            "content": "<untrusted_memory_evidence>\n" + item + "\n</untrusted_memory_evidence>",
        }
        if message_tokens([mandatory[0], *evidence, candidate, mandatory[1]]) <= allowed:
            evidence.append(candidate)
    if summary:
        candidate = {
            "role": "user",
            "content": "<conversation_summary_data>\n" + summary + "\n</conversation_summary_data>",
        }
        if message_tokens([mandatory[0], *evidence, candidate, mandatory[1]]) <= allowed:
            evidence.append(candidate)
    selected = []
    for item in reversed(history):
        candidate = {"role": item["role"], "content": str(item["content"])}
        if message_tokens([mandatory[0], *evidence, candidate, *selected, mandatory[1]]) > allowed:
            break
        selected.insert(0, candidate)
    messages = [mandatory[0], *evidence, *selected, mandatory[1]]
    return Context(
        messages,
        message_tokens(messages),
        output_tokens,
        schema_tokens,
        len(history) - len(selected),
        len(memories)
        - sum(e["content"].startswith("<untrusted_memory_evidence>") for e in evidence),
    )
