"""Pure reference planning shared by transactions and immutable snapshot validation."""

from collections.abc import Iterable, Mapping, Sequence, Set

from pydantic import ValidationError

from career_lab.contracts.v2 import (
    EvidenceRefV2,
    LegacyProvenance,
    ObjectRef,
    ProtocolError,
    StoredObject,
    canonical,
)


def reference_values(value: Mapping[str, object]) -> Iterable[object]:
    if {
        "source_schema",
        "source_session_id",
        "original_id",
        "original_kind",
        "raw",
        "original_hash",
    } <= value.keys():
        try:
            LegacyProvenance.model_validate(value)
        except ValidationError:
            pass
        else:
            return [item for key, item in value.items() if key != "raw"]
    return value.values()


def references(value: object) -> tuple[ObjectRef, ...]:
    result: list[ObjectRef] = []
    if isinstance(value, dict):
        if {"session_id", "kind", "object_id", "version"} <= value.keys():
            result.append(
                ObjectRef.model_validate(
                    {key: item for key, item in value.items() if key in ObjectRef.model_fields}
                )
            )
        else:
            for item in reference_values(value):
                result.extend(references(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(references(item))
    return tuple({canonical(ref): ref for ref in result}.values())


def validate_graph(records: Sequence[StoredObject], external_keys: Set[str] = frozenset()) -> None:
    nodes = {canonical(record.ref): record for record in records}
    done: set[str] = set()
    active: set[str] = set()
    if len(nodes) != len(records):
        raise ProtocolError("object_reference_duplicate")

    def visit(key: str) -> None:
        if key in active:
            raise ProtocolError("object_dependency_cycle")
        if key in done:
            return
        active.add(key)
        for dep in nodes[key].dependencies:
            target = canonical(dep)
            if target in external_keys:
                continue
            if target not in nodes:
                raise ProtocolError("object_reference_missing")
            visit(target)
        active.remove(key)
        done.add(key)

    for key in nodes:
        visit(key)


def validate_reference_times(value: object, business_seq: int) -> None:
    if isinstance(value, dict):
        if "observed_at_seq" in value and value["observed_at_seq"] > business_seq:
            raise ProtocolError("future_evidence")
        if (
            isinstance(value.get("as_of"), dict)
            and value["as_of"].get("business_seq", 0) > business_seq
        ):
            raise ProtocolError("future_evidence")
        for item in reference_values(value):
            validate_reference_times(item, business_seq)
    elif isinstance(value, list):
        for item in value:
            validate_reference_times(item, business_seq)


def full_references(value: object) -> list[ObjectRef | EvidenceRefV2]:
    result: list[ObjectRef | EvidenceRefV2] = []
    if isinstance(value, dict):
        if {"session_id", "kind", "object_id", "version"} <= value.keys():
            model = EvidenceRefV2 if "observed_at_seq" in value else ObjectRef
            result.append(
                model.model_validate(
                    {key: item for key, item in value.items() if key in model.model_fields}
                )
            )
        else:
            for item in reference_values(value):
                result.extend(full_references(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(full_references(item))
    return result
