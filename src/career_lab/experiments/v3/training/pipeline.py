"""Local development pipeline; held-out confirmation remains separately gated."""

from pathlib import Path
import json
import subprocess
import time

from career_lab.contracts.v2.core import FileRef, SourceIdentity, ProtocolError, digest, read_file
from career_lab.models.v3.core import Prediction, training_examples
from career_lab.models.v3.linear import LinearCandidate, ConstantCandidate
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.legacy import LegacyMLP
from career_lab.models.v3.ensemble import select_alpha, FusionCandidate
from career_lab.models.v3.fusion_bundle import save_fusion_bundle
from career_lab.models.v3.bundle import save_bundle, load_bundle, write_json, json_bytes, sha
from .metrics import grade, summarize, sliced, paired_cluster_delta
from .freeze import freeze_selection
from .selection import SelectionPolicy, choose_dev, rank_key, tune_evidence_threshold
from .languages import bilingual_report


def source_snapshot(workspace, output):
    workspace = Path(workspace).resolve()
    output = Path(output)
    base = subprocess.check_output(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
    ).strip()
    files = {
        p.relative_to(workspace).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((workspace / "src/career_lab").rglob("*.py"))
    }
    hashes = {p: sha(raw.encode()) for p, raw in files.items()}
    snapshot = {
        "base_commit": base,
        "scope": "all runtime career_lab Python source including installed contracts overlay",
        "files": files,
        "file_hashes": hashes,
    }
    write_json(output / "sources/runtime-source.json", snapshot)
    lock = (workspace / "uv.lock").read_bytes()
    (output / "sources/uv.lock").write_bytes(lock)
    return SourceIdentity(
        base_commit=base,
        source_digest=digest(hashes),
        overlay=FileRef(path="sources/runtime-source.json", sha256=sha(json_bytes(snapshot))),
        dependency_locks=(
            FileRef(path="sources/uv.lock", sha256=sha(lock), media_type="text/plain"),
        ),
    )


class EvaluationProgrammingError(ProtocolError):
    def __init__(self, record_id, cause):
        self.record_id = record_id
        self.report = {
            "record_id": record_id,
            "kind": "programming_error",
            "exception_type": type(cause).__name__,
            "message": str(cause)[:2000],
        }
        super().__init__(
            "evaluation_programming_error", f"record {record_id}: {type(cause).__name__}"
        )


def evaluate(candidate, rows):
    output = []
    predictions = []
    latencies = []
    errors = []
    for row in rows:
        started = time.perf_counter()
        raw_prediction = None
        try:
            from dataclasses import asdict

            p = candidate.predict(row.item)
            raw_prediction = json.dumps(asdict(p), ensure_ascii=False, allow_nan=True, default=str)
            if p.model_revision != candidate.revision:
                raise ProtocolError("candidate_model_revision_mismatch")
        except (ProtocolError, OSError, TimeoutError) as exc:
            p = Prediction(
                row.item.task_type,
                row.annotation.input_hash,
                candidate.revision,
                "failed",
                None,
                None,
                reason_code=getattr(exc, "code", type(exc).__name__),
            )
            errors.append(
                {
                    "record_id": row.record_id,
                    "kind": "protocol" if isinstance(exc, ProtocolError) else "infrastructure",
                    "error_code": p.reason_code,
                    "message": str(exc)[:2000],
                }
            )
        except Exception as exc:
            raise EvaluationProgrammingError(row.record_id, exc) from exc
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        result = grade(row, p)
        result["latency_seconds"] = elapsed
        if p.status == "failed":
            result["failure_kind"] = (
                "protocol"
                if p.reason_code in {x["error_code"] for x in errors if x["kind"] == "protocol"}
                else "infrastructure"
            )
        output.append(result)
        if result.get("error_code") and not any(x["record_id"] == row.record_id for x in errors):
            errors.append(
                {
                    "record_id": row.record_id,
                    "kind": result["status"],
                    "error_code": result["error_code"],
                }
            )
        predictions.append(
            {
                "record_id": row.record_id,
                "prediction": p.as_dict() if result["format_valid"] else None,
                "raw_adapter_prediction_json": raw_prediction,
            }
        )
    metrics = summarize(output, rows[0].item.task_type)
    metrics["p95_seconds"] = (
        sorted(latencies)[min(len(latencies) - 1, int(0.95 * len(latencies)))]
        if latencies
        else None
    )
    return {
        "metrics": metrics,
        "slices": sliced(output, rows[0].item.task_type),
        "rows": output,
        "predictions": predictions,
        "errors": errors,
    }


