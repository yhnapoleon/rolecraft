import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from career_lab.contracts.evaluation import EvalConfig, EvidencePackage, GoldAnnotation, JudgeDecision, RunReport
from career_lab.datasets.release import audit_release, read_jsonl, write_jsonl
from career_lab.evidence.serializer import serialize_prompt
from career_lab.evals.graders import grade_decision
from career_lab.evals.metrics import group_bootstrap, summarize
from career_lab.storage.sessions import canonical, digest


class RunnerConfig(EvalConfig):
    output_dir: str = "runs/evals"
    split: Literal["dev", "test"] = "dev"
    replicate_id: str = "0"
    confirmatory: bool = False


class ConstantCandidate:
    revision = "constant-supported-v1"
    def judge(self, item):
        return JudgeDecision(task_type=item.task_type, label="SUPPORTED" if item.task_type == "relation" else "MET",
                             evidence_ids=[e.id for e in item.candidate_evidence], reason_code="CONSTANT_BASELINE", explanation="Constant smoke candidate", model_revision=self.revision)


class FailingCandidate:
    revision = "infrastructure-failure-v1"
    def judge(self, item):
        raise RuntimeError("simulated transport failure")


def run_eval(config: RunnerConfig, candidate=None) -> RunReport:
    if config.split == "test" and not config.confirmatory:
        raise ValueError("test evaluation requires explicit confirmatory freeze")
    if candidate is None:
        candidate = {"constant-supported-v1": ConstantCandidate, "infrastructure-failure-v1": FailingCandidate}[config.candidate]()
    if candidate.revision != config.candidate:
        raise ValueError("candidate revision mismatch")
    path = Path(config.dataset_manifest)
    audit_release(path, allowed_splits=(config.split,))
    root = path.parent
    manifest_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = {"config": config.model_dump(mode="json", exclude={"output_dir"}), "dataset_hash": manifest_hash, "grader": "independent-v2"}
    run_id = digest(identity)[:24]
    output = Path(config.output_dir) / run_id
    output.mkdir(parents=True, exist_ok=True)
    (output / "trials").mkdir(exist_ok=True)
    (output / "manifest.json").write_text(canonical(identity), encoding="utf-8")
    name = "test.inputs" if config.split == "test" else config.split
    items = [EvidencePackage.model_validate(x) for x in read_jsonl(root / f"splits/{name}.jsonl")]
    golds = {g.item_id: g for g in (GoldAnnotation.model_validate(x) for x in read_jsonl(root / f"gold/{config.split}.jsonl"))}
    lineage = {r["item_id"]: r for r in read_jsonl(root / "lineage.jsonl")}

    def trial(pair):
        item, seed = pair
        if config.input_mode == "retrieved":
            from career_lab.assistant.retrieval import retrieve
            from career_lab.evidence.serializer import seal_input
            hits = retrieve(item.claim, [{"id": e.id, "text": e.text} for e in item.candidate_evidence], limit=4)
            selected = {h["id"] for h in hits}
            evidence = tuple(e for e in item.candidate_evidence if e.id in selected)
            item = seal_input(item.model_copy(update={"candidate_evidence": evidence, "completeness": "complete" if len(evidence) == len(item.candidate_evidence) else "missing", "context": None}))
        serialize_prompt(item)
        key = f"{item.item_id}:{seed}"
        target = output / "trials" / (digest(key) + ".json")
        if target.exists():
            cached = json.loads(target.read_text(encoding="utf-8"))
            if cached["input_hash"] != item.input_hash:
                raise ValueError("cached input mismatch")
            return cached
        start = time.monotonic()
        predicted, error, saved_decision = None, None, None
        try:
            raw = candidate.judge(item)
        except Exception as exc:
            error = type(exc).__name__
            graded = {"item_id": item.item_id, "schema_valid": False, "label_correct": False, "evidence_score": 0,
                      "joint_correct": False, "error_class": "infrastructure_error"}
        else:
            graded = grade_decision(raw, golds[item.item_id], item).model_dump(mode="json")
            try:
                parsed = JudgeDecision.model_validate_json(raw) if isinstance(raw, str) else JudgeDecision.model_validate(raw)
                predicted = None if parsed.abstained else parsed.label
                saved_decision = parsed.model_dump(mode="json")
            except (ValueError, TypeError):
                pass
        row = graded | {"trial_key": key, "seed": seed, "input_hash": item.input_hash, "gold_label": golds[item.item_id].label,
                       "predicted_label": predicted, "group": lineage[item.item_id]["template_id"], "language": lineage[item.item_id]["language"],
                       "latency_seconds": time.monotonic()-start, "exception_class": error, "decision": saved_decision}
        temp = target.with_suffix(".tmp")
        temp.write_text(canonical(row), encoding="utf-8")
        temp.replace(target)
        return row

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        rows = list(pool.map(trial, [(item, seed) for item in items for seed in config.seeds]))
    metrics = summarize(rows)
    metrics["p95_seconds"] = sorted(r["latency_seconds"] for r in rows)[min(len(rows)-1, int(.95*len(rows)))] if rows else None
    slices = {g: summarize([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})}
    write_jsonl(output / "predictions.jsonl", rows)
    write_jsonl(output / "errors.jsonl", [r for r in rows if r["error_class"]])
    (output / "metrics.json").write_text(canonical({"overall": metrics, "slices": slices, "accuracy_ci": group_bootstrap(rows)}), encoding="utf-8")
    (output / "report.md").write_text(f"# Eval {run_id}\n\nCandidate: {candidate.revision}; split: {config.split}; dataset: {manifest_hash}\n\n```json\n{json.dumps(metrics, indent=2)}\n```\n\nInfrastructure errors remain in end-to-end denominators. Evidence quality and label quality are separate. Synthetic pilot and few groups do not establish workplace reliability.\n", encoding="utf-8")
    return RunReport(run_id=run_id, manifest_path=str(output / "manifest.json"), metrics=metrics, slices=slices, paired_diff_path=None, errors_path=str(output / "errors.jsonl"))
