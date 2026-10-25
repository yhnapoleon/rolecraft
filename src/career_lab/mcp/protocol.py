"""MCP 2026-07-28 stateless tools, plus explicit 2025-11-25 compatibility.

Only tools/discovery/ping are advertised. No sampling, execution, roots, resource
fetch, tasks extension or server-initiated requests. Business identity is never
inferred from clientInfo or JSON-RPC IDs.
"""

import json
import re
from copy import deepcopy
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from pydantic import ValidationError

from career_lab.delegations.http_client import RemoteFailure

from .results import agent_view

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
VERSION = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
SERVER = "io.modelcontextprotocol/serverInfo"
INSTRUCTIONS = (
    "RoleCraft workspace tools for one delegated practice session. Only the listed tools are "
    "authorized; server permissions and business rules still apply. session_id is optional "
    "and defaults to the session this connection is authorized for; if given, it must match. "
    "Start with observation; tools shows which tools are available now. "
    "The JSON-RPC id is not the business request_id: after an unknown "
    "result keep command.request_id unchanged and read requests.read; re-execution requires "
    "an explicit user decision. Engineer writes (engineer.reproduce, engineer.trial, "
    "engineer.submissions.draft) answer inline and are not in requests.read: after an unknown "
    "result read engineer.tickets.read with that ticket_id, whose latest experiments and drafts "
    "show whether it was recorded."
)
# The per-tool sentence on what to do after an unknown result.
RECOVER = (
    "After an unknown result, read requests.read; re-execution requires an explicit user decision."
)
ENGINEER_RECOVER = (
    "After an unknown result, read engineer.tickets.read with the same ticket_id (its latest "
    "experiments and drafts show whether this was recorded); requests.read does not list engineer "
    "operations. Re-execution requires an explicit user decision."
)
SESSION_DESCRIPTION = (
    "Optional; defaults to the practice session this connection is authorized for. "
    "If given, it must be that session."
)


def session_view(parameters, session_id):
    """MCP view of a tool schema: a bound connection may omit session_id.

    The public ToolSchema stays unchanged; only the advertised copy differs.
    """
    properties = parameters.get("properties")
    if session_id is None or not isinstance(properties, dict) or "session_id" not in properties:
        return parameters
    view = deepcopy(parameters)
    view["properties"]["session_id"]["description"] = SESSION_DESCRIPTION
    required = [key for key in view.get("required", []) if key != "session_id"]
    if required:
        view["required"] = required
    else:
        view.pop("required", None)
    return view


def server_info() -> dict[str, str]:
    try:
        installed_version = package_version("career-lab")
    except PackageNotFoundError:
        installed_version = "0.0.0+uninstalled"
    return {"name": "rolecraft-workspace", "version": installed_version}


class RpcFailure(Exception):
    def __init__(self, code, message, data=None):
        self.code, self.message, self.data = code, message, data


