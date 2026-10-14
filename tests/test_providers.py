from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from data_parasite.config import ModelProfile, Settings
from data_parasite.providers import ModelRouter, ProviderError


class Decision(BaseModel):
    next_action: str


def router(provider="openai", **changes):
    profile = ModelProfile(id="test", provider=provider, model="test-model", **changes)
    return ModelRouter(
        Settings(_env_file=None),
        profiles={"test": profile},
        roles={"answer": "test", "supervisor": "test"},
    )


async def test_oversized_prompt_is_rejected_before_network():
    model = router(context_window=2048, max_output_tokens=512)
    with pytest.raises(ProviderError, match="context"):
        await model.complete([{"role": "user", "content": "界" * 3000}])


async def test_unknown_profile_fails_clearly():
    with pytest.raises(ProviderError, match="Unknown model profile"):
        router().profile("answer", "missing")


async def test_openai_structured_and_parameter_capability():
    model = router(temperature_supported=False)
    parsed = Decision(next_action="final_answer")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    parse = AsyncMock(return_value=response)
    model._clients["test"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
    )
    result = await model.complete([{"role": "user", "content": "route"}], schema=Decision)
    assert result.parsed == parsed
    assert "temperature" not in parse.call_args.kwargs
    assert parse.call_args.kwargs["max_completion_tokens"] == 1024


async def test_anthropic_structured_uses_validated_tool():
    model = router("anthropic")
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", name="structured_response", input={"next_action": "final_answer"}
            )
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=6),
        stop_reason="tool_use",
    )
    create = AsyncMock(return_value=response)
    model._clients["test"] = SimpleNamespace(messages=SimpleNamespace(create=create))
    result = await model.complete(
        [{"role": "system", "content": "route"}, {"role": "user", "content": "hello"}],
        schema=Decision,
    )
    assert result.parsed.next_action == "final_answer"
    assert create.call_args.kwargs["system"] == "route"
    assert create.call_args.kwargs["tool_choice"]["name"] == "structured_response"


async def test_malformed_provider_result_has_safe_error():
    model = router("anthropic")
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use", name="structured_response", input={"secret": "must-not-appear"}
                )
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="tool_use",
        )
    )
    model._clients["test"] = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(ProviderError) as caught:
        await model.complete([{"role": "user", "content": "test"}], schema=Decision)
    assert "must-not-appear" not in str(caught.value)


async def test_demo_needs_no_credentials_and_embeddings_are_stable():
    model = ModelRouter(Settings(_env_file=None))
    first = await model.embed(["hello memory"])
    second = await model.embed(["hello memory"])
    assert first == second
    assert len(first[0]) == 64
    result = await model.complete([{"role": "user", "content": "hello"}])
    assert "demo" in result.text.lower()


def test_profile_file_rejects_invalid_role(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text('[roles]\nanswer="missing"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        ModelRouter(Settings(_env_file=None, models_file=path))
