"""Internal routing metadata, never new fields on the frozen ToolSchema."""

from dataclasses import dataclass
from copy import deepcopy
from career_lab.contracts import v2 as C
from career_lab.api.modules import ExtensionRegistry


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    ids: tuple[str, ...] = ()


ROUTES = {
    "observation": Route("GET", "/observation"),
    "tools": Route("GET", "/tools"),
    "objects.read": Route("GET", "/objects/{kind}/{object_id}/{version}"),
    "requests.read": Route("GET", "/requests/{request_id}", ("request_id",)),
    "work_items.list": Route("GET", "/work-items"),
    "work_items.create": Route("POST", "/work-items"),
    "work_items.update": Route("PATCH", "/work-items/{item_id}", ("item_id",)),
    "work_items.batch": Route("POST", "/work-items/batch"),
    "work_products.list": Route("GET", "/work-products"),
    "work_products.create": Route("POST", "/work-products"),
    "work_products.versions.list": Route(
        "GET", "/work-products/{product_id}/versions", ("product_id",)
    ),
    "work_products.versions.create": Route(
        "POST", "/work-products/{product_id}/versions", ("product_id",)
    ),
    "work_products.adopt": Route("POST", "/work-products/{product_id}/adoption", ("product_id",)),
    "work_products.shares.create": Route(
        "POST", "/work-products/{product_id}/shares", ("product_id",)
    ),
    "work_products.shares.change": Route(
        "POST", "/work-products/{product_id}/shares/{share_id}", ("product_id", "share_id")
    ),
    "work_products.shares.list": Route(
        "GET", "/work-products/{product_id}/shares", ("product_id",)
    ),
    "workspace_imports": Route("POST", "/workspace-imports"),
    "workspace_imports.list": Route("GET", "/workspace-imports"),
    "workspace_imports.read": Route("GET", "/workspace-imports/{import_id}", ("import_id",)),
    "materials.list": Route("GET", "/materials"),
    "tests.list": Route("GET", "/tests"),
    "tests.create": Route("POST", "/tests"),
    "actions": Route("POST", "/actions"),
    "turns.create": Route("POST", "/turns"),
    "reviews.create": Route("POST", "/reviews"),
    "reviews.read": Route("GET", "/reviews/{review_id}", ("review_id",)),
    "feedback.create": Route("POST", "/feedback"),
    "feedback.records.read": Route("GET", "/feedback-records/{feedback_id}", ("feedback_id",)),
    "feedback.responses.create": Route(
        "POST", "/feedback/{feedback_id}/responses", ("feedback_id",)
    ),
    "feedback.responses.list": Route("GET", "/feedback/{feedback_id}/responses", ("feedback_id",)),
    "feedback.responses.read": Route("GET", "/feedback-responses/{response_id}", ("response_id",)),
    "submissions.create": Route("POST", "/submissions"),
    "submissions.list": Route("GET", "/submissions"),
    "revision_cycles": Route("POST", "/revision-cycles"),
    # Engineer work an Agent may do. The reads take ticket_id / review_id as query filters.
    # engineer.tickets.create and engineer.submissions.sign are the person's own and have
    # no route here, so they are never tools.
    "engineer.tickets.read": Route("GET", "/engineer/tickets"),
    "engineer.reproduce": Route(
        "POST", "/engineer/tickets/{ticket_id}/reproductions", ("ticket_id",)
    ),
    "engineer.trial": Route("POST", "/engineer/tickets/{ticket_id}/trials", ("ticket_id",)),
    "engineer.submissions.draft": Route(
        "POST", "/engineer/tickets/{ticket_id}/drafts", ("ticket_id",)
    ),
    "engineer.reviews.read": Route("GET", "/engineer/reviews"),
}
# What each engineer tool expects, carried as its input schema's description (the
# ToolSchema itself stays frozen).
ENGINEER_TOOL_NOTES = {
    "engineer.tickets.read": (
        "Lists engineer tickets; with ticket_id, one ticket's detail: baseline_config, "
        "editable_fields (the only settings a trial or draft may change, and their allowed "
        "values), public probes, trials, drafts and reviews."
    ),
    "engineer.reproduce": (
        "Reruns the ticket's recorded target tests on its baseline configuration; "
        "it changes no setting."
    ),
    "engineer.trial": (
        "Tries a candidate: payload.changes is {field: new value}, fields taken from the "
        "ticket detail's editable_fields; unlisted fields keep the baseline."
    ),
    "engineer.submissions.draft": (
        "Drafts a fix: changes is {field: new value}, fields from the ticket detail's "
        "editable_fields; only the person signs it, on the RoleCraft web page."
    ),
    "engineer.reviews.read": (
        "Reads the reviews run after the person signs a draft; only the person signs, on the "
        "RoleCraft web page. Pass review_id for the full report."
    ),
}
# The engineer writes run inline with the rule-based retrieval and queue no job.
ENGINEER_SYNC_OPERATIONS = frozenset(
    {"engineer.reproduce", "engineer.trial", "engineer.submissions.draft"}
)
# Fixed synchronous workspace/lifecycle operations. Asynchronous/model-backed entries
# cannot be activated by MCP while the common atomic delegate-job limit is absent.
SYNC_OPERATIONS = frozenset(
    {
        k
        for k, v in ROUTES.items()
        if k.startswith(("work_items.", "work_products.", "workspace_imports"))
    }
    | {"feedback.responses.create", "submissions.create", "revision_cycles"}
)
NEVER_ENABLE = frozenset({"turns.create", "feedback.create"})


