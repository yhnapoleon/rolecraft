"""No arbitrary HTTP proxy: only the fixed public business routes are callable."""

import time

from pydantic import ValidationError

from career_lab.contracts import v2 as C

from . import http_transport
from .catalog import ROUTES
from .credentials import load_credentials, redact
from .http_transport import RemoteFailure as RemoteFailure
from .http_transport import safe_id as safe_id


class HttpAgentClient:
    def __init__(self, config_path, *, timeout=15.0):
        if not 0 < timeout <= 30:
            raise ValueError("invalid timeout")
        self.config_path = config_path
        self.timeout = timeout

    def _request(
        self, credentials, method, suffix, body=None, query=None, deadline=None, *, operation=None
    ):
        timeout = (
            self.timeout
            if deadline is None
            else min(self.timeout, max(0.001, deadline - time.monotonic()))
        )

        value = http_transport.request_json(
            credentials, method, suffix, body=body, query=query, timeout=timeout
        )
        from .public_output import project_public_output

        return redact(project_public_output(value, operation=operation), credentials.token)

    def observation(self, session_id, query=None, *, credentials=None, deadline=None):
        credentials = credentials or load_credentials(self.config_path)
        if session_id != credentials.session_id:
            raise RemoteFailure("session_route_mismatch", 404)
        value = self._request(
            credentials, "GET", "/observation", query=query or {}, deadline=deadline
        )
        try:
            observation = C.Observation.model_validate(value["result"])
        except (KeyError, ValidationError):
            raise RemoteFailure("observation_contract_invalid") from None
        if observation.session_id != session_id or observation.actor.kind != "external_agent":
            raise RemoteFailure("delegation_required", 403)
        return observation

    def tools(self):
        credentials = load_credentials(self.config_path)
        return self.observation(credentials.session_id).tools

    def call(self, name, arguments, *, deadline=None):
        if not isinstance(arguments, dict):
            raise RemoteFailure("tool_arguments_invalid", 422)
        credentials = load_credentials(self.config_path)
        if arguments.get("session_id") != credentials.session_id:
            raise RemoteFailure("session_route_mismatch", 404)
        observation = self.observation(
            credentials.session_id, credentials=credentials, deadline=deadline
        )
        tool = next((t for t in observation.tools if t.name == name), None)
        if tool is None:
            raise RemoteFailure("tool_unknown", 404)
        if not tool.available:
            raise RemoteFailure(tool.unavailable_code or "tool_unavailable", 503)
        # Slot/action routing is internal. Public ToolSchema is not extended.
        operation = (
            name
            if name in ROUTES
            else {"submit": "submissions.create", "begin_revision": "revision_cycles"}.get(
                name, "actions"
            )
        )
        if operation not in ROUTES:
            raise RemoteFailure("tool_unavailable", 503)
        route = ROUTES[operation]
        if route.method == "GET":
            if set(arguments) - {"session_id", "query"}:
                raise RemoteFailure("tool_arguments_invalid", 422)
            raw_query = arguments.get("query", {})
            if not isinstance(raw_query, dict):
                raise RemoteFailure("tool_arguments_invalid", 422)
            payload = dict(raw_query)
            body = None
        else:
            if set(arguments) - {"session_id", "command"}:
                raise RemoteFailure("tool_arguments_invalid", 422)
            try:
                command = C.Command.model_validate(arguments["command"])
            except (KeyError, ValidationError):
                raise RemoteFailure("tool_arguments_invalid", 422) from None
            if command.operation != name:
                raise RemoteFailure("operation_route_mismatch", 403)
            payload = command.payload
            body = command.model_dump(mode="json")
            if operation == "work_products.versions.create":
                if payload.get("removed") or not self._editable_head(
                    credentials, observation, payload, deadline
                ):
                    raise RemoteFailure("lifecycle_permission_unavailable", 503)
                if (command.expected_version, command.expected_workspace_revision) != (
                    observation.as_of.business_seq,
                    observation.as_of.workspace_revision,
                ):
                    raise RemoteFailure("version_conflict", 409)
        if operation == "objects.read":
            try:
                read = C.ObjectRead.model_validate(payload)
            except ValidationError:
                raise RemoteFailure("tool_arguments_invalid", 422) from None
            if read.ref.session_id != credentials.session_id:
                raise RemoteFailure("session_route_mismatch", 404)
            if read.as_of is not None:
                raise RemoteFailure("object_time_window_unsupported", 422)
            # Exact existing public route. No body write or synthetic read receipt.
            target = (
                "/objects/"
                + safe_id(read.ref.kind)
                + "/"
                + safe_id(read.ref.object_id)
                + "/"
                + str(read.ref.version)
            )
            params = (
                {"config_version": read.ref.config_version}
                if read.ref.config_version is not None
                else None
            )
            return self._request(
                credentials, "GET", target, query=params, deadline=deadline, operation=name
            )
        suffix = route.path
        for key in route.ids:
            if key not in payload:
                raise RemoteFailure("route_object_required", 422)
            suffix = suffix.replace("{" + key + "}", safe_id(payload[key]))
        query = (
            {k: v for k, v in payload.items() if k not in route.ids and v is not None}
            if body is None
            else None
        )
        return self._request(
            credentials, route.method, suffix, body, query, deadline, operation=name
        )

    def _editable_head(self, credentials, observation, payload, deadline=None):
        product_id = payload.get("product_id")
        head = next((p for p in observation.products if p.object_id == product_id), None)
        if head is None or payload.get("expected_head") != head.version:
            return False
        # Read the exact version through the ordinary authorized version list.
        response = self._request(
            credentials,
            "GET",
            "/work-products/" + safe_id(product_id) + "/versions",
            query={"cursor": 0, "limit": 100},
            deadline=deadline,
        )
        try:
            page = response["result"]["result"]
            rows = page["items"]
        except (KeyError, TypeError):
            raise RemoteFailure("workspace_contract_invalid") from None
        current = next((p for p in rows if p.get("version") == head.version), None)
        # Never guess across a truncated history page; require an explicit result endpoint.
        return current is not None and current.get("removed_at") is None

    def wait_request(self, session_id, request_id, *, seconds=5.0, interval=0.1):
        if not 0 <= seconds <= 30 or not 0.02 <= interval <= 1:
            raise ValueError("invalid wait budget")
        end = time.monotonic() + seconds
        last = None
        while True:
            try:
                last = self.call(
                    "requests.read",
                    {"session_id": session_id, "query": {"request_id": request_id}},
                    deadline=end if seconds > 0 else None,
                )
            except RemoteFailure as error:
                if (
                    last is not None
                    and error.code == "response_unconfirmed"
                    and time.monotonic() >= end
                ):
                    return last
                raise
            if last.get("status") not in {"pending", "needs_context"} or time.monotonic() >= end:
                return last
            if last.get("status") == "needs_context":
                return last
            time.sleep(min(interval, max(0, end - time.monotonic())))
