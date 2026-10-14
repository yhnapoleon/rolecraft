"""MCP Streamable HTTP on the API: 2026-07-28 per-request metadata and 2025-11-25 initialize.

The endpoint only translates the protocol. It authenticates the delegation token from the
Authorization header, then runs the same Protocol and HttpAgentClient as stdio against this
application's public routes, in process. No protocol session, SSE stream or GET endpoint.
Responses never echo request headers; the request log carries a safe code only.
"""

import base64
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from functools import partial

import anyio
import httpx
from fastapi import Request
from fastapi.responses import Response

from career_lab.api.error_boundary import log_failure
from career_lab.contracts.v2 import ProtocolError
from career_lab.delegations.credentials import Credentials
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure

from .protocol import CAPABILITIES, LEGACY, MODERN, VERSION, Protocol, RpcFailure

PATH = "/sessions/{session_id}/mcp"
# Never resolvable: requests to it only ever travel through the in-process transport.
INTERNAL_BASE = "http://rolecraft-mcp.invalid"
# Local deployment only: a rebound DNS name never reaches the endpoint.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CREDENTIAL_CODES = frozenset(
    {"token_invalid", "credential_expired", "credential_revoked_or_invalid"}
)
# 2026-07-28 mirrors these body fields into Mcp-Name for the listed methods.
NAMED_METHODS = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
BASE64_SENTINEL = re.compile(r"=\?base64\?([A-Za-z0-9+/]*={0,2})\?=")
JSON_RANGES = frozenset({"application/json", "application/*", "*/*"})

# JSON-RPC error codes. 1001 and 1002 are shared with stdio; 1003-1005 are application codes
# outside the JSON-RPC and MCP reserved ranges.
SERVICE_UNAVAILABLE = 1001
TOO_MANY_IN_FLIGHT = 1002
AUTHORIZATION_FAILED = 1003
RATE_LIMITED = 1004
BROWSER_REFUSED = 1005
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
MISSING_CAPABILITY = -32021
UNSUPPORTED_VERSION = -32022


@dataclass(frozen=True)
class HttpLimits:
    """Endpoint limits in one place; deployment changes them here.

    Counters live in the API process, so with several processes each enforces its own.
    """

    in_flight: int = 16  # requests admitted at once, waiting or running (as stdio)
    concurrent: int = 4  # requests running at once (as stdio's worker threads)
    burst: int = 30  # requests one authorization may send back to back
    per_second: float = 10.0  # sustained requests per second for one authorization
    max_body: int = 1_048_576  # bytes per request body (as stdio's line limit)


DEFAULT_LIMITS = HttpLimits()


class TokenBuckets:
    """Per-authorization request rate."""

    def __init__(self, burst, per_second, clock=time.monotonic):
        self.burst, self.per_second, self.clock = burst, per_second, clock
        self.buckets = {}
        self.lock = threading.Lock()

    def take(self, key):
        """0.0 when admitted; otherwise the seconds until one request would be admitted."""
        with self.lock:
            now = self.clock()
            tokens, last = self.buckets.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.per_second)
            if tokens >= 1:
                self.buckets[key] = (tokens - 1, now)
                self.forget_full(now)
                return 0.0
            self.buckets[key] = (tokens, now)
            return (1 - tokens) / self.per_second

    def forget_full(self, now):
        # Authorizations expire within an hour; idle full buckets carry no state worth keeping.
        if len(self.buckets) > 1024:
            self.buckets = {
                key: (tokens, last)
                for key, (tokens, last) in self.buckets.items()
                if tokens + (now - last) * self.per_second < self.burst
            }


class Admission:
    """Requests admitted at once. Used from the event loop only, so it needs no lock."""

    def __init__(self, limit):
        self.limit, self.active = limit, 0

    def enter(self):
        if self.active >= self.limit:
            return False
        self.active += 1
        return True

    def leave(self):
        self.active -= 1


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict | None = None
    headers: dict[str, str] | None = None
    # Safe diagnostic code for the request log. Request content never goes into the log.
    code: str = "ok"
    # Only for 500: the exception type name is logged, never its text.
    error: Exception | None = None


class Refusal(Exception):
    def __init__(self, reply):
        super().__init__(reply.code)
        self.reply = reply


class EndpointRefusal(Exception):
    """Logged in place of an exception when the endpoint itself refuses a request."""


