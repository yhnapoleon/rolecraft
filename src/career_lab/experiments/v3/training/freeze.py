"""Relative-path immutable freeze and explicit campaign validation; no test auto-open."""

from pathlib import Path
from datetime import datetime, timezone
import json

from career_lab.contracts.v2.core import FileRef, SourceIdentity, ProtocolError, digest, read_file
from career_lab.contracts.v2.data import TestCampaign, CampaignCandidate, require_confirmatory
from career_lab.models.v3.bundle import write_json


def freeze_selection(
    root,
    path,
    *,
    files,
    source: SourceIdentity,
    selection,
    split_manifest: FileRef,
    fixture=False,
    candidates=(),
):
    root = Path(root).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ProtocolError("freeze_path_outside_root")
    if selection.get("selection_split") != "dev":
        raise ProtocolError("selection_must_use_dev")
    if not source.dependency_locks or source.overlay is None:
        raise ProtocolError("freeze_source_and_dependencies_required")
    refs = [FileRef.model_validate(r.model_dump(mode="json")) for r in files]
    if len({r.path for r in refs}) != len(refs):
        raise ProtocolError("duplicate_freeze_member")
    protected = {r.path: r.sha256 for r in refs}
    for mandatory in (
        split_manifest,
        *source.dependency_locks,
        *((source.overlay,) if source.overlay else ()),
    ):
        if protected.get(mandatory.path) != mandatory.sha256:
            raise ProtocolError("freeze_identity_file_missing")
    for ref in refs:
        if (
            set(Path(ref.path).parts) & {"inputs", "labels", "gold", "proofs"}
            or Path(ref.path).name == "records.json"
        ):
            raise ProtocolError("raw_dataset_must_not_be_opened_by_freeze", status=403)
        read_file(root, ref)
    if len({c.id for c in candidates}) != len(candidates):
        raise ProtocolError("duplicate_frozen_candidate")
    for candidate in candidates:
        if candidate.source != source:
            raise ProtocolError("frozen_candidate_source_mismatch")
        for ref in (candidate.runtime, candidate.evaluation):
            if protected.get(ref.path) != ref.sha256:
                raise ProtocolError("frozen_candidate_file_missing")
    body = {
        "protocol": "expansion-v3-w08-freeze-v1",
        "files": [r.model_dump(mode="json") for r in refs],
        "source": source.model_dump(mode="json"),
        "selection": selection,
        "split_manifest": split_manifest.model_dump(mode="json"),
        "fixture": fixture,
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    }
    body["id"] = digest(body)
    write_json(target, body)
    return body


def verify_freeze(root, ref: FileRef):
    raw = json.loads(read_file(Path(root), ref))
    if raw.get("id") != digest({k: v for k, v in raw.items() if k != "id"}):
        raise ProtocolError("freeze_record_drift")
    if (
        raw.get("protocol") != "expansion-v3-w08-freeze-v1"
        or raw["selection"].get("selection_split") != "dev"
    ):
        raise ProtocolError("freeze_protocol_invalid")
    for value in raw["files"]:
        member = FileRef.model_validate(value)
        if (
            set(Path(member.path).parts) & {"inputs", "labels", "gold", "proofs"}
            or Path(member.path).name == "records.json"
        ):
            raise ProtocolError("raw_dataset_must_not_be_opened_by_freeze", status=403)
        read_file(Path(root), member)
    return raw


def validate_campaign(
    root, *, freeze_ref, campaign_ref, candidate: CampaignCandidate, split_manifest: FileRef
):
    frozen = verify_freeze(root, freeze_ref)
    if frozen["fixture"]:
        raise ProtocolError("fixture_cannot_authorize_confirmatory")
    campaign = TestCampaign.model_validate_json(read_file(Path(root), campaign_ref))
    require_confirmatory(campaign, candidate, split_manifest)
    if candidate.model_dump(mode="json") not in frozen.get("candidates", []):
        raise ProtocolError("campaign_budget_or_candidate_not_frozen")
    if split_manifest.model_dump(mode="json") != frozen["split_manifest"]:
        raise ProtocolError("campaign_split_mismatch")
    if candidate.source.model_dump(mode="json") != frozen["source"]:
        raise ProtocolError("campaign_source_mismatch")
    pins = {x["path"]: x["sha256"] for x in frozen["files"]}
    for ref in (candidate.runtime, candidate.evaluation):
        if pins.get(ref.path) != ref.sha256:
            raise ProtocolError("campaign_candidate_not_frozen")
        read_file(Path(root), ref)
    return {
        "campaign_id": campaign.id,
        "candidate_id": candidate.id,
        "freeze_id": frozen["id"],
        "test_content_opened": False,
        "scope": "authorization identity checked; test reader remains an integration-owned port",
    }
