"""Reuse the existing role-model adapter without its hidden retry loop."""
import time
from copy import copy
from career_lab.contracts.v2 import ModelAttemptUsage
from .ports import ModelOutput, PortError


class AdapterModel:
    """One request per attempt; provider truth and unknown usage are preserved.

    OpenAICompatibleModel currently fixes output to 512 and cannot set decode/seed.
    This bridge therefore reports seed unsupported; it cannot prove a frozen E4
    model comparison until the shared provider supports those controls.
    """
    output_token_limit = 512
    seed_supported = False

    def __init__(self, adapter, provider: str):
        if getattr(adapter, "retries", 0):
            raise ValueError("disable hidden provider retries before wrapping")
        self.adapter, self.provider, self.revision = adapter, provider, adapter.revision

    def preflight(self, timeout):
        if timeout <= 0:
            raise PortError("deadline_exceeded", dispatched=False)
        if hasattr(self.adapter, "timeout"):
            configured = self.adapter.timeout
            if type(configured) not in (int, float) or configured <= 0:
                raise PortError("provider_timeout_invalid", dispatched=False)
            try:
                probe = copy(self.adapter)
                probe.timeout = min(configured, timeout)
            except Exception:
                raise PortError("provider_timeout_uncontrollable", dispatched=False) from None

    def complete(self, messages, tools, *, request_id, attempt_id, timeout, seed):
        self.preflight(timeout)
        adapter = copy(self.adapter) if hasattr(self.adapter, "timeout") else self.adapter
        if hasattr(adapter, "timeout"):
            adapter.timeout = min(adapter.timeout, timeout)
        started = time.monotonic()
        try:
            reply = adapter.complete(messages, tools)
        except PortError:
            raise
        except Exception as exc:
            usage = ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
                provider=self.provider, model_revision=self.revision, status="failed",
                elapsed_seconds=time.monotonic() - started, usage_known=False)
            return ModelOutput("", usage, getattr(exc, "code", "provider_" + type(exc).__name__))
        u = reply.usage
        inp, out = u.get("prompt_tokens"), u.get("completion_tokens")
        known = type(inp) is int and inp >= 0 and type(out) is int and out >= 0
        usage = ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
            provider=self.provider, model_revision=self.revision, status="success",
            input_tokens=inp if known else None, output_tokens=out if known else None,
            elapsed_seconds=time.monotonic() - started, usage_known=known)
        # Policy requests structured text, no role tools are invoked by this bridge.
        if reply.tool_calls:
            return ModelOutput("", usage)
        return ModelOutput(reply.text, usage)
