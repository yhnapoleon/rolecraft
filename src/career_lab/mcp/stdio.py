"""Bounded JSON-RPC lines. Diagnostics never include input/config/exception text."""

import json, sys, threading
from concurrent.futures import ThreadPoolExecutor
from .protocol import RpcFailure
from career_lab.delegations.http_client import RemoteFailure


def serve(protocol, stdin=None, stdout=None, stderr=None):
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    write_lock = threading.RLock()
    state_lock = threading.Lock()
    pending = {}
    closed = False

    def emit(value):
        if value is None:
            return
        with write_lock:
            if not closed:
                stdout.write(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                    + "\n"
                )
                stdout.flush()

    def error(identifier, code, message, data=None):
        value = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
        if identifier is not None:
            value["id"] = identifier
        if data is not None:
            value["error"]["data"] = data
        return value

    def run(request, cancelled):
        identifier = request.get("id")
        try:
            result = protocol.handle(request)
            value = (
                {"jsonrpc": "2.0", "id": identifier, "result": result}
                if result is not None
                else None
            )
        except RpcFailure as exc:
            value = error(identifier, exc.code, exc.message, exc.data)
        except RemoteFailure as exc:
            value = error(identifier, 1001, "RoleCraft service unavailable", {"code": exc.code})
        except Exception:
            stderr.write("mcp_request_failed\n")
            stderr.flush()
            value = error(identifier, -32603, "Internal error")
        with state_lock:
            if identifier in pending and pending[identifier] is cancelled:
                pending.pop(identifier)
            if not cancelled.is_set():
                emit(value)

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rolecraft-mcp")
    try:
        while True:
            raw = stdin.readline(1_048_577)
            if not raw:
                break
            if len(raw) > 1_048_576 or not raw.endswith(b"\n"):
                emit(error(None, -32600, "Message size or framing invalid"))
                break
            try:
                request = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                )
            except (ValueError, UnicodeError, RecursionError):
                emit(error(None, -32700, "Parse error"))
                continue
            if not isinstance(request, dict):
                emit(error(None, -32600, "Invalid request"))
                continue
            if "id" not in request:
                if request.get("method") == "notifications/cancelled":
                    params = request.get("params")
                    identifier = params.get("requestId") if isinstance(params, dict) else None
                    if type(identifier) in (str, int):
                        with state_lock:
                            if identifier in pending:
                                pending[identifier].set()
                else:
                    try:
                        protocol.handle(request)
                    except Exception:
                        pass  # Notifications never get a response.
                continue
            identifier = request["id"]
            if type(identifier) not in (str, int):
                emit(error(None, -32600, "Invalid request ID"))
                continue
            # Protocol setup is immediate, preventing legacy initialize races.
            if request.get("method") == "initialize":
                try:
                    emit({"jsonrpc": "2.0", "id": identifier, "result": protocol.handle(request)})
                except RpcFailure as exc:
                    emit(error(identifier, exc.code, exc.message, exc.data))
                continue
            with state_lock:
                if identifier in pending:
                    pending[identifier].set()
                    emit(error(identifier, -32600, "Duplicate in-flight request ID"))
                    continue
                if len(pending) >= 16:
                    emit(error(identifier, 1002, "Too many in-flight protocol requests"))
                    continue
                cancelled = threading.Event()
                pending[identifier] = cancelled
            pool.submit(run, request, cancelled)
    finally:
        # EOF means the client has gone. Effects may already have committed;
        # cancelled/unfinished commands are recovered by their business key.
        with state_lock:
            for event in pending.values():
                event.set()
        closed = True
        pool.shutdown(wait=True, cancel_futures=True)
