"""Export, predict, seal and register a trained C1 as an encoder return v3 (S6).

    python -m experiments.recognition.relation.register_c1 \
        --train-out runs/local/recognizers/c1-xlmr --out runs/local/c1-return

Runs the remote's reference tool (``docs/data/return-v3/reference/export_hf_return.py``)
in this environment (CPU, torch 2.8.0, transformers 4.57.1, as the specification requires):

1. ``export`` with ``--weights-stage supervised_finetuned``, our ``heads.npz`` and a training
   report (``fit_split=train``);
2. ``predict`` on relation-v3 dev converted to the dataset row shape
   (``{"record_id", "model_input": {"evidence": ...}}``), written into the return;
3. ``seal`` naming relation-v3 (its manifest SHA-256) with label tier G2v;
4. ``registry_cli register --scope external_candidate`` into ``<out>/registry``.

Prints the three environment variables for ``runs/local/dev/env.ps1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPORT = ROOT / "docs/data/return-v3/reference/export_hf_return.py"
XLMR_REVISION = "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"
DATASET = ROOT / "data/releases/relation-v3"


def run(args: list[str]) -> dict:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(
            " ".join(args[:4]) + " failed:\n" + result.stdout[-2000:] + result.stderr[-3000:]
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def dataset_rows(split: str) -> list[dict]:
    rows = []
    for line in (DATASET / "relation.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["split"] != split:
            continue
        mi = r["model_input"]
        evidence = {
            "item_id": r["record_id"],
            "task_type": "relation",
            "criterion": None,
            "claim": mi["claim"],
            "subjects": [],
            "purpose": mi["purpose"],
            "as_of": {"schema_version": 2, **mi["as_of"]},
            "applicability": "applicable",
            "candidate_evidence": [
                {
                    "id": c["id"],
                    "text": c["text"],
                    "ref": {
                        "schema_version": 2,
                        "session_id": "relation-v3",
                        "kind": "material",
                        "object_id": c["id"],
                        "version": 1,
                        "observed_at_seq": c["observed_at_seq"],
                        "valid_from_seq": c["valid_from_seq"],
                        "valid_until_seq": c["valid_until_seq"],
                    },
                }
                for c in mi["candidate_evidence"]
            ],
            "rule_context": mi["rule_context"],
            "rule_bound": None,
            "completeness": "complete",
        }
        model_input = {"evidence": evidence, "schema_version": 2, "task_type": "relation"}
        rows.append(
            {
                "record_id": r["record_id"],
                "schema_version": 2,
                "task_type": "relation",
                "input_hash": hashlib.sha256(
                    json.dumps(
                        model_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "model_input": model_input,
            }
        )
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-out", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    train_out, out = Path(args.train_out).resolve(), Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    c1 = json.loads((train_out / "c1.json").read_text(encoding="utf-8"))
    metrics = json.loads((train_out / "metrics.json").read_text(encoding="utf-8"))
    report = {
        "fit_split": "train",
        "training_kind": f"supervised_pair_ce_freeze_bottom_{c1.get('freeze_layers', 8)}",
        "source_revision": XLMR_REVISION,
        "notes": "relation-v3 (DeepSeek G2v); dev-joint early stopping; see metrics.json",
        "dev_joint": metrics["dev"]["all"]["joint"],
    }
    (out / "training-report.json").write_text(json.dumps(report), encoding="utf-8")
    target = out / "return"
    exported = run(
        [
            sys.executable,
            "-I",
            str(EXPORT),
            "export",
            "--encoder-dir",
            str(train_out / "encoder"),
            "--variant",
            "pair_aggregate",
            "--source-revision",
            XLMR_REVISION,
            "--weights-stage",
            "supervised_finetuned",
            "--heads",
            str(train_out / "heads.npz"),
            "--training-report",
            str(out / "training-report.json"),
            "--max-tokens",
            str(c1.get("max_tokens", 256)),
            "--evidence-threshold",
            "0.5",
            "--out",
            str(target),
        ]
    )
    print("export", json.dumps(exported)[:400])
    inputs = out / "dev.inputs.jsonl"
    with inputs.open("w", encoding="utf-8", newline="\n") as handle:
        for row in dataset_rows("dev"):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (target / "training-notes.md").write_text(
        "# C1 relation encoder\n\nXLM-R base, pair_aggregate, mean pooling, trained on relation-v3 "
        "train (DeepSeek-generated claims, label tier G2v), early stopping on dev joint.\n",
        encoding="utf-8",
    )
    predicted = run(
        [
            sys.executable,
            "-I",
            str(EXPORT),
            "predict",
            "--root",
            str(target),
            "--inputs",
            str(inputs),
            "--out",
            str(target / "predictions.dev.jsonl"),
        ]
    )
    print("predict", json.dumps({k: predicted[k] for k in ("rows", "statuses", "model_revision")}))
    manifest_sha = hashlib.sha256((DATASET / "manifest.json").read_bytes()).hexdigest()
    sealed = run(
        [
            sys.executable,
            "-I",
            str(EXPORT),
            "seal",
            "--root",
            str(target),
            "--dataset-id",
            "rolecraft-relation-v3",
            "--dataset-manifest-sha256",
            manifest_sha,
            "--label-tier",
            "G2v",
        ]
    )
    print("seal", json.dumps(sealed)[:300])
    registry = out / "registry"
    registered = run(
        [
            sys.executable,
            "-m",
            "career_lab.models.v3.registry_cli",
            "register",
            "--registry",
            str(registry),
            "--bundle-root",
            str(target),
            "--bundle-path",
            sealed["bundle_path"],
            "--bundle-hash",
            sealed["bundle_hash"],
            "--scope",
            "external_candidate",
        ]
    )
    ref = json.dumps(registered["registration"], separators=(",", ":"))
    print("\n# runs/local/dev/env.ps1")
    print(f"$env:CAREER_LAB_MODEL_REGISTRY = '{registry}'")
    print(f"$env:CAREER_LAB_MODEL_REGISTRATION = '{ref}'")
    print(f"$env:CAREER_LAB_MODEL_JOURNAL = '{out / 'journal'}'")
    print(f"$env:CAREER_LAB_RELATION_ENCODER = '{train_out}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
