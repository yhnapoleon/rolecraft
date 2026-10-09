"""Explicit installation point. No imports, code execution or model from user input."""

from dataclasses import dataclass
from typing import Callable, Literal, get_args, get_origin
from pydantic import BaseModel, ValidationError
from career_lab.contracts.v2 import *
from career_lab.storage.v2_store import V2Store, Mutation, TransactionResult


class CreateSessionV2(V2):
    schema_version: Literal[2]
    scenario: Identifier
    work_language: Literal["zh", "en"] | None = None


class V2Response(V2):
    result: dict[str, JsonValue]


class JobEnvelope(V2):
    origin_request_id: Identifier
    job_id: Identifier
    context: JobContextSnapshot
    command: Command
    operation: Identifier
    capability: Literal["read", "act", "submit", "delegate"] = "act"


@dataclass(frozen=True)
class ScenarioRegistration:
    bindings: SessionBindings
    baseline_config: AssistantConfig
    resources: dict
    scenario_state: ScenarioStateV2 | None = None
    work_language: Literal["zh", "en"] | None = None


@dataclass(frozen=True)
class StoreJobHandler:
    callback: Callable
    retry_on_error: bool = True


@dataclass(frozen=True)
class Operation:
    name: str
    capability: str
    request_model: type[V2]
    handler: Callable
    mutates: bool = True
    response_model: type[V2] | None = None
    approval_policy: Callable | None = None
    action_name: str | None = None
    action_field: str | None = None
    service_mode: bool = False
    event_projector: Callable | None = None
    preview_handler: Callable | None = None
    ready: bool = True
    unavailable_code: str | None = None


# Public API/tool installation whitelist. Internal snapshot/restore is deliberately absent.
PUBLIC_OPERATIONS = {
    "configuration.apply",
    "workbench.read",
    "objects.read",
    "turns.display",
    "requests.read",
    "actions",
    "tests.create",
    "tests.list",
    "turns.create",
    "submissions.create",
    "submissions.list",
    "feedback.records.read",
    "feedback.responses.create",
    "feedback.responses.read",
    "feedback.responses.list",
    "feedback.create",
    "feedback.read",
    "approvals.resolve",
    "materials.list",
    "timeline",
    "evidence.read",
    "work_items.create",
    "work_items.list",
    "work_items.update",
    "work_items.batch",
    "work_products.adopt",
    "work_products.create",
    "work_products.list",
    "work_products.versions.create",
    "work_products.versions.list",
    "work_products.shares.create",
    "work_products.shares.change",
    "work_products.shares.list",
    "workspace_imports",
    "workspace_imports.read",
    "workspace_imports.list",
    "reviews.create",
    "reviews.read",
    "revision_cycles",
    "observation",
    "tools",
    "delegations.create",
    "delegations.revoke",
}


