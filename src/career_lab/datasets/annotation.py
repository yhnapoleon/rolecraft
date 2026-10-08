import csv
import json
import math
from pathlib import Path
from sklearn.metrics import cohen_kappa_score

from career_lab.datasets.release import read_jsonl
from career_lab.storage.sessions import digest


def export_annotation_pack(manifest, output, count=100):
    root = Path(manifest).parent
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    lineage = {r["item_id"]: r for r in read_jsonl(root / "lineage.jsonl")}
    items = read_jsonl(root / "splits/train.jsonl") + read_jsonl(root / "splits/dev.jsonl")
    # Interleave templates, ensuring the first 30 cover all available capabilities.
    groups = {}
    for item in items:
        groups.setdefault(lineage[item["item_id"]]["template_id"], []).append(item)
    selected = []
    while len(selected) < count and any(groups.values()):
        for group in groups.values():
            if group and len(selected) < count:
                selected.append(group.pop(0))
    entries = [
        dict(
            item_id=i["item_id"],
            input_hash=i["input_hash"],
            claim=i["claim"],
            candidate_evidence=json.dumps(i["candidate_evidence"], ensure_ascii=False),
            annotator_id="",
            label="",
            evidence_sets="",
            missing_requirement="",
            notes="",
            minutes="",
        )
        for i in selected
    ]
    for name in ("annotator-a.csv", "annotator-b.csv"):
        with (output / name).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(entries[0]))
            writer.writeheader()
            writer.writerows(entries)
    from career_lab.datasets.release import write_jsonl

    write_jsonl(output / "inputs.jsonl", selected)
    report = dict(
        items=len(selected),
        human_status="pending",
        selection=[lineage[i["item_id"]] for i in selected],
        input_hashes={i["item_id"]: i["input_hash"] for i in selected},
        inputs_hash=digest(selected),
    )
    (output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def import_annotations(pack, first, second):
    pack = Path(pack)
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    inputs = read_jsonl(pack / "inputs.jsonl")
    if digest(inputs) != manifest["inputs_hash"]:
        raise ValueError("annotation input drift")
    by_id = {i["item_id"]: i for i in inputs}

    def read(path):
        with Path(path).open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        seen = set()
        done = {}
        people = set()
        for row in rows:
            iid = row["item_id"]
            if iid in seen or iid not in by_id or row["input_hash"] != by_id[iid]["input_hash"]:
                raise ValueError("annotation identity conflict")
            if (
                row["claim"] != by_id[iid]["claim"]
                or json.loads(row["candidate_evidence"]) != by_id[iid]["candidate_evidence"]
            ):
                raise ValueError("annotation display changed")
            seen.add(iid)
            if not row["label"].strip():
                continue
            if row["label"] not in {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"}:
                raise ValueError("invalid annotation label")
            if not row["annotator_id"].strip():
                raise ValueError("annotator required")
            sets = json.loads(row["evidence_sets"])
            valid = {e["id"] for e in by_id[iid]["candidate_evidence"]}
            if (
                not isinstance(sets, list)
                or not sets
                or any(
                    not isinstance(s, list)
                    or any(e not in valid for e in s)
                    or len(s) != len(set(s))
                    for s in sets
                )
            ):
                raise ValueError("invalid evidence sets")
            if row["label"] != "INSUFFICIENT" and any(not s for s in sets):
                raise ValueError("positive/negative requires evidence")
            if row["label"] == "INSUFFICIENT" and not row["missing_requirement"].strip():
                raise ValueError("missing requirement needed")
            minutes = float(row["minutes"])
            if not math.isfinite(minutes) or minutes <= 0:
                raise ValueError("minutes must be positive")
            row["evidence_sets"] = sorted(sorted(s) for s in sets)
            row["minutes"] = minutes
            done[iid] = row
            people.add(row["annotator_id"])
        if len(people) > 1:
            raise ValueError("one annotator per sheet")
        return done, people

    a, pa = read(first)
    b, pb = read(second)
    if pa & pb:
        raise ValueError("independent annotators required")
    shared = sorted(a.keys() & b.keys())
    la = [a[i]["label"] for i in shared]
    lb = [b[i]["label"] for i in shared]
    kappa = float(cohen_kappa_score(la, lb)) if shared and len(set(la + lb)) > 1 else None
    disagreements = [
        dict(item_id=i, a=a[i], b=b[i])
        for i in shared
        if a[i]["label"] != b[i]["label"]
        or a[i]["evidence_sets"] != b[i]["evidence_sets"]
        or a[i]["missing_requirement"] != b[i]["missing_requirement"]
    ]
    return dict(
        status="ready_for_adjudication" if len(shared) == len(inputs) else "pending",
        paired=len(shared),
        total=len(inputs),
        raw_agreement=sum(x == y for x, y in zip(la, lb)) / len(shared) if shared else None,
        kappa=kappa,
        minutes=sum(r["minutes"] for r in [*a.values(), *b.values()]),
        disagreements=disagreements,
        human_gold_released=False,
    )
