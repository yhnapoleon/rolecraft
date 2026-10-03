import hashlib
import json
from collections import Counter
from pathlib import Path

from career_lab.contracts.evaluation import EvidencePackage, GoldAnnotation
from career_lab.datasets.generate import generate_records
from career_lab.evidence.serializer import serialize_prompt
from career_lab.storage.sessions import canonical


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def audit_records(rows):
    by_id = {r["item_id"]: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate item IDs")
    for grouping in ("template_id", "root_case_id"):
        groups = {}
        for row in rows:
            if row["split"] not in {"train", "dev", "test"}:
                raise ValueError("invalid split")
            group = row[grouping]
            if group in groups and groups[group] != row["split"]:
                raise ValueError(f"{grouping} leaks across split")
            groups[group] = row["split"]
    for row in rows:
        if row.get("parent_id"):
            parent = by_id.get(row["parent_id"])
            if not parent or parent["split"] != row["split"] or parent["root_case_id"] != row["root_case_id"]:
                raise ValueError("parent lineage split mismatch")
        if row.get("source_split") in {"test", "dev"} and row["source_split"] != row["split"]:
            raise ValueError("source split contamination")


def build_release(output: Path, rows=None) -> Path:
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("release directory must be new; immutable versions cannot be overwritten")
    rows = generate_records() if rows is None else rows
    lineage = [r["lineage"] for r in rows]
    audit_records(lineage)
    output.mkdir(parents=True, exist_ok=True)
    for split in ("train", "dev", "test"):
        subset = [r for r in rows if r["lineage"]["split"] == split]
        name = "test.inputs" if split == "test" else split
        write_jsonl(output / f"splits/{name}.jsonl", [r["input"] for r in subset])
        write_jsonl(output / f"gold/{split}.jsonl", [r["gold"] for r in subset])
    write_jsonl(output / "lineage.jsonl", lineage)
    if any("source_span_ids" in r for r in rows):
        write_jsonl(output / "source_annotations.jsonl", [{"item_id": r["input"]["item_id"], "source_span_ids": r["source_span_ids"], "source_spans": r["source_spans"]} for r in rows if "source_span_ids" in r])
    source_names = sorted({r["source"] for r in lineage})
    card = f"# Engineering pilot dataset\n\n{len(rows)} relation items. Sources: {', '.join(source_names)}. Synthetic G0 labels or original public G1 annotations; no new human double annotation or real learner data. Group-isolated splits. Only a pipeline pilot, not the planned 800–1500 item research release. No claim of workplace validity. Public English data is separate and retains source splits; document groups do not imply unseen-hypothesis generalization. ContractNLI original spans are not minimal sufficient sets. Test reserved; routine evaluation uses dev.\n"
    (output / "data_card.md").write_text(card, encoding="utf-8")
    manifest = {"version": "pilot-v1", "files": {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob("*")) if p.is_file()}, "samples": len(rows), "sources": source_names, "confirmatory": False}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report = audit_release(path)
    (output / "audit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def audit_release(manifest: Path, allowed_splits=("train", "dev", "test")):
    manifest = Path(manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    root = manifest.parent.resolve()
    if not set(allowed_splits) <= {"train", "dev", "test"}:
        raise ValueError("invalid audit split")
    for name, expected in data["files"].items():
        if name.startswith(("gold/", "splits/", "proofs/")) and Path(name).name.split(".")[0] not in allowed_splits:
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("release file/hash mismatch")
    lineage = read_jsonl(root / "lineage.jsonl")
    audit_records(lineage)
    expected_ids = {r["item_id"]: r["split"] for r in lineage}
    seen, signatures, labels = set(), {}, Counter()
    for split in allowed_splits:
        name = "test.inputs" if split == "test" else split
        inputs = [EvidencePackage.model_validate(r) for r in read_jsonl(root / f"splits/{name}.jsonl")]
        golds = [GoldAnnotation.model_validate(r) for r in read_jsonl(root / f"gold/{split}.jsonl")]
        if len({g.item_id for g in golds}) != len(golds) or {i.item_id for i in inputs} != {g.item_id for g in golds}:
            raise ValueError("gold/input identity mismatch")
        for item in inputs:
            serialize_prompt(item)
            if item.item_id in seen or expected_ids.get(item.item_id) != split:
                raise ValueError("input identity/lineage mismatch")
            seen.add(item.item_id)
            signature = canonical([item.claim, [e.text for e in item.candidate_evidence]])
            if signature in signatures and signatures[signature] != split:
                raise ValueError("identical model input leaks across split")
            signatures[signature] = split
        labels.update(g.label for g in golds)
    if seen != {iid for iid, split in expected_ids.items() if split in allowed_splits} or len(lineage) != data["samples"]:
        raise ValueError("sample count mismatch")
    return {"valid": True, "samples": len(seen), "audited_splits": list(allowed_splits), "templates": len({r['template_id'] for r in lineage}), "labels": dict(labels),
            "splits": dict(Counter(r['split'] for r in lineage)), "languages": dict(Counter(r['language'] for r in lineage))}
