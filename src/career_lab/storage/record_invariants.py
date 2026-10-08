"""Mandatory record invariants shared by transaction commit and historical restore."""

from collections import defaultdict
from collections.abc import Sequence

from career_lab.contracts.v2 import ObjectRef, ProtocolError, StoredObject


def _heads(records: Sequence[StoredObject]) -> dict[tuple[str, str], StoredObject]:
    heads: dict[tuple[str, str], StoredObject] = {}
    for record in records:
        key = (record.ref.kind, record.ref.object_id)
        if key not in heads or heads[key].ref.version < record.ref.version:
            heads[key] = record
    return heads


def validate_write_set(
    existing: Sequence[StoredObject],
    incoming: Sequence[StoredObject],
    current_cycle_id: str,
) -> None:
    """Called unconditionally inside the transaction, after planning and before persistence."""
    prior = _heads(existing)
    resulting = _heads((*existing, *incoming))
    for record in incoming:
        kind = record.ref.kind
        previous = prior.get((kind, record.ref.object_id))
        if kind == "product":
            if set(record.visible_to) != {"learner"}:
                raise ProtocolError("product_requires_share", status=403)
            cycle = ObjectRef.model_validate(record.content["cycle"])
            head = resulting.get(("cycle", cycle.object_id))
            if (
                cycle.object_id != current_cycle_id
                or head is None
                or head.content["status"] != "open"
                or cycle != head.ref
            ):
                raise ProtocolError("product_cycle_closed", status=409)
        if kind in {"feedback", "feedback_response"}:
            if previous is not None or record.ref.version != 1:
                raise ProtocolError("feedback_record_immutable", status=409)
            if record.content.get("read_projection") is not None:
                raise ProtocolError("feedback_projection_not_persistable", status=403)
        if kind == "cycle" and previous is not None and previous.content["status"] != "open":
            raise ProtocolError("revision_cycle_closed", status=409)


def validate_history(records: Sequence[StoredObject]) -> None:
    """Restore validates the same rules at each original atomic revision, without executing it."""
    groups: dict[int, list[StoredObject]] = defaultdict(list)
    for record in records:
        groups[record.created_storage_revision].append(record)
    past: list[StoredObject] = []
    for revision in sorted(groups):
        incoming = groups[revision]
        cycles = [
            record for record in _heads((*past, *incoming)).values() if record.ref.kind == "cycle"
        ]
        current = max(
            cycles,
            key=lambda record: (
                record.content["opened_at"]["storage_revision"],
                record.created_storage_revision,
            ),
            default=None,
        )
        validate_write_set(past, incoming, current.ref.object_id if current else "")
        past.extend(incoming)
