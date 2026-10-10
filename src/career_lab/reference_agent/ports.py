"""Fixed HTTP routes; recovery always reads Gateway.request_result, never replays effects."""

from collections.abc import Sequence

from pydantic import JsonValue, ValidationError

from career_lab.contracts.v2.core import Command, Executor, ProtocolError, VersionPoint, digest
from career_lab.contracts.v2.data import ActionProposal
from career_lab.contracts.v2.discovery import REQUEST_MODELS, public_models
from career_lab.contracts.v2.requests import ActionInput
from career_lab.contracts.v2.research import RequestResult
from career_lab.contracts.v2.world import Observation, PublicState
from career_lab.delegations import http_transport
from career_lab.delegations.catalog import ROUTES
from career_lab.delegations.credentials import Credentials, redact
from career_lab.delegations.http_client import RemoteFailure, safe_id
from career_lab.delegations.openai_tools import function_name, function_tools
from career_lab.delegations.public_output import project_public_output
from career_lab.reference_agent.request_identity import RequestIdentity

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


def function_declarations(observation: Observation) -> list[dict[str, JsonValue]]:
    tools = []
    models = public_models()
    for tool in observation.tools:
        if not tool.available or tool.name not in OPERATIONS:
            continue
        operation = OPERATIONS[tool.name]
        schema = models[REQUEST_MODELS[operation]].model_json_schema()
        if operation == "actions":
            schema["properties"]["tool"] = {"type": "string", "const": tool.name}
        tools.append(
            tool.model_copy(update={"parameters": schema, "parameters_hash": digest(schema)})
        )
    result = function_tools(tools, api="chat_completions")
    for item in result:
        item["function"]["description"] = (
            "Execute one authorized action payload. The runner binds session, versions and "
            "request identity."
        )
    return result


def canonical_tool(name: str, observation: Observation) -> str | None:
    return next(
        (tool.name for tool in observation.tools if name in {tool.name, function_name(tool.name)}),
        None,
    )


def validate_candidate(action: ActionProposal) -> None:
    operation = OPERATIONS.get(action.tool)
    if operation is None or operation not in REQUEST_MODELS:
        raise ProtocolError("reference_operation_unavailable", status=403)
    payload = public_models()[REQUEST_MODELS[operation]].model_validate(action.arguments)
    if isinstance(payload, ActionInput) and payload.tool != action.tool:
        raise ProtocolError("reference_candidate_invalid")


def public_results(results: Sequence[RequestResult]) -> list[dict[str, JsonValue]]:
    """Use the same public result boundary as the existing HTTP/MCP client."""
    output = []
    for result in results:
        try:
            value = project_public_output(result.model_dump(mode="json"), operation="requests.read")
        except RemoteFailure as error:
            raise ProtocolError(error.code, status=error.status or 503) from None
        output.append(value)
    return output


class HttpEnvironment:
    def __init__(
        self, credentials: Credentials, executor: Executor, identity: RequestIdentity
    ) -> None:
        self.credentials = credentials
        self.executor = executor
        self.expected_at: VersionPoint | None = None
        self.identity = identity

    def request(
        self, method: str, suffix: str, command: Command | None = None, *, timeout: float = 10
    ) -> dict[str, JsonValue]:
        try:
            value = http_transport.request_json(
                self.credentials,
                method,
                suffix,
                body=command.model_dump(mode="json") if command is not None else None,
                timeout=timeout,
            )
            return redact(value, self.credentials.token)
        except RemoteFailure as error:
            code = {
                "response_unconfirmed": "request_result_unresolved",
                "request_failed": "request_rejected",
            }.get(error.code, error.code)
            raise ProtocolError(code, status=error.status or 503) from None

    def state(self, timeout: float = 10) -> PublicState:
        value = PublicState.model_validate(self.request("GET", "", timeout=timeout)["state"])
        if value.session_id != self.credentials.session_id:
            raise ProtocolError("run_session_mismatch", status=409)
        if self.expected_at is not None:
            actual = VersionPoint(
                business_seq=value.business_seq,
                workspace_revision=value.workspace_revision,
                storage_revision=value.storage_revision,
            )
            if actual != self.expected_at:
                raise ProtocolError("reference_context_changed", status=409)
        return value

    def execute(self, command: Command, timeout: float = 10) -> None:
        operation = OPERATIONS.get(command.operation)
        if operation is None:
            raise ProtocolError("reference_operation_unavailable", status=503)
        route = ROUTES[operation]
        self.request(route.method, route.path, command, timeout=timeout)

    def recover(self, command: Command) -> RequestResult:
        transaction_id = self.identity.transaction_for(command, OPERATIONS[command.operation])
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
        if result.response.transaction_id != transaction_id:
            raise ProtocolError("request_result_identity_mismatch", status=409)
        return result
