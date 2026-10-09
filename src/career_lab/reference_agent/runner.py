"""Bounded checklist slice of the old executor, consuming current request results."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import ConfigDict, Field, JsonValue

from career_lab.contracts.v2.core import (
    V2,
    ActualConsumption,
    AuthContext,
    Command,
    ProtocolError,
    Timestamp,
    digest,
)
from career_lab.contracts.v2.data import ActionProposal
from career_lab.contracts.v2.research import RequestResult, RunManifest, RuntimeBundle
from career_lab.delegations.credentials import Credentials, load_credentials
from career_lab.reference_agent.journal import RunJournal
from career_lab.reference_agent.ports import OPERATIONS, HttpEnvironment
from career_lab.reference_agent.suite import load_manifest
from career_lab.registry.v3.store import BundleRegistry
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import V2Store


class Checklist(V2):
    schema_version: Literal[2]
    actions: tuple[ActionProposal, ...] = Field(min_length=1)


class Checkpoint(V2):
    model_config = ConfigDict(frozen=False, extra="forbid")
    identity: str
    executing_code_digest: str
    business_terminal_verified: Literal[False] = False
    manifest: RunManifest
    status: Literal["running", "pending", "needs_context", "unresolved", "failed", "completed"]
    started_at: Timestamp
    pending: Command | None = None
    results: list[RequestResult] = []
    dispatch_count: int = 0
    error_code: str | None = None


def source_digest() -> str:
    return digest(
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        }
    )


def fixed_checklist(
    manifest: RunManifest,
    registry: BundleRegistry,
    runtime_id: str,
    evaluation_id: str,
) -> Checklist:
    registry.bind(runtime_id, evaluation_id)
    runtime = registry.load(runtime_id)
    if not isinstance(runtime, RuntimeBundle) or runtime.source != manifest.source:
        raise ProtocolError("run_runtime_mismatch")
    if (
        RuntimeBundle.model_validate_json(registry.resolve_manifest(runtime_id, manifest.runtime))
        != runtime
    ):
        raise ProtocolError("run_runtime_mismatch")
    registry.resolve_manifest(evaluation_id, manifest.evaluation)
    if manifest.policy is None or runtime.skills is not None:
        raise ProtocolError("reference_policy_unavailable", status=503)
    if (
        manifest.provider != "local-checklist"
        or manifest.model_revision != "none"
        or manifest.budget.model_calls
    ):
        raise ProtocolError("reference_model_unavailable", status=503)
    if manifest.split == "test":
        raise ProtocolError("confirmatory_runner_unavailable", status=503)
    checklist = Checklist.model_validate_json(registry.resolve_file(runtime_id, manifest.policy))
    if any(action.tool not in OPERATIONS for action in checklist.actions):
        raise ProtocolError("reference_operation_unavailable", status=503)
    return checklist


def authenticate_run(
    manifest: RunManifest, credentials: Credentials, database: Path, scenario_root: Path
) -> AuthContext:
    module = ScenarioModule(scenario_root)
    if module.release is None:
        raise ProtocolError("run_published_scenario_required")
    if not database.is_file():
        raise ProtocolError("run_database_unavailable", status=503)
    # Existing trusted authentication API, opened read-only like the engineer CLI.
    store = V2Store(
        "sqlite:///file:" + quote(str(database.resolve()), safe="/") + "?mode=ro&uri=true"
    )
    try:
        auth = store.authenticate(credentials.session_id, credentials.token)
        bindings = store.view(auth).bindings
        if auth.executor.kind != "reference_agent" or auth.executor != manifest.executor:
            raise ProtocolError("reference_executor_required", status=403)
        if (
            auth.session_id != manifest.session_id
            or bindings != module.bindings
            or bindings.scenario != manifest.scenario
            or bindings.evaluation != manifest.evaluation
        ):
            raise ProtocolError("run_session_binding_mismatch", status=409)
    finally:
        store.db.engine.dispose()
    return auth


def load_checkpoint(
    journal: RunJournal, manifest: RunManifest, identity: str, code: str, resume: bool
) -> Checkpoint:
    saved = journal.load()
    if saved is not None and not resume:
        raise ProtocolError("run_exists_use_resume", status=409)
    if saved is None and resume:
        raise ProtocolError("run_not_found", status=404)
    state = (
        Checkpoint.model_validate(saved)
        if saved is not None
        else Checkpoint(
            identity=identity,
            executing_code_digest=code,
            manifest=manifest,
            status="running",
            started_at=datetime.now(UTC),
        )
    )
    if state.identity != identity:
        raise ProtocolError("resume_identity_mismatch", status=409)
    return state


def run_checklist(
    *,
    manifest_path: Path,
    registry_path: Path,
    runtime_id: str,
    evaluation_id: str,
    database: Path,
    credentials_path: Path,
    scenario_root: Path,
    output: Path,
    resume: bool = False,
) -> dict[str, JsonValue]:
    manifest = load_manifest(manifest_path)
    credentials = load_credentials(credentials_path)
    auth = authenticate_run(manifest, credentials, database, scenario_root)
    checklist = fixed_checklist(manifest, BundleRegistry(registry_path), runtime_id, evaluation_id)
    code = source_digest()
    identity = digest(
        {
            "manifest": manifest.model_dump(mode="json"),
            "runtime": runtime_id,
            "evaluation": evaluation_id,
            "executing_code": code,
        }
    )
    journal = RunJournal(output)
    with journal.locked():
        state = load_checkpoint(journal, manifest, identity, code, resume)
        if state.status in {"completed", "failed"}:
            return state.model_dump(mode="json")
        environment = HttpEnvironment(credentials, auth.executor)
        try:
            advance(state, checklist, environment, journal)
        finally:
            environment.close()
        return state.model_dump(mode="json")


def advance(
    state: Checkpoint, checklist: Checklist, environment: HttpEnvironment, journal: RunJournal
) -> None:
    if state.status == "failed":
        return

    def save() -> None:
        now = datetime.now(UTC)
        terminal = state.status in {"completed", "failed"}
        status = state.status if terminal or state.status == "running" else "blocked"
        state.manifest = state.manifest.model_copy(
            update={
                "status": status,
                "started_at": state.started_at,
                "ended_at": now if terminal else None,
                "actual_consumption": ActualConsumption(
                    actions=state.dispatch_count,
                    wall_seconds=(now - state.started_at).total_seconds(),
                    usage_complete=False,
                    cost_complete=False,
                ),
            }
        )
        journal.save(state.model_dump(mode="json"))

    save()
    try:
        while len(state.results) < len(checklist.actions) or state.pending is not None:
            if state.pending is None:
                if state.dispatch_count >= state.manifest.budget.actions:
                    raise ProtocolError("run_budget_exhausted")
                action = checklist.actions[len(state.results)]
                public = environment.state(remaining_seconds(state))
                timeout = remaining_seconds(state)
                state.pending = Command(
                    schema_version=2,
                    request_id=digest(
                        [state.identity, len(state.results), action.model_dump(mode="json")]
                    ),
                    expected_version=public.business_seq,
                    expected_workspace_revision=public.workspace_revision,
                    operation=action.tool,
                    payload=action.arguments,
                )
                state.dispatch_count += 1
                save()  # Durable intent before dispatch; uncertain requests are only queried.
                environment.execute(state.pending, timeout)
            result = environment.recover(state.pending)
            if state.results and state.results[-1].request_id == result.request_id:
                state.results[-1] = result
            else:
                state.results.append(result)
            state.status = "running" if result.status == "completed" else result.status
            state.error_code = None
            if result.status != "completed":
                save()
                return
            state.pending = None
            save()
        state.status = "completed"
    except ProtocolError as error:
        confirmed_conflict = error.status == 409 and error.code == "request_id_reused"
        state.status = "failed" if confirmed_conflict or state.pending is None else "unresolved"
        state.error_code = error.code
    save()


def remaining_seconds(state: Checkpoint) -> float:
    elapsed = (datetime.now(UTC) - state.started_at).total_seconds()
    remaining = state.manifest.budget.wall_seconds - elapsed
    if remaining <= 0:
        raise ProtocolError("run_budget_exhausted")
    return min(10, remaining)