class ExtensionRegistry:
    def __init__(self):
        self.object_models = {}
        self.scenarios = {}
        self.operations = {}
        self.cli = {}
        self.job_handlers = {}
        self.reference_resolvers = {}
        self.contextual_reference_resolvers = set()

    def register_object_model(self, kind, model):
        if kind in self.object_models:
            raise ValueError("object model already installed")
        self.object_models[kind] = model

    def register_reference_resolver(self, kind, resolver, *, contextual=False):
        if kind in self.reference_resolvers:
            raise ValueError("reference resolver already registered")
        self.reference_resolvers[kind] = resolver
        if contextual:
            self.contextual_reference_resolvers.add(kind)

    def register_scenario(self, name, scenario: ScenarioRegistration):
        if name in self.scenarios:
            raise ValueError("scenario already registered")
        self.scenarios[name] = scenario

    def register(self, operation: Operation):
        if operation.name == "requests.read" and (
            operation.mutates or operation.capability != "read"
        ):
            raise ValueError("request result lookup is read-only")
        if operation.ready and operation.unavailable_code is not None:
            raise ValueError("ready operation cannot have unavailable code")
        if not operation.ready and operation.unavailable_code is None:
            raise ValueError("unready operation needs unavailable code")
        if operation.name not in PUBLIC_OPERATIONS:
            raise ValueError("not a public module slot")
        if operation.preview_handler and operation.name != "workspace_imports":
            raise ValueError("preview hook reserved for workspace import")
        if operation.name in self.operations:
            raise ValueError("operation already installed")
        if operation.capability not in {"read", "act", "submit", "delegate"}:
            raise ValueError("invalid public capability")
        if operation.mutates and operation.capability == "read":
            raise ValueError("read capability cannot mutate")
        if not issubclass(operation.request_model, V2):
            raise TypeError("v2 request model required")
        if operation.service_mode and operation.name not in {
            "delegations.create",
            "delegations.revoke",
        }:
            raise ValueError("service mode reserved for auth control plane")
        actions = self.operation_actions(operation)
        if operation.event_projector is not None and actions is None:
            raise ValueError("projected action field must declare Literal values")
        if actions is not None:
            for installed in self.operations.values():
                prior = self.operation_actions(installed)
                if prior is not None and actions & prior:
                    raise ValueError("public action already registered")
        self.operations[operation.name] = operation

    @staticmethod
    def operation_actions(operation):
        if not operation.mutates:
            return frozenset()
        if not operation.action_field:
            return frozenset((operation.action_name or operation.name,))
        field = operation.request_model.model_fields.get(operation.action_field)
        if field is None or get_origin(field.annotation) is not Literal:
            return None
        return frozenset(get_args(field.annotation))

    def projector_for_action(self, action):
        """Select only from installed registrations and a persisted action name.

        Dynamic string fields are not proof of routing. Ambiguous registrations
        fail closed rather than selecting another module's projector.
        """
        matches = []
        for op in self.operations.values():
            if not op.mutates:
                continue
            if op.action_field:
                field = op.request_model.model_fields.get(op.action_field)
                matched = (
                    field is not None
                    and get_origin(field.annotation) is Literal
                    and action in get_args(field.annotation)
                )
            else:
                matched = action == (op.action_name or op.name)
            if matched:
                matches.append(op)
        if len(matches) > 1:
            raise ProtocolError("event_projection_ambiguous", status=503)
        return matches[0].event_projector if matches else None

    def availability(self, name):
        builtins = {"requests.read": "read", "jobs.refresh": "act"}
        if name in builtins:
            return OperationAvailability(
                name=name, installed=True, ready=True, capability=builtins[name]
            )
        operation = self.operations.get(name)
        if operation is None:
            return OperationAvailability(
                name=name,
                installed=False,
                ready=False,
                unavailable_code="module_unavailable"
                if name in PUBLIC_OPERATIONS
                else "operation_not_public",
            )
        return OperationAvailability(
            name=name,
            installed=True,
            ready=operation.ready,
            capability=operation.capability,
            unavailable_code=operation.unavailable_code,
        )

    def register_cli(self, name, configure_parser):
        if name in self.cli:
            raise ValueError("CLI already registered")
        self.cli[name] = configure_parser

    def install_cli(self, subparsers):
        for name, configure in self.cli.items():
            configure(subparsers.add_parser(name))

    def register_job(self, name, handler):
        if name in self.job_handlers:
            raise ValueError("job already registered")
        self.job_handlers[name] = handler


class SessionAccess(str):
    def __new__(cls, sid, context):
        value = super().__new__(cls, sid)
        value.context = context
        return value


def public_state(state):
    # Scenario-specific resource/milestone projections belong to the installed observation module.
    return state.model_dump(mode="json", exclude={"resources", "applied_milestones"})


