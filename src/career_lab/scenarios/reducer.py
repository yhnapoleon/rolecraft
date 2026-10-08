from copy import deepcopy

from career_lab.contracts.actions import Action, Event, TransitionResult, WorldState
from career_lab.contracts.scenario import PilotPlan, ScenarioSpec
from career_lab.errors import CodedValueError


class InvalidAction(CodedValueError):
    pass


class VersionConflict(CodedValueError):
    code = "version_conflict"


def initial_state(session_id: str, spec: ScenarioSpec) -> WorldState:
    versions = {m.id: m.version for m in spec.materials if m.available_after_event is None}
    return WorldState(
        session_id=session_id,
        version=0,
        logical_time=0,
        resources={
            k: getattr(spec.constraints, k) for k in ("capacity", "dev_days", "deadline_day")
        },
        configs={},
        material_versions=versions,
        indexed_versions=versions.copy(),
    )


def apply_action(state: WorldState, action: Action, spec: ScenarioSpec) -> TransitionResult:
    if state.version != action.expected_version:
        raise VersionConflict(f"expected {action.expected_version}; current {state.version}")
    actor = action.actor_id
    if actor not in {r.id for r in spec.roles} | {"learner"}:
        raise InvalidAction("unknown actor")
    if state.status != "active" and action.tool != "resume":
        raise InvalidAction(f"session is {state.status}", code=f"session_{state.status}")
    data = deepcopy(state.model_dump())
    args = action.arguments
    tool = action.tool
    effects = None
    rule_id = None
    visibility = (actor,)
    if tool == "read_material":
        if set(args) != {"material_id"}:
            raise InvalidAction("read_material requires material_id")
        material = next(
            (
                m
                for m in spec.materials
                if m.id == args["material_id"] and m.version == state.material_versions.get(m.id)
            ),
            None,
        )
        if material is None or actor not in material.visible_to:
            raise InvalidAction("material unavailable", code="material_unavailable")
    elif tool in {"request_capacity", "request_resources"}:
        if (
            actor != "learner"
            or set(args) != {"reason"}
            or not isinstance(args["reason"], str)
            or not args["reason"].strip()
        ):
            raise InvalidAction("learner request requires a reason", code="reason_required")
        rule = next((r for r in spec.event_rules if r.trigger.request_tool == tool), None)
        if not rule or rule.id in state.applied_rules:
            raise InvalidAction("request unavailable", code="request_unavailable")
        data["pending_requests"] = list(set(state.pending_requests) | {rule.id})
        visibility = ("learner", "supervisor")
    elif tool == "approve_request":
        if set(args) != {"rule_id"}:
            raise InvalidAction("approve_request requires rule_id")
        rule = next((r for r in spec.event_rules if r.id == args["rule_id"]), None)
        if (
            not rule
            or rule.trigger.authorized_role != actor
            or rule.id not in state.pending_requests
        ):
            raise InvalidAction("approval needs authorized role and pending request")
        effects, rule_id, visibility = rule.effects, rule.id, rule.visible_to
        data["pending_requests"] = [x for x in state.pending_requests if x != rule_id]
    elif tool == "update_pilot":
        if actor != "learner" or set(args) != {"plan"}:
            raise InvalidAction("learner update requires plan")
        plan = PilotPlan.model_validate(args["plan"])
        if set(plan.knowledge_domains) - {d.id for d in spec.domains} or set(plan.work_items) - {
            w.id for w in spec.work_items
        }:
            raise InvalidAction("unknown domain or work item", code="unknown_domain_or_work_item")
        data["configs"] = {"pilot": plan.model_dump(mode="json")}
        data["config_version"] += 1
    elif tool == "refresh_index":
        if actor != "learner" or args:
            raise InvalidAction("refresh_index takes no arguments")
        data["indexed_versions"] = data["material_versions"].copy()
    elif tool in {"test_assistant", "save_artifact", "submit_plan", "record_turn"}:
        # Content is stored atomically by the service; only references enter events.
        if (
            set(args) != {"object_id"}
            or not isinstance(args["object_id"], str)
            or not args["object_id"]
        ):
            raise InvalidAction("service operation requires object_id")
        if tool != "record_turn" and actor != "learner":
            raise InvalidAction("learner operation")
        if tool == "submit_plan":
            if not state.configs:
                raise InvalidAction("configure pilot before submission", code="config_required")
            data["status"] = "submitted"
    elif tool in {"pause", "resume"}:
        if actor != "learner" or args or (tool == "resume" and state.status != "paused"):
            raise InvalidAction("invalid pause/resume", code="invalid_pause_resume")
        data["status"] = "paused" if tool == "pause" else "active"
    else:
        raise InvalidAction(f"unsupported tool: {tool}")

    events, snapshots = [], []

    def emit(kind, payload, visible_to):
        before = data["version"]
        data["version"] += 1
        data["logical_time"] += 1
        events.append(
            Event(
                id=f"{action.id}:{data['version']}",
                session_id=state.session_id,
                seq=data["version"],
                event_type=kind,
                actor_id=actor,
                payload=payload,
                before_version=before,
                after_version=data["version"],
                visible_to=visible_to,
            )
        )
        snapshots.append(WorldState.model_validate(deepcopy(data)))

    def apply_effect(effect, rid):
        for key in ("capacity", "dev_days", "deadline_day"):
            value = getattr(effect, key)
            if value is not None:
                data["resources"][key] = value
        for ref in effect.material_versions:
            data["material_versions"][ref.material_id] = ref.version
        data["applied_rules"] = [*data["applied_rules"], rid]

    if effects:
        apply_effect(effects, rule_id)
    if tool not in {"pause", "resume"}:
        data["action_count"] += 1
    emit(tool, dict(args), visibility)
    for rule in spec.event_rules:
        if (
            rule.trigger.kind == "after_action_count"
            and rule.id not in data["applied_rules"]
            and data["action_count"] >= rule.trigger.action_count
            and data["status"] != "submitted"
        ):
            apply_effect(rule.effects, rule.id)
            emit(rule.id, rule.effects.model_dump(mode="json", exclude_none=True), rule.visible_to)
    return TransitionResult(
        state=snapshots[-1], events=tuple(events), replayed=False, snapshots=tuple(snapshots)
    )
