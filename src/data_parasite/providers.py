"""Small capability-aware adapters, validated structured output and bounded retries."""

import asyncio
import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from .config import ModelProfile, Settings


class ProviderError(ValueError):
    """Safe public error; never includes upstream response bodies or credentials."""


@dataclass
class Completion:
    text: str
    parsed: BaseModel | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def input_upper_bound(messages: list[dict], schema: type[BaseModel] | None = None) -> int:
    # One token per UTF-8 byte is conservative across supported byte-based tokenizers.
    size = sum(len(str(m["content"]).encode("utf-8")) + 32 for m in messages) + 256
    if schema:
        size += len(json.dumps(schema.model_json_schema()).encode("utf-8")) + 256
    return size


class ModelRouter:
    def __init__(self, settings: Settings, profiles=None, roles=None):
        self.settings = settings
        self.max_attempts = settings.max_retries + 1
        self._clients = {}
        self.profiles = {
            "demo": ModelProfile(
                id="demo", provider="demo", model="deterministic-v1", label="Local demo"
            )
        }
        self.roles = dict.fromkeys(
            ("answer", "supervisor", "extraction", "memory", "summary"), "demo"
        )
        if settings.models_file.is_file():
            with settings.models_file.open("rb") as handle:
                config = tomllib.load(handle)
            self.profiles.update(
                {
                    key: ModelProfile(id=key, **value)
                    for key, value in config.get("profiles", {}).items()
                }
            )
            self.roles.update(config.get("roles", {}))
        self.profiles.update(profiles or {})
        self.roles.update(roles or {})
        if any(value not in self.profiles for value in self.roles.values()):
            raise ValueError("Every role must reference an existing model profile")

    def profile(self, role="answer", override=None) -> ModelProfile:
        key = override or self.roles.get(role, self.roles["answer"])
        if key not in self.profiles:
            raise ProviderError("Unknown model profile")
        return self.profiles[key]

    def available(self, profile: ModelProfile) -> bool:
        if profile.provider == "demo":
            return True
        if profile.provider == "azure":
            return bool(self.settings.azure_api_key and self.settings.azure_endpoint)
        return bool(getattr(self.settings, f"{profile.provider}_api_key"))

    def _client(self, profile):
        if profile.id in self._clients:
            return self._clients[profile.id]
        if not self.available(profile):
            raise ProviderError("Credentials are missing for the selected provider")
        if profile.provider == "anthropic":
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                max_retries=0,
                timeout=self.settings.request_timeout,
            )
        elif profile.provider == "azure":
            from openai import AsyncAzureOpenAI

            client = AsyncAzureOpenAI(
                api_key=self.settings.azure_api_key.get_secret_value(),
                azure_endpoint=self.settings.azure_endpoint,
                api_version=self.settings.azure_api_version,
                max_retries=0,
                timeout=self.settings.request_timeout,
            )
        else:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                max_retries=0,
                timeout=self.settings.request_timeout,
            )
        self._clients[profile.id] = client
        return client

    async def close(self):
        for client in self._clients.values():
            await client.close()

    async def complete(
        self,
        messages,
        role="answer",
        profile=None,
        schema=None,
        max_output_tokens=None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ):
        selected = self.profile(role, profile)
        output_limit = min(
            max_output_tokens or selected.max_output_tokens, selected.max_output_tokens
        )
        if output_limit < 1:
            raise ProviderError("Output token budget exhausted")
        if schema and not selected.structured_output:
            raise ProviderError("Selected model profile does not support structured output")
        if input_upper_bound(messages, schema) + output_limit > selected.context_window:
            raise ProviderError("Request exceeds the selected model context budget")
        if selected.provider == "demo":
            return await self._demo(messages, schema, on_token)
        streamed = False

        async def emit(text):
            nonlocal streamed
            streamed = True
            await on_token(text)

        for attempt in range(self.settings.max_retries + 1):
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    return await self._call(
                        selected,
                        messages,
                        schema,
                        output_limit,
                        emit if on_token and selected.streaming and not schema else None,
                    )
            except (ValidationError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
                raise ProviderError("Provider returned an invalid or incomplete response") from None
            except ProviderError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                transient = (
                    isinstance(exc, (TimeoutError, ConnectionError))
                    or type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}
                    or status in {408, 429, 500, 502, 503, 504}
                )
                if not transient or streamed or attempt == self.settings.max_retries:
                    raise ProviderError(
                        "Model request failed; check provider configuration and availability"
                    ) from None
                await asyncio.sleep(min(0.25 * 2**attempt, 2))
        raise ProviderError("Model request failed")

    async def _call(self, profile, messages, schema, output_limit, on_token):
        client = self._client(profile)
        if profile.provider == "anthropic":
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            arguments = dict(
                model=profile.model,
                system=system,
                messages=[m for m in messages if m["role"] != "system"],
                max_tokens=output_limit,
            )
            if schema:
                arguments.update(
                    tools=[
                        {
                            "name": "structured_response",
                            "description": "Return the validated result",
                            "input_schema": schema.model_json_schema(),
                        }
                    ],
                    tool_choice={"type": "tool", "name": "structured_response"},
                )
            if on_token:
                async with client.messages.stream(**arguments) as stream:
                    async for token in stream.text_stream:
                        await on_token(token)
                    response = await stream.get_final_message()
            else:
                response = await client.messages.create(**arguments)
            if response.stop_reason == "max_tokens":
                raise ProviderError("Model output exceeded the configured output budget")
            parsed = None
            if schema:
                data = next(
                    (
                        b.input
                        for b in response.content
                        if b.type == "tool_use" and b.name == "structured_response"
                    ),
                    None,
                )
                if data is None:
                    raise ProviderError("Provider did not return the requested structured response")
                parsed = schema.model_validate(data)
            text = "".join(b.text for b in response.content if b.type == "text")
            return Completion(
                text, parsed, response.usage.input_tokens, response.usage.output_tokens
            )
        arguments = dict(model=profile.model, messages=messages, max_completion_tokens=output_limit)
        if profile.temperature_supported:
            arguments["temperature"] = 0
        if schema:
            response = await client.chat.completions.parse(**arguments, response_format=schema)
            message = response.choices[0].message
            if message.refusal or message.parsed is None:
                raise ProviderError("Provider declined the structured request")
            return Completion(
                "", message.parsed, response.usage.prompt_tokens, response.usage.completion_tokens
            )
        if on_token:
            stream = await client.chat.completions.create(
                **arguments, stream=True, stream_options={"include_usage": True}
            )
            text, usage = "", None
            async with stream:
                async for chunk in stream:
                    if chunk.usage:
                        usage = chunk.usage
                    if chunk.choices:
                        choice = chunk.choices[0]
                        if choice.finish_reason == "length":
                            raise ProviderError(
                                "Model output exceeded the configured output budget"
                            )
                        token = choice.delta.content or ""
                        text += token
                        if token:
                            await on_token(token)
            return Completion(
                text,
                None,
                usage.prompt_tokens if usage else input_upper_bound(messages),
                usage.completion_tokens if usage else len(text.encode("utf-8")),
            )
        response = await client.chat.completions.create(**arguments)
        if response.choices[0].finish_reason == "length":
            raise ProviderError("Model output exceeded the configured output budget")
        text = response.choices[0].message.content
        if text is None:
            raise ProviderError("Provider returned no answer")
        return Completion(
            text, None, response.usage.prompt_tokens, response.usage.completion_tokens
        )

    async def _demo(self, messages, schema, on_token):
        user = messages[-1]["content"]
        evidence = []
        for message in messages[:-1]:
            if message["content"].startswith("<untrusted_memory_evidence>\n"):
                try:
                    evidence.append(
                        json.loads(message["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
                    )
                except (ValueError, IndexError):
                    pass
        if schema:
            fields = schema.model_fields
            if "next_action" in fields:
                # Demo is deliberately deterministic; real reasoning needs a live profile.
                history = user.rsplit("Completed actions: ", 1)[-1]
                action = "episodic_memory_retrieval"
                if "episodic_memory_retrieval" in history:
                    action = "semantic_memory_retrieval"
                if "semantic_memory_retrieval" in history:
                    action = "final_answer"
                value = {"next_action": action}
            elif "memories" in fields:
                value = {"memories": []}
                match = re.fullmatch(
                    r"\s*I (live in|like|prefer) ([^\n.!?]{1,180})[.!]?\s*", user, re.IGNORECASE
                )
                if match:
                    verb, fact = match.groups()
                    content = f"I {verb.lower()} {fact.strip()}."
                    old = next(
                        (
                            r
                            for r in evidence
                            if r.get("kind") == "episodic"
                            and r.get("content", "").lower().startswith(f"i {verb.lower()} ")
                        ),
                        None,
                    )
                    value["memories"] = [
                        {
                            "content": content,
                            "category": "personal",
                            "importance": 0.5,
                            "keywords": [verb.lower(), fact.strip()],
                            "supersedes": old["id"] if old and old["content"] != content else None,
                        }
                    ]
            else:
                raise ProviderError("Demo does not support this schema")
            return Completion("", schema.model_validate(value), input_upper_bound(messages), 16)
        text = "Local demo — no model API was called. I can demonstrate retrieval and execution controls. Select a configured live model for generated answers."
        if evidence:
            text = (
                "Local demo — retrieved evidence (no generated interpretation):\n\n"
                + "\n\n".join(
                    f"{r['content']} [source: {r.get('document') or r['source']}]"
                    for r in evidence[:4]
                )
            )
        elif re.fullmatch(
            r"\s*I (live in|like|prefer) [^\n.!?]{1,180}[.!]?\s*", user, re.IGNORECASE
        ):
            text = "Local demo — this explicit preference or location will be considered for episodic memory. Try asking about it in your next message."
        if on_token:
            for token in re.findall(r"\S+\s*", text):
                await on_token(token)
                await asyncio.sleep(0.01)
        return Completion(text, None, input_upper_bound(messages), len(text.split()))

    async def embed(self, texts):
        if not texts or len(texts) > 64 or any(len(t.encode("utf-8")) > 24000 for t in texts):
            raise ProviderError("Embedding batch exceeds configured limits")
        if self.settings.embedding_provider == "demo":
            vectors = []
            for text in texts:
                vector = [0.0] * 64
                for word in re.findall(r"\w+", text.lower()):
                    digest = hashlib.sha256(word.encode()).digest()
                    vector[int.from_bytes(digest[:2]) % 64] += 1
                norm = math.sqrt(sum(v * v for v in vector)) or 1
                vectors.append([v / norm for v in vector])
            return vectors
        profile = ModelProfile(
            id="__embeddings",
            provider=self.settings.embedding_provider,
            model=self.settings.embedding_model,
        )
        try:
            async with asyncio.timeout(self.settings.request_timeout):
                response = await self._client(profile).embeddings.create(
                    model=profile.model, input=texts, dimensions=self.settings.embedding_dimensions
                )
            vectors = [row.embedding for row in sorted(response.data, key=lambda row: row.index)]
            if len(vectors) != len(texts) or any(
                len(v) != self.settings.embedding_dimensions or not all(math.isfinite(x) for x in v)
                for v in vectors
            ):
                raise ProviderError("Embedding model returned an incompatible vector shape")
            return vectors
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(
                "Embedding request failed; check configuration and availability"
            ) from None