class Protocol:
    def __init__(self, backend, *, negotiated=None):
        """negotiated: a legacy version a stateless transport already established per request.

        stdio keeps the handshake in this object; Streamable HTTP carries the negotiated
        version in the MCP-Protocol-Version header of every legacy request.
        """
        if negotiated not in (None, LEGACY):
            raise ValueError("unsupported negotiated protocol version")
        self.backend = backend
        self.legacy_version = negotiated
        self.initialized = negotiated is not None

    def _bound_session(self):
        # Backends bound to one authorized session expose it; catalogue-only backends do not.
        return getattr(self.backend, "session_id", None)

    def _metadata(self, request):
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise RpcFailure(-32602, "Invalid params")
        meta = params.get("_meta", {})
        if not isinstance(meta, dict):
            raise RpcFailure(-32602, "Invalid metadata")
        if VERSION in meta:
            version = meta[VERSION]
            if not isinstance(version, str):
                raise RpcFailure(-32602, "Invalid protocol version")
            if version != MODERN:
                raise RpcFailure(
                    -32022,
                    "Unsupported protocol version",
                    {"supported": [MODERN, LEGACY], "requested": version},
                )
            if CAPABILITIES not in meta or not isinstance(meta[CAPABILITIES], dict):
                raise RpcFailure(-32602, "Missing per-request client capabilities")
            return MODERN, {k: v for k, v in params.items() if k != "_meta"}
        if self.legacy_version and self.initialized:
            return LEGACY, {k: v for k, v in params.items() if k != "_meta"}
        raise RpcFailure(
            -32602,
            "Modern requests require per-request version and capabilities; legacy clients must initialize",
        )

    def _result(self, result, version, *, cache=False):
        if version == MODERN:
            result = {"resultType": "complete", **result, "_meta": {SERVER: server_info()}}
            if cache:
                result.update(ttlMs=0, cacheScope="private")
        return result

    def handle(self, request):
        if (
            not isinstance(request, dict)
            or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)
        ):
            raise RpcFailure(-32600, "Invalid request")
        if "id" not in request:
            return self.notification(request)
        if type(request["id"]) not in (str, int):
            raise RpcFailure(-32600, "Invalid request ID")
        method = request["method"]
        params = request.get("params", {})
        if method == "initialize":
            if self.legacy_version is not None:
                raise RpcFailure(-32600, "Already initialized")
            if (
                not isinstance(params, dict)
                or not isinstance(params.get("protocolVersion"), str)
                or not isinstance(params.get("capabilities"), dict)
                or not isinstance(params.get("clientInfo"), dict)
                or any(
                    not isinstance(params["clientInfo"].get(k), str) for k in ("name", "version")
                )
            ):
                raise RpcFailure(-32602, "Invalid initialize params")
            self.legacy_version = LEGACY
            return {
                "protocolVersion": LEGACY,
                "capabilities": {"tools": {}},
                "serverInfo": server_info(),
                "instructions": INSTRUCTIONS,
            }
        version, params = self._metadata(request)
        if method == "server/discover":
            if params:
                raise RpcFailure(-32602, "Discovery accepts metadata only")
            return self._result(
                {
                    "supportedVersions": [MODERN, LEGACY],
                    "capabilities": {"tools": {}},
                    "instructions": INSTRUCTIONS,
                },
                version,
                cache=True,
            )
        if method == "ping":
            return self._result({}, version)
        if method == "tools/list":
            if set(params) - {"cursor"}:
                raise RpcFailure(-32602, "Invalid tool-list params")
            cursor = params.get("cursor", "0")
            if not isinstance(cursor, str) or not re.fullmatch(r"0|[1-9][0-9]{0,5}", cursor):
                raise RpcFailure(-32602, "Invalid cursor")
            tools = sorted((t for t in self.backend.tools() if t.available), key=lambda t: t.name)
            start = int(cursor)
            if start > len(tools):
                raise RpcFailure(-32602, "Invalid cursor")
            bound = self._bound_session()
            result = {
                "tools": [
                    {
                        "name": t.name,
                        "description": "Authorized RoleCraft "
                        + t.capability
                        + " operation. Existing server permissions and business rules apply. "
                        "Preserve exact citation kind, object_id and version. config_version "
                        "belongs only on kind=config references; omit it on material/test/product "
                        "references. "
                        + (ENGINEER_RECOVER if t.name.startswith("engineer.") else RECOVER),
                        "inputSchema": session_view(t.parameters, bound),
                        "annotations": {
                            "readOnlyHint": t.capability == "read",
                            "openWorldHint": False,
                        },
                    }
                    for t in tools[start : start + 50]
                ]
            }
            if start + 50 < len(tools):
                result["nextCursor"] = str(start + 50)
            return self._result(result, version, cache=True)
        if method == "tools/call":
            if (
                set(params) - {"name", "arguments"}
                or not isinstance(params.get("name"), str)
                or not isinstance(params.get("arguments", {}), dict)
            ):
                raise RpcFailure(-32602, "Invalid tool-call params")
            name = params["name"]
            known = {t.name for t in self.backend.tools()}
            if name not in known:
                raise RpcFailure(-32602, "Unknown tool")
            arguments = params.get("arguments", {})
            bound = self._bound_session()
            if bound is not None and "session_id" not in arguments:
                # An explicit session is passed through for the backend's own match check.
                arguments = {**arguments, "session_id": bound}
            try:
                result = agent_view(name, arguments, self.backend.call(name, arguments))
                return self._result(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    result, ensure_ascii=False, separators=(",", ":")
                                ),
                            }
                        ],
                        "structuredContent": result,
                        "isError": False,
                    },
                    version,
                )
            except RemoteFailure as error:
                return self._result(
                    {
                        "content": [{"type": "text", "text": error.code}],
                        "structuredContent": {
                            "code": error.code,
                            "status": error.status,
                            "retry_rule": (
                                "Recover read-only with engineer.tickets.read for this ticket; "
                                "requests.read does not list engineer operations. Re-execution "
                                "requires an explicit user decision."
                                if name.startswith("engineer.")
                                else "Recover the original request read-only. Re-execution "
                                "requires an explicit user decision; never mint a new "
                                "request_id to replace an unknown result."
                            ),
                        },
                        "isError": True,
                    },
                    version,
                )
            except ValidationError:
                return self._result(
                    {
                        "content": [{"type": "text", "text": "tool_arguments_invalid"}],
                        "isError": True,
                    },
                    version,
                )
        raise RpcFailure(-32601, "Method not supported")

    def notification(self, request):
        if request["method"] == "notifications/initialized" and self.legacy_version:
            self.initialized = True
        return None