def run_development(
    reader,
    output,
    *,
    workspace,
    task="relation",
    seed=5002,
    epochs=4,
    dimension=8,
    max_tokens=128,
    selection_policy=None,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    policy = (selection_policy or SelectionPolicy()).validate()
    write_json(output / "selection-policy.json", policy.as_dict())
    started = time.perf_counter()
    reports = {}
    bundles = {}
    evaluations = {}
    write_json(
        output / "started.json",
        {
            "mode": "synthetic_pipeline" if reader.fixture else "development_only",
            "formal_E1_E2_complete": False,
        },
    )
    try:
        train = training_examples(reader.load("train", task), task)
        dev = reader.load("dev", task)
        source = source_snapshot(workspace, output)
        release_raw = read_file(reader.root, reader.release_ref)
        split_raw = read_file(reader.root, reader.split_ref)
        (output / "provenance").mkdir()
        (output / "provenance/release.json").write_bytes(release_raw)
        (output / "provenance/split.json").write_bytes(split_raw)
        release_ref = FileRef(path="provenance/release.json", sha256=sha(release_raw))
        split_ref = FileRef(path="provenance/split.json", sha256=sha(split_raw))
        models = {
            "constant": ConstantCandidate(task),
            "linear": LinearCandidate(task, seed),
            "attention_pack": AttentionEncoder(
                task, variant="pack", seed=seed, dimension=dimension, max_tokens=max_tokens
            ),
            "attention_pair": AttentionEncoder(
                task, variant="pair", seed=seed, dimension=dimension, max_tokens=max_tokens
            ),
            "attention_pair_mean_logits": AttentionEncoder(
                task,
                variant="pair",
                aggregation="mean_logits",
                seed=seed,
                dimension=dimension,
                max_tokens=max_tokens,
            ),
        }
        if task == "relation":
            models["legacy_character_mlp"] = LegacyMLP(seed)
        for name, model in models.items():
            if name == "constant":
                reports[name] = {"training_performed": False, "kind": "fixed baseline"}
            else:
                reports[name] = (
                    model.fit(train, epochs=epochs)
                    if isinstance(model, AttentionEncoder)
                    else model.fit(train)
                )
                if name != "legacy_character_mlp":
                    reports[name]["dev_threshold_selection"] = tune_evidence_threshold(
                        model, dev, policy
                    )
                ref = save_bundle(
                    model,
                    output / "models" / name,
                    source_root=output,
                    training_release=release_ref,
                    split_manifest=split_ref,
                    source=source,
                )
                reloaded, bundle = load_bundle(output / "models" / name, ref)
                for row in dev:
                    a, b = model.predict(row.item), reloaded.predict(row.item)
                    if a != b:
                        raise ProtocolError("reload_prediction_drift")
                models[name] = reloaded
                bundles[name] = {
                    "root": "models/" + name,
                    "manifest": ref.model_dump(mode="json"),
                    "model_revision": bundle.model_revision,
                }
            evaluations[name] = evaluate(models[name], dev)
        alpha_report = None
        if task == "relation":
            encoder_names = ("attention_pack", "attention_pair", "attention_pair_mean_logits")
            selected_encoder = max(
                encoder_names,
                key=lambda n: rank_key(evaluations[n]["metrics"], order=encoder_names.index(n)),
            )
            alpha_report = select_alpha(dev, models["linear"], models[selected_encoder], policy)
            alpha_report["encoder_selected_on_dev"] = selected_encoder
            if alpha_report["alpha"] is not None:
                ref = save_fusion_bundle(
                    output / "models/fusion",
                    left_root=output / bundles["linear"]["root"],
                    left_ref=FileRef.model_validate(bundles["linear"]["manifest"]),
                    right_root=output / bundles[selected_encoder]["root"],
                    right_ref=FileRef.model_validate(bundles[selected_encoder]["manifest"]),
                    alpha=alpha_report["alpha"],
                    threshold=alpha_report["evidence_threshold"],
                )
                fused, fb = load_bundle(output / "models/fusion", ref)
                bundles["fusion"] = {
                    "root": "models/fusion",
                    "manifest": ref.model_dump(mode="json"),
                    "model_revision": fb.model_revision,
                }
                evaluations["fusion"] = evaluate(fused, dev)
        names = list(evaluations)
        selection = choose_dev(
            [
                {
                    "id": n,
                    "metrics": evaluations[n]["metrics"],
                    "cost": 2 if n == "fusion" and alpha_report["alpha"] not in (0.0, 1.0) else 1,
                }
                for n in names
            ],
            policy,
        )
        selected = selection["selected"]
        report = {
            "mode": "synthetic_pipeline"
            if reader.fixture
            else "development_only_pending_confirmation",
            "formal_E1_E2_complete": False,
            "selection_split": "dev",
            "selected": selected,
            "task_type": task,
            "selection_status": selection["status"],
            "selection_policy": policy.as_dict(),
            "training": reports,
            "evaluations": evaluations,
            "fusion": alpha_report,
            "bundles": bundles,
            "data_scope": reader.scope_report(),
            "source": source.model_dump(mode="json"),
            "seed": seed,
            "seed_count": 1,
            "elapsed_seconds": time.perf_counter() - started,
            "external_model_calls": 0,
            "test_evaluation": "not_run",
            "pretrained_encoder": "not_run: requires separately locked dependencies and pinned approved local checkpoint",
            "SFT": "not_run",
            "GRPO": "not_run",
            "product_integration": "not_run",
            "paired_vs_linear": {
                n: paired_cluster_delta(
                    evaluations["linear"]["rows"], value["rows"], seed=seed, metric="joint_correct"
                )
                for n, value in evaluations.items()
                if n != "linear"
            },
            "paired_label_vs_linear": {
                n: paired_cluster_delta(
                    evaluations["linear"]["rows"], value["rows"], seed=seed, metric="label_correct"
                )
                for n, value in evaluations.items()
                if n != "linear"
            },
            "language_evaluation": bilingual_report(
                train, dev, evaluations, reports, reader.scope_report(), task
            ),
            "limitations": [
                "synthetic smoke is not E1/E2 or model-quality evidence"
                if reader.fixture
                else "independent test/structure gates remain",
                "single seed; no stable improvement claim",
                "all predictions advisory",
                "no new sealed test content opened",
            ],
        }
        write_json(output / "reports/development.json", report)
        for name, result in evaluations.items():
            base = output / ("E2" if name == "fusion" else "E1") / name
            write_json(
                base / "manifest.json",
                {
                    "status": "synthetic_pipeline" if reader.fixture else "development_only",
                    "formal_complete": False,
                    "release": reader.release_ref.model_dump(mode="json"),
                    "source": source.model_dump(mode="json"),
                    "candidate": name,
                },
            )
            write_json(
                base / "config.json",
                {
                    "seed": seed,
                    "epochs": epochs,
                    "dimension": dimension,
                    "max_tokens": max_tokens,
                    "selection_policy": policy.as_dict(),
                },
            )
            write_json(base / "predictions.json", result["predictions"])
            training_exclusions = [
                dict(e, kind="training_capacity_exclusion")
                for e in reports.get(name, {}).get("excluded_records", [])
            ]
            write_json(base / "errors.json", result["errors"] + training_exclusions)
            write_json(
                base / "metrics.json", {"overall": result["metrics"], "slices": result["slices"]}
            )
        # Check that actual runtime source stayed fixed during the fit/evaluation.
        snapshot = json.loads((output / "sources/runtime-source.json").read_text())
        for name, expected in snapshot["file_hashes"].items():
            if sha((Path(workspace) / name).read_bytes()) != expected:
                raise ProtocolError("source_changed_during_training")
        refs = [
            FileRef(path=p.relative_to(output).as_posix(), sha256=sha(p.read_bytes()))
            for p in sorted(output.rglob("*"))
            if p.is_file()
        ]
        frozen = freeze_selection(
            output,
            "freeze.json",
            files=refs,
            source=source,
            selection={
                "selection_split": "dev",
                "selected": selected,
                "alpha": alpha_report["alpha"] if alpha_report else None,
                "evidence_threshold": alpha_report["evidence_threshold"] if alpha_report else None,
                "selection_policy": policy.as_dict(),
                "seed": seed,
                "epochs": epochs,
                "dimension": dimension,
                "max_tokens": max_tokens,
            },
            split_manifest=split_ref,
            fixture=reader.fixture,
        )
        return {
            "report": "reports/development.json",
            "freeze_id": frozen["id"],
            "freeze_path": str((output / "freeze.json").resolve()),
            "freeze_hash": sha((output / "freeze.json").read_bytes()),
            "selected": selected,
            "mode": report["mode"],
            "formal_E1_E2_complete": False,
        }
    except Exception as exc:
        failure = {
            "error": getattr(exc, "code", type(exc).__name__),
            "record_id": getattr(exc, "record_id", None),
            "details": getattr(exc, "report", None),
            "elapsed_seconds": time.perf_counter() - started,
            "completed_fit_reports": reports,
            "formal_E1_E2_complete": False,
        }
        write_json(output / "failure.json", failure)
        write_json(output / "reports/errors.json", [failure])
        raise
