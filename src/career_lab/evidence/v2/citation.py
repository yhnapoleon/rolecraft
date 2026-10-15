"""The exact citation of a saved object version, as the evaluator verifies it."""

from collections.abc import Iterable

from career_lab.contracts.v2 import EvidenceRefV2, StoredObject, VersionPoint

# A person cites a test run or a work version as a whole; materials are cited by passage.
CITED_OBJECT_KINDS = frozenset({"test", "product"})


def object_citation(
    row: StoredObject, points: Iterable[VersionPoint]
) -> tuple[EvidenceRefV2, VersionPoint] | None:
    """The version as observed at the stored point that created it; None outside ``points``."""
    born = next((p for p in points if p.storage_revision == row.created_storage_revision), None)
    if born is None:
        return None
    return EvidenceRefV2(**row.ref.model_dump(), observed_at_seq=born.business_seq), born
