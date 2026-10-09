"""Fixed HTTP routes; recovery always reads Gateway.request_result, never replays effects."""

import re

import httpx
from pydantic import JsonValue, ValidationError

from career_lab.contracts.v2.core import Command, Executor, ProtocolError
from career_lab.contracts.v2.research import RequestResult
from career_lab.contracts.v2.world import PublicState
from career_lab.delegations.catalog import ROUTES
from career_lab.delegations.credentials import Credentials
from career_lab.delegations.http_client import safe_id

# Only installed, bounded business operations used by fixed reference checklists.
OPERATIONS = {
    "read_material": "actions",
    "apply_config": "actions",
    "refresh_index": "actions",
    "request_business": "actions",
    "tests.create": "tests.create",
    "work_products.create": "work_products.create",
    "reviews.create": "reviews.create",
    "submissions.create": "submissions.create",
    "begin_revision": "revision_cycles",
}


class HttpEnvironment:
    def __init__(self, credentials: Credentials, executor: Executor) -> None:
        self.credentials = credentials
        self.executor = executor
        self.prefix = "/sessions/" + safe_id(credentials.session_id)
        self.client = httpx.Client(
            base_url=credentials.api_url,
            headers={"Authorization": "Bearer " + credentials.token},
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self.client.close()

    def request(
        self, method: str, suffix: str, command: Command | None = None, *, timeout: float = 10
    ) -> dict[str, JsonValue]:
        try:
            response = self.client.request(
                method,
                self.prefix + suffix,
                json=command.model_dump(mode="json") if command is not None else None,
                timeout=timeout,
            )
            value = response.json()
        except (httpx.HTTPError, ValueError):
            raise ProtocolError("request_result_unresolved", status=503) from None
        if response.status_code >= 300:
            code = value.get("code") if isinstance(value, dict) else None
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code):
                code = "request_rejected"
            if self.credentials.token in code:
                code = "request_rejected"
            raise ProtocolError(code, status=response.status_code)
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise ProtocolError("request_result_unresolved", status=503)
        return value

    def state(self, timeout: float = 10) -> PublicState:
        value = PublicState.model_validate(self.request("GET", "", timeout=timeout)["state"])
        if value.session_id != self.credentials.session_id:
            raise ProtocolError("run_session_mismatch", status=409)
        return value

    def execute(self, command: Command, timeout: float = 10) -> None:
        operation = OPERATIONS.get(command.operation)
        if operation is None:
            raise ProtocolError("reference_operation_unavailable", status=503)
        route = ROUTES[operation]
        self.request(route.method, route.path, command, timeout=timeout)

    def recover(self, command: Command) -> RequestResult:
        try:
            result = RequestResult.model_validate(
                self.request("GET", "/requests/" + safe_id(command.request_id))
            )
        except ValidationError:
            raise ProtocolError("request_result_invalid", status=503) from None
        if (result.session_id, result.request_id, result.operation, result.executor) != (
            self.credentials.session_id,
            command.request_id,
            command.operation,
            self.executor,
        ):
            raise ProtocolError("request_result_identity_mismatch", status=409)
        return result
