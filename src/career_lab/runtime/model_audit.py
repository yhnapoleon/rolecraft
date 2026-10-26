"""Private append-only model accounting. Never stores prompts, replies or exception bodies."""

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from time import monotonic
from uuid import uuid4

from career_lab.contracts.v2.core import ModelAttemptUsage, digest
from career_lab.runtime.file_lock import flock
from career_lab.runtime.model_adapter import ModelTransportTimeout

_scope = ContextVar("model_audit_scope", default=None)
_active = ContextVar("model_audit_call", default=None)
FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter", "function_call"}


@contextmanager
def audit_scope(**identity):
    token = _scope.set({**(_scope.get() or {}), **identity})
    try:
        yield
    finally:
        _scope.reset(token)


def emit(event, **fields):
    path = Path(os.environ.get("CAREER_LAB_MODEL_AUDIT_PATH", "runs/local/model-audit.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"event": event, "at": datetime.now(UTC).isoformat(), **(_scope.get() or {}), **fields}
    # One append under a process lock: API and multiple workers may share this journal.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        flock(stream)
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def tokens(usage, key):
    value = usage.get(key)
    return value if type(value) is int and value >= 0 else None


class ModelCallAudit:
    def __init__(self, slot, **identity):
        self.identity = {"slot": slot, "call_id": uuid4().hex, **identity}
        self.called = False
        self.validation_code = None

    def write(self, event, **fields):
        emit(event, **self.identity, **fields)

    def complete(self, model, messages, tools):
        self.called = True
        self.write("model_call_started", prompt_hash=digest(messages))
        started = monotonic()
        reply, status = None, "failed"
        try:
            reply = model.complete(messages, tools)
            status = "success"
            return reply
        except (TimeoutError, ModelTransportTimeout):
            status = "timeout"
            raise
        finally:
            usage = getattr(reply, "usage", {}) or {}
            a, b = tokens(usage, "prompt_tokens"), tokens(usage, "completion_tokens")
            reason = getattr(reply, "finish_reason", None)
            attempt = ModelAttemptUsage(
                request_id=self.identity.get(
                    "request_id", (_scope.get() or {}).get("request_id", self.identity["call_id"])
                ),
                attempt_id=self.identity["call_id"],
                expected_provider=getattr(model, "provider", None),
                expected_model_revision=model.revision,
                provider=getattr(model, "provider", None),
                model_revision=model.revision,
                status=status,
                input_tokens=a,
                output_tokens=b,
                elapsed_seconds=monotonic() - started,
                usage_known=a is not None and b is not None,
            )
            self.write(
                "model_call_finished",
                usage=attempt.model_dump(mode="json"),
                finish_reason=reason if reason in FINISH_REASONS else None,
            )

    def validation(self, status, code=None, **fields):
        self.write("model_validation", called=self.called, status=status, code=code, **fields)


def complete(model, messages, tools):
    audit = _active.get()
    return audit.complete(model, messages, tools) if audit else model.complete(messages, tools)


def record_validation_code(code):
    """Attach a caller-whitelisted code to this invocation, never to its public result."""
    audit = _active.get()
    if audit is not None:
        audit.validation_code = code


def audited(slot):
    """Keep accounting outside recognizer wrappers, which may discard inner diagnostics."""

    def decorate(function):
        @wraps(function)
        def evaluate(self, package, *args, **kwargs):
            audit = ModelCallAudit(
                slot,
                session_id=package.subjects[0].session_id,
                criterion=package.criterion,
                input_hash=package.input_hash,
            )
            token = _active.set(audit)
            try:
                result = function(self, package, *args, **kwargs)
                if slot == "JUDGE":
                    record = result.attempts[-1] if result.attempts else {}
                    status = record.get("status", "preflight_skipped")
                    code = record.get("code")
                else:
                    status, code = result.status, audit.validation_code
                audit.validation(status, code)
                return result
            except Exception:
                audit.validation("failed", "evaluation_failed")
                raise
            finally:
                _active.reset(token)

        return evaluate

    return decorate


@contextmanager
def phase(name):
    started = monotonic()
    status = "completed"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        emit("feedback_phase", phase=name, status=status, elapsed_seconds=monotonic() - started)