class Gateway:
    def __init__(self, store: V2Store, registry: ExtensionRegistry):
        self.store, self.registry = store, registry
        for kind, resolver in registry.reference_resolvers.items():
            contextual = kind in registry.contextual_reference_resolvers
            if kind not in store.reference_resolvers:
                store.register_reference_resolver(kind, resolver, contextual=contextual)
            elif (
                store.reference_resolvers[kind] is not resolver
                or (kind in store.contextual_reference_resolvers) != contextual
            ):
                raise ValueError("incompatible reference resolver registration")
        for kind, model in registry.object_models.items():
            if kind not in store.object_models:
                store.register_object(kind, model)
            elif store.object_models[kind] is not model:
                raise ValueError("incompatible object model registration")

    def create(self, request: CreateSessionV2):
        scenario = getattr(self.registry, "language_scenarios", {}).get(
            (request.scenario, request.work_language)
        ) or self.registry.scenarios.get(request.scenario)
        if scenario is None:
            raise ProtocolError("scenario_module_unavailable", status=503)
        if request.work_language is not None and request.work_language != scenario.work_language:
            raise ProtocolError("work_language_unavailable", status=503)
        state, token = self.store.create_session(
            scenario.bindings,
            scenario.baseline_config,
            scenario.resources,
            scenario_state=scenario.scenario_state,
        )
        return {
            "schema_version": 2,
            "session_id": state.session_id,
            "token": token,
            "state": public_state(state),
            "binding": {
                "protocol": 2,
                "sessionId": state.session_id,
                "workLanguage": scenario.work_language,
                "scenarioHash": scenario.bindings.scenario.sha256,
            },
        }

    def dispatch(self, auth, name, body=None, route_params=None):
        active = getattr(self.registry, "active_bindings", None)
        operation = self.registry.operations.get(name)
        if active and (name == "jobs.refresh" or operation is not None and operation.mutates):
            # Session bindings are immutable. This check also covers service-mode grants.
            binding = self.store.query(auth, lambda view: view.bindings)
            if binding not in active:
                raise ProtocolError("scenario_read_only", status=409)
        if name == "jobs.refresh":
            command = Command.model_validate(body)
            if command.operation != "jobs.refresh" or command.payload != {
                "job_id": (route_params or {}).get("job_id")
            }:
                raise ProtocolError("operation_route_mismatch", status=403)
            result = self.store.refresh_job(auth, command, command.payload["job_id"])
            return self.public_result(auth, result)
        if name == "requests.read":
            query = RequestResultQuery.model_validate(body or route_params)
            return self.request_result(auth, query.request_id).model_dump(mode="json")
        op = self.registry.operations.get(name)
        if op is None:
            raise ProtocolError("module_unavailable", f"{name} is not installed", 503)
        if not op.ready:
            raise ProtocolError(op.unavailable_code or "module_unavailable", status=503)
        params = route_params or {}
        self.store.authorize(auth, op.capability)
        if op.mutates:
            command = Command.model_validate(body)
            payload = op.request_model.model_validate(command.payload)
            expected_action = (
                getattr(payload, op.action_field)
                if op.action_field
                else (op.action_name or op.name)
            )
            if command.operation != expected_action:
                raise ProtocolError("operation_route_mismatch", status=403)
            command = Command.model_validate(
                command.model_dump(mode="json") | {"payload": payload.model_dump(mode="json")}
            )
            # Endpoint object IDs are part of the fingerprint and cannot be silently substituted.
            if params:
                for key, value in params.items():
                    if command.payload.get(key) != value:
                        raise ProtocolError("route_object_mismatch", status=409)
            if op.preview_handler is not None and getattr(payload, "mode", None) == "preview":
                self.store.authorize(auth, "read", command.operation)
                result = self.store.query(
                    auth,
                    lambda view: op.preview_handler(view, command, auth),
                    operation=command.operation,
                )
                if op.response_model is None:
                    raise ProtocolError("module_response_contract_missing", status=503)
                try:
                    result = op.response_model.model_validate(
                        result.model_dump(mode="json") if isinstance(result, BaseModel) else result
                    )
                except ValidationError as exc:
                    raise ProtocolError("module_response_invalid", status=503) from exc
                return {"schema_version": 2, "result": result.model_dump(mode="json")}
            if op.service_mode:
                self.store.authorize(auth, op.capability, command.operation)
                result = op.handler(self.store, payload, auth, command.request_id)
                if op.response_model is None:
                    raise ProtocolError("module_response_contract_missing", status=503)
                try:
                    result = op.response_model.model_validate(
                        result.model_dump(mode="json") if isinstance(result, BaseModel) else result
                    )
                except ValidationError as exc:
                    raise ProtocolError("module_response_invalid", status=503) from exc
                return {"schema_version": 2, "result": result.model_dump(mode="json")}
            result = self.store.execute(
                auth,
                command,
                op.handler,
                capability=op.capability,
                approval_policy=op.approval_policy,
            )
            return self.public_result(
                auth,
                result,
                self.registry.projector_for_action(command.operation)
                if result.replayed
                else op.event_projector,
                operation=command.operation,
            )
        self.store.authorize(auth, op.capability, op.action_name or op.name)
        payload = op.request_model.model_validate(body or params)
        result = self.store.query(
            auth, lambda view: op.handler(view, payload, auth), operation=op.action_name or op.name
        )
        if op.response_model is None:
            raise ProtocolError("module_response_contract_missing", status=503)
        try:
            result = op.response_model.model_validate(
                result.model_dump(mode="json") if isinstance(result, BaseModel) else result
            )
        except ValidationError as exc:
            raise ProtocolError("module_response_invalid", status=503) from exc
        payload = (
            result.model_dump(mode="json", exclude={"visible_sources": {"__all__": {"fact_ids"}}})
            if name == "observation"
            else result.model_dump(mode="json")
        )
        return {"schema_version": 2, "result": payload}

    def request_result(self, auth, request_id):
        meta, response, links = self.store.request_result(auth, request_id)
        jobs = []
        for link in links:
            effect = link.pop("effect")
            effect_operation = link.pop("effect_operation", None)
            projector = (
                self.registry.projector_for_action(effect_operation)
                if effect_operation is not None
                else None
            )
            jobs.append(
                RequestJobResult(
                    **link,
                    effect=PublicTransactionResult.model_validate(
                        self.public_result(auth, effect, projector, operation=effect_operation)
                    )
                    if effect is not None
                    else None,
                )
            )
        status = "completed"
        if any(j.status in {"queued", "running"} for j in jobs):
            status = "pending"
        elif any(j.status == "failed" for j in jobs):
            status = "failed"
        elif any(j.status == "needs_context" for j in jobs):
            status = "needs_context"
        elif any(j.effect is None for j in jobs):
            status = "unresolved"
        return RequestResult(
            session_id=auth.session_id,
            request_id=request_id,
            operation=meta["operation"],
            executor=response.executor,
            status=status,
            response=PublicTransactionResult.model_validate(
                self.public_result(
                    auth,
                    response,
                    self.registry.projector_for_action(meta["operation"]),
                    operation=meta["operation"],
                )
            ),
            jobs=tuple(jobs),
        )

    def public_result(self, auth, result, event_projector=None, *, operation=None):
        from career_lab.api.public_materials import material_result

        readable = "read" in auth.capabilities
        visible = {canonical(x.ref) for x in self.store.view(auth).objects} if readable else set()
        events = []
        for event in result.events:
            if not readable or auth.actor_id not in event.visible_to:
                continue
            if auth.allowed_objects is not None and any(
                canonical(ref) not in visible for ref in event.refs
            ):
                continue
            if event_projector:
                projected = event_projector(event, auth)
                if projected is None:
                    continue
                projected = PublicEvent.model_validate(projected.model_dump(mode="json"))
                if (projected.id, projected.seq, projected.transaction_id) != (
                    event.id,
                    event.seq,
                    event.transaction_id,
                ):
                    raise ProtocolError("event_projection_identity_mismatch")
            else:
                # Default output contains no unfiltered scenario payload.
                # The scenario installs a scoped projector.
                projected = PublicEvent.model_validate(
                    event.model_dump(mode="json", exclude={"visible_to", "data"}) | {"data": {}}
                )
            events.append(projected)
        public = PublicTransactionResult(
            transaction_id=result.transaction_id,
            boundary=result.boundary,
            executor=result.executor,
            state=PublicState.model_validate(public_state(result.state)),
            objects=tuple(x for x in result.objects if canonical(x) in visible),
            events=tuple(events),
            result=material_result(operation, result.result) if readable else {},
            replayed=result.replayed,
        )
        return public.model_dump(mode="json")

    def run_job(self, name, payload, *, claim=None):
        from career_lab.jobs.worker import WorkerClaim

        if not isinstance(claim, WorkerClaim):
            raise ProtocolError("worker_claim_required", status=409)
        envelope = JobEnvelope.model_validate(payload)
        handler = self.registry.job_handlers.get(name)
        if handler is None:
            raise ProtocolError("module_unavailable", status=503)
        if envelope.operation != name:
            raise ProtocolError("job_kind_invalid")
        from career_lab.jobs.repository import JobRepository
        import time

        leased = JobRepository(self.store.db).get(envelope.job_id)
        if (
            claim.job_id != envelope.job_id
            or leased["kind"] != name
            or leased["payload"] != payload
            or leased["status"] != "running"
            or leased["lease_until"] <= time.time()
            or (leased["lease_token"], leased["worker_id"], leased["attempt"])
            != (claim.lease_token, claim.worker_id, claim.attempt)
        ):
            raise ProtocolError("worker_lease_lost", status=409)
        auth = self.store.guard_job(envelope.context, envelope.capability, check_context=False)
        prior = self.store.replay(auth, envelope.command, envelope.capability)
        if prior is not None:
            return self.public_result(
                auth,
                prior,
                self.registry.projector_for_action(envelope.command.operation),
                operation=envelope.command.operation,
            )
        self.store.guard_job(envelope.context, envelope.capability, command=envelope.command)
        derived_subject = self.store.fixed_feedback_subject(envelope.command)
        view = self.store.job_view(
            auth,
            envelope.context,
            command=envelope.command,
            worker_claim=claim,
            capability=envelope.capability,
        )
        plan = (
            handler.callback(self.store, view, envelope, auth)
            if isinstance(handler, StoreJobHandler)
            else handler(view, envelope, auth)
        )
        # External calls can repeat on transient failure; deterministic failures stop.
        self.store.guard_job(envelope.context, envelope.capability, command=envelope.command)
        result = self.store.execute(
            auth,
            envelope.command,
            lambda *_: plan,
            capability=envelope.capability,
            worker_fence=claim,
            derived_subject=derived_subject,
            job_context=envelope.context,
        )
        return self.public_result(
            auth,
            result,
            self.registry.projector_for_action(envelope.command.operation),
            operation=envelope.command.operation,
        )


def make_step_result(
    transaction: TransactionResult,
    observation: Observation,
    step: ObservedStep,
    consumption: ActualConsumption,
    *,
    origin_request_id=None,
    model_attempts=(),
):
    point = VersionPoint(
        **transaction.state.model_dump(
            include={"business_seq", "workspace_revision", "storage_revision"}
        )
    )
    if observation.as_of != point or observation.actor != transaction.executor:
        raise ProtocolError("step_observation_mismatch", status=409)
    if step.request_id != transaction.boundary.request_id:
        raise ProtocolError("step_request_mismatch", status=409)
    origin = origin_request_id or transaction.boundary.request_id
    return StepResult(
        request_id=origin,
        effect_request_id=transaction.boundary.request_id
        if origin != transaction.boundary.request_id
        else None,
        status="success",
        executor=transaction.executor,
        observation=observation,
        step=step,
        boundary=transaction.boundary,
        replayed=transaction.replayed,
        model_attempts=model_attempts,
        actual_consumption=consumption,
    )