def rpc_error(code, message, identifier=None, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    value = {"jsonrpc": "2.0", "error": error}
    if identifier is not None:
        value["id"] = identifier
    return value


def unauthorized(code):
    """401 for every token problem, as MCP authorization requires; data.code says which."""
    challenge = 'Bearer realm="rolecraft"'
    if code != "token_required":
        challenge += ', error="invalid_token"'
    message = "Authorization required" if code == "token_required" else "Authorization not valid"
    return Reply(
        401,
        rpc_error(AUTHORIZATION_FAILED, message, data={"code": code}),
        {"WWW-Authenticate": challenge},
        code="mcp_unauthorized",
    )


def host_name(value):
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def media_type(value):
    return (value or "").split(";", 1)[0].strip().lower()


def accepts_json(value):
    if value is None:
        return True
    return bool({media_type(part) for part in value.split(",")} & JSON_RANGES)


def screen(request):
    """Transport checks before any credential or body is read."""
    headers = request.headers
    # MCP clients are not browsers and send no Origin; any browser origin is refused.
    if "origin" in headers:
        text = "Browser-origin requests are not accepted"
        return Reply(403, rpc_error(BROWSER_REFUSED, text), code="mcp_browser_refused")
    if host_name(headers.get("host")) not in LOOPBACK_HOSTS:
        text = "Only loopback hosts are accepted"
        return Reply(403, rpc_error(BROWSER_REFUSED, text), code="mcp_browser_refused")
    if request.url.query:
        # Tokens never travel in URLs, so nothing here reads a query string.
        text = "The MCP endpoint takes no query parameters"
        return Reply(400, rpc_error(INVALID_REQUEST, text), code="mcp_query_refused")
    if media_type(headers.get("content-type")) != "application/json":
        return Reply(415, code="mcp_media_type_refused")
    if not accepts_json(headers.get("accept")):
        return Reply(406, code="mcp_not_acceptable")
    return None


def bearer_token(header):
    scheme, _, token = (header or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def read_capped(request, limit):
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


def refuse_constant(_):
    raise ValueError("non-finite number")


def parse(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=refuse_constant)
    except (ValueError, UnicodeError, RecursionError):
        refused = Reply(400, rpc_error(PARSE_ERROR, "Parse error"), code="mcp_parse_error")
        raise Refusal(refused) from None


def request_id(message):
    identifier = message.get("id")
    return identifier if type(identifier) in (str, int) else None


def invalid(text, identifier=None, data=None):
    body = rpc_error(INVALID_REQUEST, text, identifier, data)
    return Refusal(Reply(400, body, code="mcp_invalid_request"))


def classify(message, headers):
    """notification, handshake (legacy initialize), modern (per-request _meta) or legacy."""
    if not isinstance(message, dict):
        raise invalid(
            "Batch requests are not supported" if isinstance(message, list) else "Invalid request"
        )
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        raise invalid("Only JSON-RPC requests and notifications are accepted", request_id(message))
    if "id" not in message:
        return "notification"
    if message["method"] == "initialize":
        return "handshake"
    params = message.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    if isinstance(meta, dict) and VERSION in meta:
        check_modern(message, meta, headers)
        return "modern"
    # Legacy requests carry the version negotiated by an earlier initialize.
    if headers.get("mcp-protocol-version") == LEGACY:
        return "legacy"
    raise invalid(
        "Unsupported or missing MCP-Protocol-Version",
        request_id(message),
        {"supported": [MODERN, LEGACY]},
    )


def header_text(value):
    """Header value as text; the base64 sentinel form is decoded first."""
    match = BASE64_SENTINEL.fullmatch(value)
    if match is None:
        return value if all(" " <= c <= "~" or c == "\t" for c in value) else None
    try:
        return base64.b64decode(match.group(1), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def mismatch(text, identifier):
    body = rpc_error(HEADER_MISMATCH, text, identifier)
    return Refusal(Reply(400, body, code="mcp_header_mismatch"))


def check_modern(message, meta, headers):
    """2026-07-28 Streamable HTTP: the mirrored headers must match the body."""
    identifier = request_id(message)
    version = headers.get("mcp-protocol-version")
    if version is None or version != meta[VERSION]:
        raise mismatch("MCP-Protocol-Version does not match", identifier)
    if version != MODERN:
        data = {"supported": [MODERN, LEGACY], "requested": version}
        body = rpc_error(UNSUPPORTED_VERSION, "Unsupported protocol version", identifier, data)
        raise Refusal(Reply(400, body, code="mcp_version_unsupported"))
    method = message["method"]
    if headers.get("mcp-method") != method:
        raise mismatch("Mcp-Method does not match", identifier)
    field = NAMED_METHODS.get(method)
    named = headers.get("mcp-name")
    if field is not None and (named is None or header_text(named) != message["params"].get(field)):
        raise mismatch("Mcp-Name does not match", identifier)
    if not isinstance(meta.get(CAPABILITIES), dict):
        body = rpc_error(INVALID_PARAMS, "Missing per-request client capabilities", identifier)
        raise Refusal(Reply(400, body, code="mcp_metadata_missing"))


def protocol_failure(failure, era, identifier):
    """Protocol-level failures carry an HTTP status; tool results stay 200."""
    body = rpc_error(failure.code, failure.message, identifier, failure.data)
    if failure.code in (PARSE_ERROR, INVALID_REQUEST):
        return Reply(400, body, code="mcp_invalid_request")
    if era == "modern" and failure.code == METHOD_NOT_FOUND:
        return Reply(404, body, code="mcp_method_not_found")
    if era == "modern" and failure.code in (
        HEADER_MISMATCH,
        MISSING_CAPABILITY,
        UNSUPPORTED_VERSION,
    ):
        return Reply(400, body, code="mcp_invalid_request")
    return Reply(200, body, code="mcp_rpc_error")


def too_many(code, message, wait):
    retry = {"Retry-After": str(max(1, math.ceil(wait)))}
    return Reply(429, rpc_error(code, message), retry, code="mcp_rate_limited")


class StreamableHttpEndpoint:
    def __init__(self, app, limits):
        self.store = app.state.v2_store
        self.limits = limits
        self.transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        # MCP work runs on its own threads, so it never waits on the routes it calls.
        self.limiter = anyio.CapacityLimiter(limits.concurrent)
        self.admission = Admission(limits.in_flight)
        self.buckets = TokenBuckets(limits.burst, limits.per_second)

    async def handle(self, session_id: str, request: Request) -> Response:
        refused = screen(request)
        if refused is not None:
            return respond(request, refused)
        if not self.admission.enter():
            return respond(
                request, too_many(TOO_MANY_IN_FLIGHT, "Too many requests in progress", 1)
            )
        try:
            token = bearer_token(request.headers.get("authorization"))
            raw = await read_capped(request, self.limits.max_body)
            if raw is None:
                return respond(request, Reply(413, code="mcp_payload_too_large"))
            reply = await anyio.to_thread.run_sync(
                partial(self.serve, session_id, token, raw, request.headers), limiter=self.limiter
            )
        finally:
            self.admission.leave()
        return respond(request, reply)

    def serve(self, session_id, token, raw, headers):
        try:
            return self.exchange(session_id, token, raw, headers)
        except Exception as error:
            return Reply(
                500,
                rpc_error(INTERNAL_ERROR, "Internal error"),
                code="mcp_internal_error",
                error=error,
            )

    def exchange(self, session_id, token, raw, headers):
        if token is None:
            return unauthorized("token_required")
        try:
            auth = self.store.authenticate(session_id, token)
        except ProtocolError as error:
            return unauthorized(error.code if error.code in CREDENTIAL_CODES else "token_invalid")
        # Only a delegated Agent may connect; the learner's own session token never does.
        if auth.executor.kind != "external_agent" or auth.executor.delegation_id is None:
            return unauthorized("delegation_required")
        wait = self.buckets.take(auth.credential_id)
        if wait:
            return too_many(RATE_LIMITED, "Rate limit exceeded for this authorization", wait)
        try:
            message = parse(raw)
            era = classify(message, headers)
        except Refusal as refusal:
            return refusal.reply
        if era == "notification":
            # Accepted and ignored: calls are short and synchronous, and no session exists.
            return Reply(202)
        identifier = message["id"]
        backend = HttpAgentClient(
            credentials=Credentials(INTERNAL_BASE, session_id, token), transport=self.transport
        )
        protocol = Protocol(backend, negotiated=LEGACY if era == "legacy" else None)
        try:
            result = protocol.handle(message)
        except RpcFailure as failure:
            return protocol_failure(failure, era, identifier)
        except RemoteFailure as failure:
            # Revoked or expired between the check above and the call: same answer as above.
            if failure.code in CREDENTIAL_CODES:
                return unauthorized(failure.code)
            body = rpc_error(
                SERVICE_UNAVAILABLE,
                "RoleCraft service unavailable",
                identifier,
                {"code": failure.code},
            )
            return Reply(200, body, code="mcp_service_unavailable")
        except Exception as error:
            body = rpc_error(INTERNAL_ERROR, "Internal error", identifier)
            return Reply(500, body, code="mcp_internal_error", error=error)
        return Reply(200, {"jsonrpc": "2.0", "id": identifier, "result": result})


def respond(request, reply):
    if reply.status >= 400:
        log_failure(request, reply.error or EndpointRefusal(), reply.status, reply.code)
    else:
        request.state.safe_error_code = reply.code
    content = b""
    if reply.body is not None:
        content = json.dumps(
            reply.body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    return Response(
        content=content,
        status_code=reply.status,
        media_type="application/json" if reply.body is not None else None,
        headers={"Cache-Control": "no-store", **(reply.headers or {})},
    )


def mount_mcp_http(app, *, limits=DEFAULT_LIMITS):
    """Add the endpoint once. It stays out of the published OpenAPI contract."""
    if getattr(app.state, "mcp_http", None) is not None:
        return app.state.mcp_http
    endpoint = StreamableHttpEndpoint(app, limits)
    app.add_api_route(PATH, endpoint.handle, methods=["POST"], include_in_schema=False)
    app.state.mcp_http = endpoint
    return endpoint
