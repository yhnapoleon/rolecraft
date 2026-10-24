import json
import re
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import Field

from career_lab.contracts.base import Contract
from career_lab.contracts.v2.core import ProtocolError


class ToolCall(Contract):
    id: str
    name: str
    arguments: dict


class ModelReply(Contract):
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict = Field(default_factory=dict)
    # Provider's reason the text ended ("stop", "length", ...); absent when not reported.
    finish_reason: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ModelTransportTimeout(RuntimeError):
    """The bounded transport timed out; still a RuntimeError for existing callers."""


class ModelAdapter(Protocol):
    revision: str

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


class ScriptedModel:
    revision = "scripted-test-only-v1"

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append(json.loads(json.dumps(messages)))
        return next(self.replies)


class LocalModel:
    """Explicitly labeled offline extractive role response, never an LLM substitute claim."""

    revision = "local-extractive-v1"

    def complete(self, messages, tools):
        context = json.loads(messages[0]["content"].split("\nCONTEXT\n", 1)[1])
        facts = context["facts"]
        return ModelReply(
            text="本地事实模式："
            + "；".join(f["description"] + f"（当前值：{f['value']}）" for f in facts)
        )


# A standalone historical "sk-" token is used as-is, so every key file read before keeps
# its key; otherwise the first non-empty, non-comment line is the key.
_LEGACY_KEY = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]+")


def read_key(path: Path) -> str:
    """Read one provider key. Errors carry only a code, never file content."""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ProtocolError("model_slot_key_unreadable", status=503) from None
    legacy = _LEGACY_KEY.search(raw)
    if legacy is not None:
        return legacy.group()
    for line in raw.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if len(value) < 8 or any(character.isspace() for character in value):
            break
        return value
    raise ProtocolError("model_slot_key_invalid", status=503)


class OpenAICompatibleModel:
    """One chat-completions endpoint. ``api_key=None`` sends no Authorization header."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout=45.0,
        retries=2,
        max_tokens: int = 512,
    ):
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.revision = model
        self.timeout, self.retries = timeout, retries
        self.max_tokens = max_tokens

    def __repr__(self) -> str:
        return f"OpenAICompatibleModel(model={self.revision!r}, retries={self.retries})"

    @classmethod
    def from_key_file(
        cls, path: Path, *, base_url="https://api.deepseek.com", model="deepseek-chat", **kwargs
    ):
        return cls(read_key(path), base_url, model, **kwargs)

    def complete(self, messages, tools):
        payload = {"model": self.revision, "messages": messages, "max_tokens": self.max_tokens}
        if tools:
            payload["tools"] = tools
        headers = {} if self._api_key is None else {"Authorization": "Bearer " + self._api_key}
        for attempt in range(self.retries + 1):
            try:
                response = httpx.post(
                    self.base_url + "/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    if (
                        response.status_code == 429 or response.status_code >= 500
                    ) and attempt < self.retries:
                        continue
                    raise RuntimeError(f"model provider HTTP {response.status_code}")
                data = response.json()
                choice = data["choices"][0]
                message = choice["message"]
                calls = tuple(
                    ToolCall(
                        id=c["id"],
                        name=c["function"]["name"],
                        arguments=json.loads(c["function"]["arguments"]),
                    )
                    for c in message.get("tool_calls", [])
                )
                reason = choice.get("finish_reason")
                return ModelReply(
                    text=message.get("content") or "",
                    tool_calls=calls,
                    usage=data.get("usage", {}),
                    finish_reason=reason if isinstance(reason, str) else None,
                )
            except httpx.TransportError as error:
                if attempt == self.retries:
                    failure = (
                        ModelTransportTimeout
                        if isinstance(error, httpx.TimeoutException)
                        else RuntimeError
                    )
                    raise failure("model transport failed after bounded retries") from None
        raise RuntimeError("model exhausted retries")
