"""Shared pieces of the public-data releases (``public-real-v1``, ``public-synth-v1``).

Relation records keep the relation-v3 shape (``model_input`` in the EvidencePackage form,
``pair_labels`` over every candidate, ``split``), so the C1 / stack evaluation code reads
them unchanged. External documents have no session clock: every unit is observed at
seq 0 and the reference time is seq 1, except versioned sources (site-policy revisions,
Jira field history), where superseded text carries ``valid_until_seq`` like v3's
old-version negatives. Provenance sits next to ``model_input``, never inside it.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "public"
RELEASES = ROOT / "data" / "releases"
PAIR = {"SUPPORTED": "SUPPORTS", "CONTRADICTED": "CONTRADICTS", "INSUFFICIENT": "UNRELATED"}


def unit_id(*parts: object) -> str:
    return "u-" + hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]


def source_of(source_id: str) -> dict:
    path = RAW / source_id / "source.json"
    if not path.exists():
        path = ROOT / "data" / "raw" / source_id / "source.json"
    return json.loads(path.read_text(encoding="utf-8"))


def candidate(uid: str, text: str, *, observed=0, valid_from=0, valid_until=None) -> dict:
    return {
        "id": uid,
        "text": text,
        "observed_at_seq": observed,
        "valid_from_seq": valid_from,
        "valid_until_seq": valid_until,
    }


def relation_record(
    *,
    record_id: str,
    language: str,
    label: str,
    claim: str,
    candidates: list[dict],
    pair_labels: dict[str, str],
    gold_unit_ids: list[str],
    split: str,
    as_of: int = 1,
    **extra,
) -> dict:
    """One relation item in the relation-v3 layout; ``extra`` holds provenance fields."""
    evidence = [u for u in gold_unit_ids if pair_labels.get(u) in ("SUPPORTS", "CONTRADICTS")]
    record = {
        "record_id": record_id,
        "language": language,
        "label": label,
        "evidence_ids": evidence if label != "INSUFFICIENT" else [],
        "gold_unit_ids": gold_unit_ids,
        "pair_labels": pair_labels,
    }
    record.update(extra)
    record["model_input"] = {
        "task_type": "relation",
        "criterion": None,
        "purpose": "commitment",
        "claim": claim,
        "as_of": {"business_seq": as_of, "workspace_revision": as_of, "storage_revision": as_of},
        "applicability": "applicable",
        "rule_context": {
            "evidence_time_context": {
                "policy": "historical-evidence-time-v1",
                "status": "known",
                "reference_seq": as_of,
                "validity_known_ids": [c["id"] for c in candidates],
            }
        },
        "candidate_evidence": candidates,
        "completeness": "complete",
    }
    record["split"] = split
    return record


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_release(out: Path, files: dict[str, list[dict]], manifest: dict, card: str) -> None:
    """JSONL files + manifest.json + data_card.md + SHA256SUMS (UTF-8, ``\\n``)."""
    out.mkdir(parents=True, exist_ok=True)
    listed = []
    for name, rows in files.items():
        write_jsonl(out / name, rows)
        listed.append({"path": name, "sha256": sha256(out / name), "records": len(rows)})
    manifest = {"schema_version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **manifest}
    manifest["files"] = listed
    with (out / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (out / "data_card.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(card.strip() + "\n")
    names = sorted([*files, "manifest.json", "data_card.md"])
    licenses = sorted(p.relative_to(out).as_posix() for p in (out / "LICENSES").glob("*"))
    with (out / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as handle:
        for name in names + licenses:
            handle.write(f"{sha256(out / name)}  {name}\n")


def copy_license(out: Path, source_id: str) -> str:
    """Copy a source's licence text into ``<release>/LICENSES/``; returns the new path."""
    source = source_of(source_id)
    src = ROOT / source["license_file"]
    target = out / "LICENSES" / f"{source_id}-{src.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(src.read_bytes())
    return target.relative_to(out).as_posix()
