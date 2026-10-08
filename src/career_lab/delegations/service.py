"""Thin control plane and tool boundary. No SQL, token table or queue."""

from datetime import datetime, timezone, timedelta
from pydantic import ValidationError
from career_lab.contracts import v2 as C
from career_lab.api.modules import V2Response
from .catalog import bindings, SYNC_OPERATIONS, NEVER_ENABLE


def require_learner(auth):
    if (
        auth.actor_id != "learner"
        or auth.executor.kind not in {"human", "external_agent"}
        or "research" in auth.capabilities
    ):
        raise C.ProtocolError("public_actor_required", status=403)


def issue(store, payload, auth, request_id, *, max_ttl_seconds=3600):
    require_learner(auth)
    if auth.executor.kind != "human":
        raise C.ProtocolError("human_delegation_required", status=403)
    now = datetime.now(timezone.utc)
    if not now < payload.expires_at <= now + timedelta(seconds=max_ttl_seconds):
        raise C.ProtocolError("delegation_expiry_invalid")
    # Labels are user-facing names, not executor IDs or routing identifiers.
    if (
        not payload.agent_label.strip()
        or len(payload.agent_label) > 64
        or not payload.agent_label.isprintable()
    ):
        raise C.ProtocolError("agent_label_invalid")
    identifier = C.digest([auth.session_id, auth.credential_id, request_id, "delegation"])
    grant = C.DelegationGrant(
        id=identifier,
        session_id=auth.session_id,
        actor_id="learner",
        executor=C.Executor(
            id="external:" + identifier, kind="external_agent", delegation_id=identifier
        ),
        capabilities=payload.capabilities,
        allowed_actions=payload.allowed_actions,
        allowed_objects=payload.allowed_objects,
        create_under_tasks=payload.create_under_tasks,
        expires_at=payload.expires_at,
    )
    token = store.issue_delegation(auth, grant)
    # Issuance intentionally returns the secret only to the authorized human.
    # Never expose this control-plane operation as an Agent/MCP tool.
    return V2Response(result={"delegation": grant.model_dump(mode="json"), "token": token})


def revoke(store, payload, auth, request_id):
    require_learner(auth)
    if auth.executor.kind != "human":
        raise C.ProtocolError("human_delegation_required", status=403)
    store.revoke_delegation(auth, payload.delegation_id)
    return V2Response(result={"delegation_id": payload.delegation_id, "revoked": True})


class ToolService:
    def __init__(self, gateway, *, synchronous=SYNC_OPERATIONS, unavailable=None):
        self.gateway = gateway
        self.synchronous = frozenset(synchronous)
        self.unavailable = dict(unavailable or {})

    def catalogue(self, auth, state):
        require_learner(auth)
        if "read" not in auth.capabilities:
            raise C.ProtocolError("capability_forbidden", status=403)
        output = []
        for name, b in sorted(bindings(self.gateway.registry).items()):
            code = None
            if b.capability not in auth.capabilities:
                code = "capability_forbidden"
            elif (
                name != "requests.read"
                and auth.allowed_actions is not None
                and name not in auth.allowed_actions
            ):
                code = "action_forbidden"
            elif b.operation == "work_products.adopt" and auth.executor.kind != "human":
                code = "human_adoption_required"
            elif b.operation in NEVER_ENABLE:
                code = "private_worker_unavailable"
            elif b.mutates and b.operation not in self.synchronous:
                code = "atomic_job_limit_unavailable"
            elif b.operation in self.unavailable:
                code = self.unavailable[b.operation]
            elif (
                b.mutates
                and state.status != "active"
                and b.operation != "feedback.responses.create"
                and not (b.operation == "revision_cycles" and state.status == "submitted")
            ):
                code = "session_" + state.status
            elif b.operation == "revision_cycles" and state.status != "submitted":
                code = "session_not_submitted"
            schema = b.schema()
            output.append(
                C.ToolSchema(
                    name=name,
                    capability=b.capability,
                    parameters=schema,
                    parameters_hash=C.digest(schema),
                    available=code is None,
                    unavailable_code=code,
                )
            )
        return tuple(output)

    def call(self, session_id, token, name, arguments):
        auth = self.gateway.store.authenticate(session_id, token)
        require_learner(auth)
        if not isinstance(arguments, dict) or arguments.get("session_id") != session_id:
            raise C.ProtocolError("session_route_mismatch", status=404)
        if name in {"work_products.remove", "work_products.restore"}:
            raise C.ProtocolError("lifecycle_permission_unavailable", status=503)
        b = bindings(self.gateway.registry).get(name)
        if b is None:
            raise C.ProtocolError("tool_unknown", status=404)
        view = self.gateway.store.view(auth)
        schema = next(t for t in self.catalogue(auth, view.state) if t.name == name)
        if not schema.available:
            raise C.ProtocolError(
                schema.unavailable_code,
                status=403
                if schema.unavailable_code
                in {"capability_forbidden", "action_forbidden", "human_adoption_required"}
                else 503,
            )
        expected = {"session_id", "command"} if b.mutates else {"session_id", "query"}
        if set(arguments) - expected:
            raise C.ProtocolError("tool_arguments_invalid")
        if b.mutates:
            command = C.Command.model_validate(arguments.get("command"))
            if command.operation != name:
                raise C.ProtocolError("operation_route_mismatch", status=403)
            payload = b.model.model_validate(command.payload)
            if b.operation == "work_products.versions.create":
                heads = [
                    r
                    for r in view.objects
                    if r.ref.kind == "product" and r.ref.object_id == payload.product_id
                ]
                if not heads:
                    raise C.ProtocolError("object_not_found", status=404)
                current = max(heads, key=lambda r: r.ref.version)
                if payload.removed or current.content.get("removed_at") is not None:
                    raise C.ProtocolError("lifecycle_permission_unavailable", status=503)
                if (
                    payload.expected_head != current.ref.version
                    or command.expected_version != view.state.business_seq
                    or command.expected_workspace_revision != view.state.workspace_revision
                ):
                    raise C.ProtocolError("version_conflict", status=409)
            route = {key: getattr(payload, key) for key in b.route.ids}
            if any(not isinstance(v, str) or not v for v in route.values()):
                raise C.ProtocolError("route_object_required")
            return self.gateway.dispatch(auth, b.operation, command.model_dump(mode="json"), route)
        query = b.model.model_validate(arguments.get("query", {}))
        for key in b.route.ids:
            if not getattr(query, key, None):
                raise C.ProtocolError("route_object_required")
        return self.gateway.dispatch(auth, b.operation, query.model_dump(mode="json"))
