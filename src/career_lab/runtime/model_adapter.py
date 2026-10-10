import json
import re
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import Field

from career_lab.contracts.base import Contract


class ToolCall(Contract):
    id: str
    name: str
    arguments: dict


class ModelReply(Contract):
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict = Field(default_factory=dict)


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


class OpenAICompatibleModel:
    def __init__(self, api_key: str, base_url: str, model: str, timeout=45.0, retries=2):
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.revision = model
        self.timeout, self.retries = timeout, retries

    @classmethod
    def from_key_file(
        cls, path: Path, *, base_url="https://api.deepseek.com", model="deepseek-chat", **kwargs
    ):
        raw = Path(path).read_text(encoding="utf-8-sig")
        match = re.search(r"sk-[A-Za-z0-9_-]+", raw)
        if match is None:
            raise ValueError("key file contains no recognized API key")
        return cls(match.group(), base_url, model, **kwargs)

    def complete(self, messages, tools):
        payload = {"model": self.revision, "messages": messages, "max_tokens": 512}
        if tools:
            payload["tools"] = tools
        for attempt in range(self.retries + 1):
            try:
                response = httpx.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + self._api_key},
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
                message = data["choices"][0]["message"]
                calls = tuple(
                    ToolCall(
                        id=c["id"],
                        name=c["function"]["name"],
                        arguments=json.loads(c["function"]["arguments"]),
                    )
                    for c in message.get("tool_calls", [])
                )
                return ModelReply(
                    text=message.get("content") or "", tool_calls=calls, usage=data.get("usage", {})
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
