"""Pure W02 state planning. Persistence, idempotent commits and HTTP belong to W01.

ScenarioSnapshot and PlannedTransition are module-internal implementation values,
not replacement wire schemas. Never install this module as an alternate database.
"""
from copy import deepcopy
from dataclasses import dataclass, field, replace

from career_lab.contracts.v2.core import AuthContext, Command, ObjectRef, ProtocolError, VersionPoint, digest
from career_lab.contracts.v2.requests import ActionInput, ApprovalInput
from career_lab.contracts.v2.world import AssistantConfig, BusinessRequest, WorldStateV2
from .policy import effective_config, evaluate_request, validate_config


@dataclass(frozen=True)
class ScenarioSnapshot:
    world: WorldStateV2
    config: AssistantConfig
    source_versions: dict[str, int]
    indexed_versions: dict[str, int]
    material_activation: dict[str, int]
    requests: tuple[BusinessRequest, ...] = ()
    decisions: tuple = ()
    request_targets: dict[str, AssistantConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedTransition:
    snapshot: ScenarioSnapshot
    events: tuple[dict, ...]
    transaction_id: str
    first_seq: int
    last_seq: int
    result: object = None


class ScenarioEngine:
    def __init__(self, package):
        self.package = package

    def initial(self, session_id):
        return ScenarioSnapshot(
            WorldStateV2(session_id=session_id, business_seq=0, workspace_revision=0,
                         storage_revision=0, cycle_id="initial", resources=dict(self.package.bundle.initial_resources)),
            self.package.baseline(session_id), dict(self.package.rules["initial_material_versions"]),
            dict(self.package.rules["initial_material_versions"]),
            {f"{mid}:{version}":0 for mid,version in self.package.rules["initial_material_versions"].items()})

    def authorize(self, auth, snapshot, operation, capability="act"):
        if not isinstance(auth, AuthContext) or auth.session_id != snapshot.world.session_id:
            raise ProtocolError("session_forbidden", status=403)
        if capability not in auth.capabilities or (auth.allowed_actions is not None and operation not in auth.allowed_actions):
            raise ProtocolError("action_forbidden", status=403)
        if auth.expires_at is not None:
            from datetime import datetime, timezone
            if auth.expires_at <= datetime.now(timezone.utc):
                raise ProtocolError("credential_expired", status=403)
        if auth.actor_id not in {"learner"} | {role.id for role in self.package.bundle.role_specs}:
            raise ProtocolError("unknown_role", status=403)
        # AuthContext is constructed by W01's credential resolver, never a user payload.

    def catalog(self, snapshot, auth):
        """Read-only actor catalog; never returns world-private material bodies."""
        self.authorize(auth, snapshot, "list_materials", "read")
        visible = self.package.visible_materials(snapshot.source_versions, auth.actor_id,
            snapshot.world.business_seq, snapshot.world.session_id)
        return tuple(meta for meta, _ in visible if auth.allowed_objects is None or meta.id in auth.allowed_objects)

    def read(self, snapshot, ref, auth):
        """Current authorized material read; no event or policy mutation."""
        self.authorize(auth, snapshot, "read_material", "read")
        if ref.session_id != snapshot.world.session_id or ref.kind != "material":
            raise ProtocolError("material_unavailable", status=404)
        if auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects:
            raise ProtocolError("object_forbidden", status=403)
        if snapshot.source_versions.get(ref.object_id) != ref.version:
            raise ProtocolError("material_unavailable", status=404)
        result = self.package.project(ref.object_id, ref.version, auth.actor_id,
            snapshot.world.business_seq, snapshot.world.session_id)
        if not result:
            raise ProtocolError("material_unavailable", status=404)
        return tuple(f.model_copy(update={"ref": f.ref.model_copy(update={
            "observed_at_seq": snapshot.world.business_seq,
            "valid_from_seq": snapshot.material_activation.get(f"{ref.object_id}:{ref.version}", 0)
        })}) for f in result)

    def plan(self, snapshot, command, auth, evidence_check=None):
        capability = "approve" if command.operation == "resolve_approval" else "act"
        self.authorize(auth, snapshot, command.operation, capability)
        # These commands affect session-wide state (including automatic events).
        # A finite object grant never implies permission to mutate the whole session.
        if command.operation != "read_material" and auth.allowed_objects is not None:
            raise ProtocolError("object_forbidden", status=403)
        if command.expected_version != snapshot.world.business_seq or command.expected_workspace_revision != snapshot.world.workspace_revision:
            raise ProtocolError("version_conflict", status=409)
        if snapshot.world.status != "active" and command.operation != "resume":
            raise ProtocolError("session_" + snapshot.world.status, status=409)
        state = deepcopy(snapshot)
        txid = digest([snapshot.world.session_id, command.request_id, command.model_dump(mode="json"), auth.executor.model_dump(mode="json")])
        events, result = [], None
        def emit(kind, payload, recipients):
            nonlocal state
            seq = state.world.business_seq + 1
            events.append({"session_id": state.world.session_id, "transaction_id": txid, "seq": seq, "event_type": kind,
                           "payload": payload, "visible_to": list(recipients), "executor": auth.executor.model_dump(mode="json")})
            state = replace(state, world=state.world.model_copy(update={"business_seq": seq}))
        if command.operation == "resolve_approval":
            if auth.actor_id != "supervisor" or auth.executor.kind != "system":
                raise ProtocolError("approval_authority_required", status=403)
            args = ApprovalInput.model_validate(command.payload)
            ref = args.request
            if ref.session_id != state.world.session_id or ref.kind != "business_request":
                raise ProtocolError("request_unavailable", status=404)
            if auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects:
                raise ProtocolError("object_forbidden", status=403)
            req = next((x for x in state.requests if x.id == ref.object_id), None)
            if req is None:
                raise ProtocolError("request_unavailable", status=404)
            if req.version != args.expected_request_revision or ref.version != req.version:
                raise ProtocolError("request_revision_conflict", status=409)
            decision = evaluate_request(self.package, req, state, evidence_check or (lambda ref: False))
            emit("business_decided", {"decision_id": decision.id, "request_id": req.id,
                 "status": decision.status, "reason_code": decision.reason_code, "granted": decision.granted},
                 ("learner", "supervisor", "tech_lead", "business_lead"))
            point = VersionPoint(business_seq=state.world.business_seq,workspace_revision=state.world.workspace_revision,storage_revision=state.world.storage_revision+1)
            decision = decision.model_copy(update={"as_of": point})
            state = replace(state,
                world=state.world.model_copy(update={"resources": {**state.world.resources, **decision.granted}}),
                requests=tuple(x.model_copy(update={"status": decision.status, "version": x.version + 1}) if x.id==req.id else x for x in state.requests),
                decisions=(*state.decisions, decision))
            result = decision
        else:
            args = ActionInput.model_validate(command.payload)
            if args.tool != command.operation:
                raise ProtocolError("operation_payload_mismatch")
            if args.tool == "apply_config":
                if args.config is None:
                    raise ProtocolError("config_required")
                validate_config(self.package, args.config, state.world.session_id)
                if args.config.id != state.config.id:
                    raise ProtocolError("config_identity_mismatch")
                if args.config.config_version != state.world.config_version + 1 or args.config.version != state.config.version + 1:
                    raise ProtocolError("config_revision_conflict", status=409)
                if auth.allowed_objects is not None and args.config.id not in auth.allowed_objects:
                    raise ProtocolError("object_forbidden", status=403)
                state = replace(state, config=args.config.model_copy(deep=True),
                    world=state.world.model_copy(update={"config_version": args.config.config_version}))
                emit("config_applied", {"config_id": args.config.id, "config_version": args.config.config_version}, ("learner",))
                if "initial_plan_applied" not in state.world.applied_milestones:
                    before = dict(state.source_versions)
                    versions = {**before, **self.package.rules["initial_plan_material_updates"]}
                    state = replace(state, source_versions=versions,
                        material_activation={**state.material_activation, **{f"{mid}:{version}":state.world.business_seq+1 for mid,version in self.package.rules["initial_plan_material_updates"].items()}},
                        world=state.world.model_copy(update={"applied_milestones": (*state.world.applied_milestones,"initial_plan_applied")}))
                    emit("initial_plan_applied", {"trigger": "first_explicit_apply_config",
                         "before_versions": before, "after_versions": versions},
                         ("learner","supervisor","tech_lead","business_lead"))
                result = effective_config(self.package, state.config, state.world.resources)
            elif args.tool == "refresh_index":
                before=dict(state.indexed_versions)
                state=replace(state,indexed_versions=dict(state.source_versions))
                emit("index_refreshed", {"before_versions":before,"after_versions":dict(state.indexed_versions)}, ("learner","tech_lead"))
            elif args.tool == "request_business":
                if not args.reason.strip():
                    raise ProtocolError("request_reason_missing")
                if any(ref.session_id != state.world.session_id for ref in args.evidence_refs):
                    raise ProtocolError("evidence_session_mismatch", status=403)
                for ref in args.evidence_refs:
                    if auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects:
                        raise ProtocolError("object_forbidden", status=403)
                    if ref.observed_at_seq > state.world.business_seq:
                        raise ProtocolError("future_evidence")
                rid=digest(["w02-request",state.world.session_id,command.request_id])
                if any(r.id==rid for r in state.requests):
                    raise ProtocolError("request_id_reused",status=409)
                req=BusinessRequest(id=rid,session_id=state.world.session_id,version=1,
                    requested=args.terms,reason=args.reason,evidence_refs=args.evidence_refs,
                    as_of=VersionPoint(business_seq=state.world.business_seq,workspace_revision=state.world.workspace_revision,storage_revision=state.world.storage_revision),
                    executor=auth.executor)
                basis = args.config if args.config is not None else state.config
                validate_config(self.package, basis, state.world.session_id)
                if basis.id != state.config.id:
                    raise ProtocolError("config_identity_mismatch")
                proposed = basis.model_dump(mode="json") != state.config.model_dump(mode="json")
                if proposed and (basis.version != state.config.version + 1 or basis.config_version != state.config.config_version + 1):
                    raise ProtocolError("proposed_config_revision_conflict", status=409)
                # Pin the exact proposal when requesting. It remains unapplied;
                # later edits to active config do not change this request's basis.
                state=replace(state,requests=(*state.requests,req),
                    request_targets={**state.request_targets, rid:basis.model_copy(deep=True)})
                emit("business_requested", {"request_id":rid,"requested":args.terms,"reason":args.reason,
                     "basis_kind":"proposed_config" if proposed else "current_config", "basis_hash":digest(basis)}, ("learner","supervisor"))
                result=req
            elif args.tool == "read_material":
                if args.material is None:
                    raise ProtocolError("material_unavailable",status=404)
                ref=args.material
                result=self.read(state,ref,auth)
                emit("material_read", {"material_id":ref.object_id,"version":ref.version}, (auth.actor_id,))
            elif args.tool in ("pause","resume"):
                if args.tool=="resume" and state.world.status!="paused": raise ProtocolError("invalid_resume")
                state=replace(state,world=state.world.model_copy(update={"status":"paused" if args.tool=="pause" else "active"}))
                emit(args.tool,{},(auth.actor_id,))
            else:
                raise ProtocolError("capability_not_installed",status=503)
        state=replace(state,world=state.world.model_copy(update={"storage_revision":snapshot.world.storage_revision+1}))
        return PlannedTransition(state,tuple(events),txid,snapshot.world.business_seq+1,state.world.business_seq,result)

    def public_event(self, event, snapshot, auth):
        """Only this projection may leave the trusted transaction planner."""
        self.authorize(auth, snapshot, "read_events", "read")
        if event.get("session_id") != snapshot.world.session_id:
            raise ProtocolError("event_session_mismatch", status=403)
        if event["seq"] > snapshot.world.business_seq:
            raise ProtocolError("event_unavailable", status=404)
        if auth.actor_id not in event["visible_to"]:
            return None
        projected = deepcopy(event)
        payload = projected["payload"]
        objects = None if auth.allowed_objects is None else set(auth.allowed_objects)
        if objects is not None:
            subject = {"material_read":"material_id", "config_applied":"config_id"}.get(event["event_type"])
            if subject:
                if payload.get(subject) not in objects:
                    return None
            elif event["event_type"] not in {"index_refreshed", "initial_plan_applied"}:
                # Session-level requests, decisions and lifecycle events have no
                # independently defined object-scope projection in this draft.
                return None
        for key in ("before_versions", "after_versions"):
            if key in payload:
                allowed = {m.id for m, _ in self.package.visible_materials(
                    payload[key], auth.actor_id, event["seq"], snapshot.world.session_id)}
                if objects is not None:
                    allowed &= objects
                payload[key] = {k:v for k,v in payload[key].items() if k in allowed}
        if objects is not None and "before_versions" in payload:
            # Do not reveal that an unrelated object changed via an otherwise
            # unchanged/empty version vector or transaction timing.
            if payload["before_versions"] == payload.get("after_versions", {}):
                return None
            projected["payload"] = {key:payload[key] for key in ("before_versions", "after_versions")}
        return projected
