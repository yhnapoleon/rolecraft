"""Local adapter interfaces, not additions to the shared wire protocol.

The integrator supplies codecs for the W06 HTTP response and W01 snapshot service.
Policies never receive a store, ScenarioBundle, SnapshotExport or evaluator.
"""
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx

from career_lab.contracts.v2 import (
    ActionBoundary, ActionProposal, Command, ModelAttemptUsage, Observation,
    ObservedStep, RestoreResult, SnapshotExport, VersionPoint, ProtocolError,
)


class PortError(Exception):
    def __init__(self, code: str, *, retryable=False, ambiguous=False, dispatched=True):
        self.code, self.retryable, self.ambiguous, self.dispatched = code, retryable, ambiguous, dispatched
        super().__init__(code)


def port_error(exc):
    if isinstance(exc, PortError):
        return exc
    code = getattr(exc, "code", type(exc).__name__)
    retryable = getattr(exc, "status", 0) in {429, 502, 503, 504, 529} and not code.endswith(("unavailable", "not_installed"))
    return PortError(code, retryable=retryable)


@dataclass(frozen=True)
class ActionOutcome:
    status: str  # success, failed, pending
    observation: Observation | None = None
    step: ObservedStep | None = None
    boundary: ActionBoundary | None = None
    job_id: str | None = None
    error_code: str | None = None
    request_id: str | None = None  # Echoed by trusted service, never inferred from step.id.

    def __post_init__(self):
        if self.status not in {"success", "failed", "pending"}:
            raise ValueError("invalid action outcome")
        if self.status == "pending" and not self.job_id:
            raise ValueError("pending outcome needs job_id")
        if self.status == "success" and (self.observation is None or self.step is None):
            raise ValueError("success needs actual observation and step")
        if self.status == "success" and not (self.request_id or self.boundary):
            raise PortError("result_request_missing", ambiguous=True)
        if self.request_id and self.boundary and self.request_id != self.boundary.request_id:
            raise PortError("result_request_mismatch", ambiguous=True)
        if self.status == "failed" and not self.error_code:
            raise ValueError("failure needs error_code")


def require_result_binding(outcome, request_id, *, job_id=None):
    """Trust service correlation, never source-step identity or request position."""
    supplied = [x for x in (outcome.request_id, outcome.boundary.request_id if outcome.boundary else None) if x]
    if not supplied:
        raise PortError("result_request_missing", ambiguous=True)
    if any(x != request_id for x in supplied):
        raise PortError("result_request_mismatch", ambiguous=True)
    if job_id is not None and outcome.job_id != job_id:
        raise PortError("result_job_mismatch", ambiguous=True)
    return outcome


class EnvironmentPort(Protocol):
    def observe(self, session_id: str, timeout: float) -> Observation: ...
    def execute(self, session_id: str, command: Command, timeout: float) -> ActionOutcome: ...
    def poll(self, session_id: str, job_id: str, timeout: float) -> ActionOutcome: ...
    def reconcile(self, session_id: str, command: Command, timeout: float) -> ActionOutcome | None:
        """Read-only lookup by original request ID; None means unresolved, never execute."""
        ...


@dataclass(frozen=True)
class HttpBindings:
    """Installed by W06. Paths and codecs must be fixed in the runtime tool bundle."""
    observation_path: Callable[[str], str]
    command_path: Callable[[str, str], str]
    job_path: Callable[[str, str], str]
    decode_observation: Callable[[dict], Observation]
    decode_outcome: Callable[[dict], ActionOutcome]
    request_result_path: Callable[[str, str], str] | None = None


class HttpEnvironment:
    def __init__(self, base_url: str, token: str, bindings: HttpBindings, *, transport=None):
        if not base_url.startswith(("http://", "https://")) or not token:
            raise ValueError("HTTP endpoint and scoped credential required")
        self.bindings = bindings
        # No automatic redirect/retry: scoped credentials never follow server-provided URLs.
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/", headers={"Authorization": "Bearer " + token},
            transport=transport, follow_redirects=False, trust_env=False,
        )

    def close(self):
        self._client.close()

    def _request(self, method, path, timeout, body=None):
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise PortError("unsafe_endpoint")
        if timeout <= 0:
            raise PortError("deadline_exceeded")
        try:
            response = self._client.request(method, path, json=body, timeout=timeout)
        except httpx.TimeoutException:
            raise PortError("transport_timeout", retryable=True, ambiguous=method != "GET") from None
        except httpx.TransportError:
            raise PortError("transport_error", retryable=True, ambiguous=method != "GET") from None
        status = response.status_code
        if status >= 300:
            codes = {401: "unauthorized", 403: "forbidden", 404: "not_found",
                     409: "version_or_request_conflict", 422: "invalid_parameters", 429: "rate_limited"}
            raise PortError(codes.get(status, "http_" + str(status)),
                            retryable=status in {429, 502, 503, 504},
                            ambiguous=method != "GET" and status >= 500)
        try:
            return response.json()
        except ValueError:
            raise PortError("invalid_json", ambiguous=method != "GET") from None

    def observe(self, session_id, timeout):
        raw = self._request("GET", self.bindings.observation_path(session_id), timeout)
        try:
            return Observation.model_validate(self.bindings.decode_observation(raw))
        except (ValueError, TypeError, KeyError):
            raise PortError("invalid_observation") from None

    def execute(self, session_id, command, timeout):
        raw = self._request("POST", self.bindings.command_path(session_id, command.operation),
                            timeout, command.model_dump(mode="json"))
        return self._decode(raw, ambiguous=True)

    def poll(self, session_id, job_id, timeout):
        raw = self._request("GET", self.bindings.job_path(session_id, job_id), timeout)
        return self._decode(raw, ambiguous=False)

    def reconcile(self, session_id, command, timeout):
        if self.bindings.request_result_path is None:
            raise PortError("request_lookup_not_installed")
        try:
            raw = self._request("GET", self.bindings.request_result_path(session_id, command.request_id), timeout)
        except PortError as exc:
            if exc.code == "not_found":
                return None
            raise
        return self._decode(raw, ambiguous=False)

    def _decode(self, raw, ambiguous):
        try:
            result = self.bindings.decode_outcome(raw)
            if not isinstance(result, ActionOutcome):
                raise TypeError("codec must return ActionOutcome")
            return result
        except (ValueError, TypeError, KeyError):
            raise PortError("invalid_action_result", ambiguous=ambiguous) from None


@dataclass(frozen=True)
class ModelOutput:
    text: str
    usage: ModelAttemptUsage
    error_code: str | None = None


class ModelPort(Protocol):
    provider: str
    revision: str
    output_token_limit: int
    def complete(self, messages: list[dict], tools: list[dict], *,
                 request_id: str, attempt_id: str, timeout: float, seed: int) -> ModelOutput: ...


class SnapshotPort(Protocol):
    """Private research interface. Never register these operations as learner tools."""
    def export(self, session_id: str, as_of: VersionPoint) -> SnapshotExport: ...
    def restore(self, snapshot: SnapshotExport, session_id: str, request_id: str) -> RestoreResult: ...
    def remap_action(self, action: ActionProposal, restored: RestoreResult) -> ActionProposal: ...
    def environment(self, restored: RestoreResult) -> EnvironmentPort: ...
    def parent_digest(self, session_id: str) -> str: ...
    def prefix_digest(self, snapshot: SnapshotExport) -> str:
        """Authoritative W01 normalized prefix digest, not a W09 approximation."""
        ...
