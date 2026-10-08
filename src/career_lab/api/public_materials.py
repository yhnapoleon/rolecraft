"""Public material projection; internal fact linkage stays in persisted sources."""

from copy import deepcopy
from career_lab.contracts.v2 import DisclosedFragment, ProtocolError
from pydantic import ValidationError


def public_fragments(fragments):
    try:
        return [
            DisclosedFragment.model_validate(part).model_dump(mode="json", exclude={"fact_ids"})
            for part in fragments
        ]
    except (ValidationError, TypeError) as exc:
        raise ProtocolError("public_material_projection_invalid", status=503) from exc


def material_result(operation, result):
    # Do not recursively rewrite user-authored work or imported provenance.
    if operation != "read_material":
        return result
    projected = deepcopy(result)
    if "fragments" in projected:
        projected["fragments"] = public_fragments(projected["fragments"])
    return projected
