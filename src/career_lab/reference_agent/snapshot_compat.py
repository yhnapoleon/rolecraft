"""Snapshot consumer compatibility for the hash-verified W01 r3 archive.

The public input is still the registered draft. This helper verifies the r3
namespace/prefix shape; it is not a replacement snapshot service or migration.
"""
from career_lab.contracts.v2 import canonical, digest
from .ports import PortError


def snapshot_prefix_digest(port, snapshot):
    legacy = getattr(port, "prefix_digest", None)
    if callable(legacy):
        return legacy(snapshot), True
    if not hasattr(snapshot, "external_references"):
        raise PortError("snapshot_prefix_verifier_unavailable")
    normalized = {
        "state": snapshot.state.model_dump(mode="json"),
        "objects": [x.model_dump(mode="json") for x in snapshot.objects],
        "events": [x.model_dump(mode="json") for x in snapshot.events],
        "external_references": [x.model_dump(mode="json") for x in snapshot.external_references],
    }
    return digest(normalized), False


def restored_cycle(snapshot, restored, legacy):
    key = canonical(["object", "cycle", snapshot.state.cycle_id])
    if key in restored.id_map:
        return restored.id_map[key]
    if legacy:
        return restored.id_map.get(snapshot.state.cycle_id, snapshot.state.cycle_id)
    raise PortError("restore_cycle_mapping_missing")
