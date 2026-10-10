"""Publisher origin binding. Real origins require an injected authoritative reader.

The receipt binds files and lineage; it is not a signature and cannot establish
real-world truth without the separately configured source authority.
"""

import json
from collections.abc import Iterable

from career_lab.contracts.v2.core import ProtocolError, digest, read_file
from career_lab.contracts.v2.data import DatasetRecordV2

PROTOCOL = "w07-source-origin-v1"


def binding(record, snapshot):
    return {
        "protocol": PROTOCOL,
        "record_id": record.record_id,
        "origin": record.bucket,
        "session_id": record.lineage.session_id,
        "lineage_hash": digest(record.lineage),
        "snapshot_digest": snapshot["snapshot_digest"],
        "source_digest": record.provenance.source.source_digest,
        "source_files": [x.model_dump(mode="json") for x in record.provenance.actual_sources],
    }


def verify_sources(record, snapshot, root, authority=None):
    expected = binding(record, snapshot)
    if snapshot["origin"] != record.bucket:
        raise ProtocolError("source_origin_bucket_mismatch")
    if snapshot["session_id"] != record.lineage.session_id:
        raise ProtocolError("source_origin_lineage_mismatch")
    verify_source_bodies(
        record, (read_file(root, source) for source in record.provenance.actual_sources)
    )
    if record.bucket != "fixture":
        # A caller's record, sidecar or review checkbox cannot authenticate itself.
        if authority is None:
            raise ProtocolError("authoritative_source_reader_required")
        if authority(record, snapshot, tuple(record.provenance.actual_sources)) != expected:
            raise ProtocolError("authoritative_source_binding_mismatch")
    return expected


def verify_source_bodies(record: DatasetRecordV2, sources: Iterable[bytes]) -> None:
    """Check source declarations after the caller verifies path and hash bindings."""
    for raw in sources:
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = None
        if isinstance(body, dict):
            declared = body.get("origin")
            if body.get("fixture") is True or declared == "unit-fixture":
                declared = "fixture"
            if (
                declared in {"fixture", "env_run", "public_aux", "business_synth", "human_session"}
                and declared != record.bucket
            ):
                raise ProtocolError("source_file_origin_mismatch")
            session = body.get("session_id", body.get("session"))
            if session is not None and session != record.lineage.session_id:
                raise ProtocolError("source_file_session_mismatch")