@dataclass(frozen=True)
class Binding:
    name: str
    operation: str
    capability: str
    model: type
    mutates: bool
    route: Route
    action_field: str | None = None

    def schema(self):
        payload = deepcopy(self.model.model_json_schema())
        defs = payload.pop("$defs", {})
        for key in self.route.ids:
            if key in payload.get("properties", {}):
                payload["properties"][key] = {"type": "string", "minLength": 1}
                payload["required"] = list(dict.fromkeys([*payload.get("required", []), key]))
        if self.operation == "work_products.versions.create":
            payload["properties"]["removed"] = {
                "const": False,
                "type": "boolean",
                "description": "Only normal editing; removal/restoration unavailable until common lifecycle authorization is frozen.",
            }
        if self.action_field:
            payload["properties"][self.action_field] = {"const": self.name, "type": "string"}
        if self.mutates:
            command = deepcopy(C.Command.model_json_schema())
            defs.update(command.pop("$defs", {}))
            command["properties"]["operation"] = {"const": self.name, "type": "string"}
            command["properties"]["payload"] = payload
            content = {"command": command}
            required = ["session_id", "command"]
        else:
            content = {"query": payload}
            required = ["session_id"]
        note = ENGINEER_TOOL_NOTES.get(self.name)
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **({"description": note} if note else {}),
            "type": "object",
            "properties": {"session_id": {"type": "string", "minLength": 1}, **content},
            "required": required,
            "additionalProperties": False,
            "$defs": defs,
        }


def bindings(registry):
    result = {}
    for name, route in ROUTES.items():
        if name == "requests.read":
            result[name] = Binding(name, name, "read", C.RequestResultQuery, False, route)
            continue
        op = registry.operations.get(name)
        if op is None:
            continue
        if op.capability not in {"read", "act", "submit"}:
            continue
        actions = ExtensionRegistry.operation_actions(op) if op.mutates else (op.name,)
        if actions is None:
            continue  # Unknown dynamic action strings are not a routing proof.
        for action in actions:
            if action in result:
                raise C.ProtocolError("tool_registration_ambiguous", status=503)
            result[action] = Binding(
                action, op.name, op.capability, op.request_model, op.mutates, route, op.action_field
            )
    return result
