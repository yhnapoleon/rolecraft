"""Durable bounded agent runner over the W01/W06 adapter ports.

Pending commands are persisted before dispatch. Resume resends the identical
command or polls its saved job ID; environment idempotency owns exactly-once
local effects. No such guarantee is claimed for remote model billing.
"""
import time
import re
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone

from career_lab.contracts.v2 import (
    RunManifest, Observation, BeliefState, ActionProposal, Command, Budget,
    ModelAttemptUsage, VersionPoint, ProtocolError, digest, canonical,
)
from .belief import check_observation, update_belief, project_observation, MEMORY_CHANNELS
from .journal import RunJournal
from .projection import model_view
from .legal import validate_action
from .policies import PolicyContext
from .ports import PortError, port_error


def jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def utc(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


class ReferenceRunner:
    def __init__(self, environment, policy, model=None, *, max_retries=2,
                 max_invalid=3, max_polls=2, request_timeout=30.0, clock=time.time,
                 evaluator=None, expected_tools_digest=None, max_reconciles=2,
                 reconcile_wall_seconds=10.0, source_authorizer=None):
        if not 0 <= max_retries <= 5 or not 1 <= max_invalid <= 10 or not 1 <= max_polls <= 20:
            raise ValueError("invalid bounded retry configuration")
        if not 1 <= max_reconciles <= 10 or reconcile_wall_seconds <= 0:
            raise ValueError("invalid bounded reconcile configuration")
        self.max_reconciles, self.reconcile_wall_seconds = max_reconciles, reconcile_wall_seconds
        self.source_authorizer = source_authorizer
        if request_timeout <= 0:
            raise ValueError("positive timeout required")
        self.environment, self.policy, self.model = environment, policy, model
        self.max_retries, self.max_invalid, self.max_polls = max_retries, max_invalid, max_polls
        self.request_timeout, self.clock, self.evaluator = request_timeout, clock, evaluator
        self.expected_tools_digest = expected_tools_digest

    def run(self, manifest: RunManifest, *, goal: str, output: Path, resume=False):
        manifest = RunManifest.model_validate(manifest)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", manifest.id):
            raise ValueError("run id must be a safe directory name")
        if manifest.executor.kind != "reference_agent":
            raise PortError("reference_executor_required")
        if not resume and self.policy.uses_model and (self.model is None or
                (manifest.provider, manifest.model_revision) != (self.model.provider, self.model.revision)):
            raise PortError("model_identity_mismatch")
        journal = RunJournal(Path(output) / manifest.id)
        self.manifest, self.journal = manifest, journal
        identity = digest({"manifest": manifest.model_dump(mode="json"), "goal": goal, "policy": self.policy.name,
                           "policy_config": jsonable(vars(self.policy)), "limits": {
                               "max_retries": self.max_retries, "max_invalid": self.max_invalid,
                               "expected_tools_digest": self.expected_tools_digest,
                               "request_timeout": self.request_timeout, "max_polls": self.max_polls}})
        # vars(policy) may contain ActionProposal objects; normalize explicitly.
        with journal.locked():
            self.state = state = journal.load()
            if state is not None and not resume:
                raise PortError("run_exists_use_resume")
            if state is None and resume:
                raise PortError("run_not_found")
            if state is None:
                state = self.state = {
                    "identity": identity, "run_id": manifest.id, "manifest": manifest.model_dump(mode="json"),
                    "goal": goal, "policy": self.policy.name, "status": "running", "reason_code": None,
                    "started_epoch": self.clock(), "started_at": utc(self.clock()), "finished_at": None,
                    "model_calls": 0, "charged_tokens": 0, "action_attempts": 0, "polls": 0,
                    "model_reservation": None, "pending": None, "steps": [], "observations": [],
                    "belief": None, "decisions": [], "errors": [], "invalid_count": 0,
                    "evaluation": None,
                }
                self._save()
            elif state["identity"] != identity:
                raise PortError("resume_identity_mismatch")
            elif state["status"] in {"stopped", "failed", "completed"} and not state["pending"]:
                journal.export(state)
                return state
            state.setdefault("reconcile_attempts", 0)
            state.setdefault("quarantined_sources", [])
            state.setdefault("approved_memory_hashes", [])
            if resume and state["pending"] and (state["pending"]["attempts"] or state["pending"]["job_id"]):
                state["pending"]["needs_reconcile"] = True
            if state["model_reservation"]:
                reservation = state["model_reservation"]
                self._record_usage(ModelAttemptUsage(
                    request_id=reservation["request_id"], attempt_id=reservation["attempt_id"],
                    provider=manifest.provider, model_revision=manifest.model_revision, status="unknown",
                    elapsed_seconds=0, usage_known=False), reservation["reserved_tokens"])
                self._stop("failed", "model_interrupted_usage_unknown")
                return self.state
            state["status"] = "running"
            polls_this_run = 0
            try:
                while True:
                    if state["pending"] and state["pending"].get("needs_reconcile"):
                        outcome = self._reconcile_pending()
                        if outcome is None:
                            break
                        if outcome.status == "failed":
                            self._failed_step(outcome.error_code)
                        else:
                            self._complete_step(outcome)
                        continue
                    self._timeout()
                    if state["pending"]:
                        pending = state["pending"]
                        if pending["job_id"]:
                            if polls_this_run >= self.max_polls:
                                state["status"], state["reason_code"] = "waiting", "job_pending"
                                self._save()
                                break
                            state["polls"] += 1
                            polls_this_run += 1
                            self._save()
                            try:
                                outcome = self.environment.poll(manifest.session_id, pending["job_id"], self._timeout())
                            except (PortError, ProtocolError) as raw_error:
                                exc = port_error(raw_error)
                                self._error(exc.code, "poll")
                                if exc.retryable:
                                    continue
                                raise
                        else:
                            if state["action_attempts"] >= manifest.budget.actions:
                                raise PortError("action_budget_exhausted", ambiguous=True)
                            pending["attempts"] += 1
                            state["action_attempts"] += 1
                            self._save()
                            try:
                                outcome = self.environment.execute(
                                    manifest.session_id, Command.model_validate(pending["command"]), self._timeout())
                            except (PortError, ProtocolError) as raw_error:
                                exc = port_error(raw_error)
                                self._error(exc.code, "action", ambiguous=exc.ambiguous)
                                if exc.ambiguous:
                                    pending["needs_reconcile"] = True
                                    raise
                                if exc.retryable and pending["attempts"] <= self.max_retries:
                                    continue
                                self._failed_step(exc.code)
                                if exc.code in {"forbidden", "unauthorized"}:
                                    raise
                                if state["invalid_count"] >= self.max_invalid:
                                    raise PortError("repeated_action_failure")
                                continue
                        self._check_correlation(outcome)
                        if outcome.status == "pending":
                            pending["job_id"] = outcome.job_id
                            self._save()
                            continue
                        if outcome.status == "failed":
                            self._error(outcome.error_code, "action_result")
                            self._failed_step(outcome.error_code)
                            if state["invalid_count"] >= self.max_invalid:
                                raise PortError("repeated_action_failure")
                            continue
                        self._complete_step(outcome)
                        continue
                    if self.policy.uses_model and (self.model is None or (manifest.provider, manifest.model_revision) != (self.model.provider, self.model.revision)):
                        raise PortError("model_identity_mismatch")
                    observation = check_observation(
                        self.environment.observe(manifest.session_id, self._timeout()),
                        manifest.session_id, manifest.executor)
                    observation = self._observe(observation)
                    context = PolicyContext(goal, observation, BeliefState.model_validate(state["belief"]),
                                            tuple(state["steps"]), manifest.seed,
                                            tuple(state["approved_memory_hashes"]), self._policy_sources())
                    visible = model_view(context)
                    context = replace(context, observation=Observation.model_validate(visible["observation"]),
                                      belief=BeliefState.model_validate(visible["belief"]),
                                      history=tuple(visible["history"]))
                    try:
                        choice = self.policy.choose(context, self._call_model)
                    except (PortError, ProtocolError) as raw_error:
                        exc = port_error(raw_error)
                        if exc.code not in {"invalid_model_choice", "invalid_parameters", "tool_unavailable"}:
                            raise
                        self._error(exc.code, "choice")
                        state["invalid_count"] += 1
                        self._save()
                        if state["invalid_count"] >= self.max_invalid:
                            raise PortError("repeated_invalid_choice")
                        continue
                    if choice.action is None:
                        self._evaluate_stop(observation, choice.stop_reason)
                        break
                    validate_action(choice.action, observation)
                    request_id = digest([manifest.id, "action", len(state["decisions"])])
                    command = Command(schema_version=2, request_id=request_id, expected_version=observation.as_of.business_seq,
                        expected_workspace_revision=observation.as_of.workspace_revision,
                        operation=choice.action.tool, payload=choice.action.arguments)
                    state["decisions"].append({
                        "id": request_id, "observation_hash": digest(observation),
                        "as_of": observation.as_of.model_dump(mode="json"),
                        "candidates": [c.model_dump(mode="json") for c in choice.candidates],
                        "selected_id": choice.action.id, "reason": choice.reason,
                        "belief_hash": digest(state["belief"]),
                    })
                    state["pending"] = {"command": command.model_dump(mode="json"),
                        "action": choice.action.model_dump(mode="json"), "job_id": None,
                        "attempts": 0, "observation_hash": digest(observation)}
                    self._save()
            except (PortError, ProtocolError) as raw_error:
                exc = port_error(raw_error)
                self._error(exc.code, "runner", ambiguous=exc.ambiguous)
                status = "stopped" if exc.code.endswith("budget_exhausted") or exc.code == "deadline_exceeded" else "failed"
                self._stop(status, exc.code)
            journal.export(state)
            return state

    def _reconcile_pending(self):
        """Read-only recovery has a separate bounded window; never dispatch new effects."""
        pending = self.state["pending"]
        pending["job_confirmed_pending"] = False
        deadline = self.clock() + self.reconcile_wall_seconds
        for _ in range(self.max_reconciles):
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            self.state["reconcile_attempts"] += 1
            self._save()
            try:
                if pending["job_id"]:
                    self.state["polls"] += 1
                    outcome = self.environment.poll(self.manifest.session_id, pending["job_id"], min(remaining, self.request_timeout))
                else:
                    lookup = getattr(self.environment, "reconcile", None)
                    if lookup is None:
                        raise PortError("request_lookup_not_installed")
                    outcome = lookup(self.manifest.session_id, Command.model_validate(pending["command"]), min(remaining, self.request_timeout))
                if outcome is not None:
                    self._check_correlation(outcome)
                    if outcome.status != "pending":
                        return outcome
                    pending["job_id"] = outcome.job_id
                    pending["job_confirmed_pending"] = True
            except (PortError, ProtocolError) as raw_error:
                exc = port_error(raw_error)
                self._error(exc.code, "reconcile", ambiguous=True)
                if not exc.retryable:
                    self._stop("unresolved", exc.code)
                    return None
        if pending["job_id"] and pending.get("job_confirmed_pending"):
            pending["needs_reconcile"] = False
            self.state["status"], self.state["reason_code"] = "waiting", "job_pending"
            self._save()
            return None
        self._stop("unresolved", "request_result_unresolved")
        return None

    def _check_correlation(self, outcome):
        expected = self.state["pending"]["command"]["request_id"]
        supplied = [x for x in (outcome.request_id, outcome.boundary.request_id if outcome.boundary else None) if x]
        if outcome.status == "success" and not supplied:
            raise PortError("result_request_missing", ambiguous=True)
        job = self.state["pending"].get("job_id")
        if job is not None and outcome.job_id is not None and outcome.job_id != job:
            raise PortError("result_job_mismatch", ambiguous=True)
        if any(x != expected for x in supplied):
            raise PortError("result_request_mismatch", ambiguous=True)

    def _timeout(self):
        remaining = self.manifest.budget.wall_seconds - (self.clock() - self.state["started_epoch"])
        if remaining <= 0:
            raise PortError("deadline_exceeded")
        return min(self.request_timeout, remaining)

    def _save(self):
        self.journal.save(self.state)

    def _error(self, code, phase, **details):
        self.state["errors"].append({"code": code, "phase": phase, "at": utc(self.clock()), **details})
        self._save()

    def _policy_sources(self):
        sources = []
        for entry in self.state["observations"]:
            observed = Observation.model_validate(entry["value"])
            allowed = entry.get("approved_memory_hashes", ())
            observed, _ = project_observation(observed, allowed)
            sources.extend(observed.visible_sources)
        return tuple(sources)

    def _observe(self, observation):
        approved = []
        for fragment in observation.visible_sources:
            if fragment.channel in MEMORY_CHANNELS:
                status = self.source_authorizer(observation, fragment) if self.source_authorizer else "unknown"
                if status in {"role_private", "prompt_only", "model_only"}:
                    raise PortError("private_memory_rejected")
                if status == "learner_known":
                    approved.append(digest(fragment))
        observation, quarantined = project_observation(observation, approved)
        approved = [digest(f) for f in observation.visible_sources if f.channel in MEMORY_CHANNELS]
        self.state["quarantined_sources"].extend(quarantined)
        self.state["approved_memory_hashes"] = approved
        schemas = sorted([{k: t.model_dump(mode="json")[k] for k in ("name", "capability", "parameters_hash")} for t in observation.tools], key=lambda t: t["name"])
        if self.expected_tools_digest is not None and digest(schemas) != self.expected_tools_digest:
            raise PortError("tool_schema_drift")
        prior = BeliefState.model_validate(self.state["belief"]) if self.state["belief"] else None
        belief = update_belief(prior, observation, approved)
        oh = digest(observation)
        if not any(x["hash"] == oh for x in self.state["observations"]):
            self.state["observations"].append({"hash": oh, "value": observation.model_dump(mode="json"),
                                               "approved_memory_hashes": [digest(f) for f in observation.visible_sources if f.channel in MEMORY_CHANNELS]})
        self.state["belief"] = belief.model_dump(mode="json")
        self._save()
        return observation

    def _failed_step(self, code):
        pending = self.state["pending"]
        self.state["steps"].append({"id": pending["command"]["request_id"],
            "action": pending["action"]["tool"], "outcome": "failed", "error_code": code,
            "observation_hash": pending["observation_hash"], "observations": [],
            "dispatch_attempts": pending["attempts"]})
        self.state["pending"] = None
        self.state["invalid_count"] += 1
        self._save()

    def _complete_step(self, outcome):
        self._check_correlation(outcome)
        observation = check_observation(outcome.observation, self.manifest.session_id, self.manifest.executor)
        pending = self.state["pending"]
        if outcome.step.outcome != "success":
            raise PortError("step_outcome_mismatch", ambiguous=True)
        if any(getattr(outcome.step.as_of, k) > getattr(observation.as_of, k) for k in ("business_seq", "workspace_revision", "storage_revision")):
            raise PortError("step_from_future", ambiguous=True)
        if outcome.step.action != pending["action"]["tool"]:
            raise PortError("step_action_mismatch", ambiguous=True)
        if any(r.session_id != self.manifest.session_id for r in outcome.step.evidence_refs):
            raise PortError("step_reference_mismatch", ambiguous=True)
        if outcome.boundary and outcome.boundary.request_id != pending["command"]["request_id"]:
            raise PortError("boundary_request_mismatch", ambiguous=True)
        # Observation and history share one durable checkpoint.
        observation = self._observe(observation)
        row = outcome.step.model_dump(mode="json")
        row.update(command_request_id=pending["command"]["request_id"], observation_hash=digest(observation),
                   dispatch_attempts=pending["attempts"],
                   boundary=outcome.boundary.model_dump(mode="json") if outcome.boundary else None)
        self.state["steps"].append(row)
        self.state["pending"] = None
        self.state["invalid_count"] = 0
        self._save()

    def _call_model(self, messages):
        for attempt in range(self.max_retries + 1):
            try:
                return self._call_model_attempt(messages)
            except (PortError, ProtocolError) as raw_error:
                exc = port_error(raw_error)
                self._error(exc.code, "model")
                if exc.code not in {"model_failed", "model_timeout", "model_call_failed"} or attempt == self.max_retries:
                    raise

    def _call_model_attempt(self, messages):
        budget, state = self.manifest.budget, self.state
        if budget.currency_limit is not None:
            raise PortError("provider_cost_reservation_unavailable")
        # UTF-8 bytes reserve a conservative input upper bound. Actual usage remains separate.
        reserve = len(canonical(messages).encode()) + self.model.output_token_limit + 256
        if state["model_calls"] >= budget.model_calls:
            raise PortError("model_budget_exhausted")
        if budget.tokens is not None and state["charged_tokens"] + reserve > budget.tokens:
            raise PortError("token_budget_exhausted")
        remaining = self._timeout()
        preflight = getattr(self.model, "preflight", None)
        if preflight is not None:
            preflight(remaining)
        request_id = digest([self.manifest.id, "decision", len(state["decisions"]), state["model_calls"]])
        attempt_id = request_id + ":0"
        state["model_calls"] += 1
        state["charged_tokens"] += reserve
        state["model_reservation"] = {"request_id": request_id, "attempt_id": attempt_id, "reserved_tokens": reserve}
        self._save()
        try:
            result = self.model.complete(messages, [], request_id=request_id, attempt_id=attempt_id,
                                         timeout=self._timeout(), seed=self.manifest.seed)
        except (PortError, ProtocolError) as raw_error:
            exc = port_error(raw_error)
            if not exc.dispatched:
                state["model_calls"] -= 1
                state["charged_tokens"] -= reserve
                state["model_reservation"] = None
                self._save()
            else:
                self._record_usage(ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
                    provider=self.manifest.provider, model_revision=self.manifest.model_revision,
                    status="unknown", elapsed_seconds=0, usage_known=False), reserve)
            raise exc
        except Exception:
            usage = ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
                provider=self.manifest.provider, model_revision=self.manifest.model_revision,
                status="failed", elapsed_seconds=0, usage_known=False)
            self._record_usage(usage, reserve)
            raise PortError("model_call_failed") from None
        usage = result.usage
        if (usage.request_id, usage.attempt_id, usage.provider, usage.model_revision) != (
                request_id, attempt_id, self.manifest.provider, self.manifest.model_revision):
            self._record_usage(ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
                provider=self.manifest.provider, model_revision=self.manifest.model_revision,
                status="unknown", elapsed_seconds=usage.elapsed_seconds, usage_known=False), reserve)
            raise PortError("model_usage_identity_mismatch")
        self._record_usage(usage, reserve)
        if usage.usage_known and usage.input_tokens + usage.output_tokens > reserve:
            raise PortError("provider_exceeded_token_reservation")
        if usage.status != "success":
            raise PortError(result.error_code or "model_" + usage.status)
        self._timeout()
        return result.text

    def _record_usage(self, usage, reserve):
        state = self.state
        state["manifest"]["attempts"].append(usage.model_dump(mode="json"))
        if usage.usage_known:
            state["charged_tokens"] += usage.input_tokens + usage.output_tokens - reserve
        state["model_reservation"] = None
        self._save()

    def _evaluate_stop(self, observation, reason):
        if self.evaluator is None:
            self._stop("stopped", "unverified_" + (reason or "policy_stop"))
            return
        evaluation = self.evaluator(self.manifest, observation, tuple(self.state["steps"]))
        if evaluation.get("evaluation") != self.manifest.evaluation.model_dump(mode="json"):
            raise PortError("evaluation_identity_mismatch")
        if evaluation.get("accepted") is not None and type(evaluation.get("accepted")) is not bool:
            raise PortError("invalid_terminal_evaluation")
        self.state["evaluation"] = evaluation
        self._stop("completed" if evaluation.get("accepted") is True else "stopped",
                   "verified_terminal" if evaluation.get("accepted") is True else "terminal_not_accepted")

    def _stop(self, status, reason):
        pending = self.state["pending"]
        if pending and reason in {"unfiltered_observation", "private_memory_rejected", "observation_identity_mismatch", "observation_source_mismatch", "observation_reference_mismatch", "tool_schema_drift"}:
            self.state["quarantined_pending"] = pending
            self.state["pending"] = None
            pending = None
            status = "failed"
        if pending:
            if pending["attempts"] or pending["job_id"]:
                status = "unresolved"
                pending["needs_reconcile"] = True
            else:
                self.state["pending"] = None
        self.state["status"], self.state["reason_code"] = status, reason
        self.state["finished_at"] = utc(self.clock())
        self._save()
        self.journal.export(self.state)
