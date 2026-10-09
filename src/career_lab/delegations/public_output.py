"""Final protocol surface check for public role replies; do not trust loose DTOs."""

from pydantic import ValidationError
from career_lab.storage.role_memory import RoleReply
from .http_client import RemoteFailure


def validate_public_output(value):
    if isinstance(value, list):
        for item in value:
            validate_public_output(item)
    elif isinstance(value, dict):
        if value.get("kind") == "role_context" and "object_id" in value:
            raise RemoteFailure("public_projection_unavailable", 503)
        if (
            "role_id" in value
            and "session_id" in value
            and any(
                k in value
                for k in ("text", "prompt_messages", "generation_audit", "private_prompt")
            )
        ):
            try:
                RoleReply.model_validate(value)
            except ValidationError:
                raise RemoteFailure("public_projection_unavailable", 503) from None
        for key, item in value.items():
            # Imported user provenance is inert; it is not a runtime RoleReply.
            if key == "legacy" and isinstance(item, dict):
                continue
            validate_public_output(item)


def project_public_output(value, *, operation=None):
    """Strip scenario fact keys only in an authoritative material-read envelope.

    User-authored payloads are never recursively rewritten based on key names.
    Role validation runs first, preserving the existing fail-closed boundary.
    """
    validate_public_output(value)
    from copy import deepcopy
    from career_lab.contracts import v2 as C

    def material(transaction):
        try:
            C.PublicTransactionResult.model_validate(transaction)
            result = transaction["result"]
            if not isinstance(result.get("material"), dict) or not isinstance(
                result.get("fragments"), list
            ):
                raise ValueError("material result missing")
            result["fragments"] = [
                C.DisclosedFragment.model_validate(part).model_dump(
                    mode="json", exclude={"fact_ids"}
                )
                for part in result["fragments"]
            ]
        except (ValidationError, ValueError, KeyError, TypeError):
            raise RemoteFailure("public_projection_unavailable", 503) from None

    if operation == "read_material":
        value = deepcopy(value)
        material(value)
    elif operation == "requests.read":
        try:
            request = C.RequestResult.model_validate(value)
        except ValidationError:
            raise RemoteFailure("request_result_contract_invalid", 503) from None
        if request.operation == "read_material":
            value = deepcopy(value)
            material(value["response"])
    return value
