"""Bounded session HTTP transport; callers retain their own authorization projection."""

import asyncio
import json
import re
from urllib.parse import quote

import httpx
from pydantic import JsonValue

from career_lab.delegations.credentials import Credentials


class RemoteFailure(Exception):
    def __init__(self, code: str, status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def safe_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "/\\%\r\n")
        or value in {".", ".."}
    ):
        raise RemoteFailure("route_object_invalid", 422)
    return quote(value, safe="")


async def _exchange(
    credentials: Credentials,
    method: str,
    suffix: str,
    body: dict[str, JsonValue] | None,
    query: dict[str, JsonValue] | None,
    timeout: float,
) -> tuple[int, bytes]:
    url = credentials.api_url + "/sessions/" + safe_id(credentials.session_id) + suffix
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream(
                method,
                url,
                headers={"Authorization": "Bearer " + credentials.token},
                json=body,
                params=query,
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 8_000_000:
                        raise RemoteFailure("response_unconfirmed")
                    raw.extend(chunk)
                return response.status_code, bytes(raw)


def request_json(
    credentials: Credentials,
    method: str,
    suffix: str,
    *,
    body: dict[str, JsonValue] | None = None,
    query: dict[str, JsonValue] | None = None,
    timeout: float = 10,
) -> dict[str, JsonValue]:
    if not 0 < timeout <= 30:
        raise ValueError("invalid timeout")
    try:
        status, raw = asyncio.run(_exchange(credentials, method, suffix, body, query, timeout))
        value = json.loads(raw)
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        raise RemoteFailure("response_unconfirmed") from None
    if not 200 <= status < 300:
        code = value.get("code") if isinstance(value, dict) else None
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code)
            or credentials.token in code
        ):
            code = "request_failed"
        raise RemoteFailure(code, status)
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise RemoteFailure("response_unconfirmed")
    return value
