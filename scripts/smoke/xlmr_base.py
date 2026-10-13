"""D7 receiving-end smoke with real XLM-R base weights (143 §3.7 item 1).

The downloaded ``FacebookAI/xlm-roberta-base`` encoder goes through the published v3 path
exactly as a responsible party's return would: ``export_hf_return.py export`` with
``--weights-stage pretrained_untrained_heads`` (heads seeded, never trained), ``seal``,
``registry_cli register --scope synthetic_fixture``. The registration then serves the
normal runtime (HTTP + worker, in process): Chinese and English learner works from the
scenario's own decision examples are reviewed twice, and the per-sentence journal gives
token counts, over-limit abstentions and per-sentence seconds.

This proves loading, sentence splitting, token measurement and honest abstention with the
real tokenizer and weights. It is not training, not a quality result and not evidence of
English quality: the heads are random, so every label is a mechanism sample.

Run with the encoder extra, from the repository root, into a new output directory::

    uv run --locked --extra encoder python -m scripts.smoke.xlmr_base \\
        --model-dir <xlm-roberta-base/<revision>> --revision <40 hex> --out <new dir>
"""

import argparse
import hashlib
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.core import FileRef
from career_lab.jobs.worker import Worker
from career_lab.models.v3.registry import load_registration
from career_lab.models.v3.units import MAX_UNITS
from scripts.regression.published import write_catalog

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "docs/data/return-v3/reference/export_hf_return.py"
DATASET_ID = "rolecraft-xlmr-smoke-synthetic"
# No dataset was used: the heads are untrained. The identity names that fact.
DATASET_SHA = hashlib.sha256(b"rolecraft-xlmr-smoke-no-dataset").hexdigest()
# One quoted fragment per cited material, up to eight fragments, or whole materials.
CITATIONS = ("fragments", "fragments-8", "whole")
# 148's recommendation: keep one feedback job's model time near this many seconds (p95).
JOB_BUDGET_SECONDS = 30.0


def run(command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(" ".join(command[:3]) + " failed:\n" + result.stdout + result.stderr)
    output = json.loads(result.stdout.strip().splitlines()[-1])
    return output | {"seconds": round(time.perf_counter() - started, 3)}


def register(model_dir: Path, revision: str, variant: str, out: Path) -> tuple[Path, FileRef, dict]:
    """Export, seal and register one untrained-heads return; returns registry, ref, timings."""
    python = sys.executable
    target = out / ("return-" + variant)
    exported = run(
        [
            python,
            "-I",
            str(EXPORT),
            "export",
            "--encoder-dir",
            str(model_dir),
            "--weights-stage",
            "pretrained_untrained_heads",
            "--variant",
            variant,
            "--source-revision",
            revision,
            "--max-tokens",
            "512",
            "--out",
            str(target),
        ],
        out,
    )
    sealed = run(
        [
            python,
            "-I",
            str(EXPORT),
            "seal",
            "--root",
            str(target),
            "--dataset-id",
            DATASET_ID,
            "--dataset-manifest-sha256",
            DATASET_SHA,
            "--label-tier",
            "G0",
        ],
        out,
    )
    registry = out / ("registry-" + variant)
    registered = run(
        [
            python,
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
            "synthetic_fixture",
        ],
        ROOT,
    )
    ref = FileRef.model_validate(registered["registration"])
    timings = {
        "export_seconds": exported["seconds"],
        "seal_seconds": sealed["seconds"],
        "register_seconds": registered["seconds"],
        "model_revision": exported["model_revision"],
        "weights_stage": exported["weights_stage"],
    }
    return registry, ref, timings


def rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


def measure_load(registry: Path, ref: FileRef) -> dict[str, Any]:
    before = rss_mb()
    started = time.perf_counter()
    model, entry = load_registration(registry, ref)
    seconds = time.perf_counter() - started
    return {
        "load_seconds": round(seconds, 3),
        "peak_rss_mb_before": before,
        "peak_rss_mb_after": rss_mb(),
        "kind": entry.get("kind"),
        "scope": entry["scope"],
        "weights_stage": entry.get("weights_stage"),
        "max_tokens": getattr(model, "max_tokens", None),
    }


class Session:
    def __init__(self, client: TestClient, app: Any, language: str) -> None:
        self.client, self.app, self.language = client, app, language
        made = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        made.raise_for_status()
        body = made.json()
        self.session_id = body["session_id"]
        self.headers = {"Authorization": "Bearer " + body["token"]}

    def send(self, path: str, key: str, operation: str, payload: dict[str, Any]) -> dict:
        state = self.client.get("/sessions/" + self.session_id, headers=self.headers).json()
        response = self.client.post(
            "/sessions/" + self.session_id + "/" + path,
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": key,
                "operation": operation,
                "payload": payload,
                "expected_version": state["state"]["business_seq"],
                "expected_workspace_revision": state["state"]["workspace_revision"],
            },
        )
        if response.status_code != 200:
            raise RuntimeError(path + " " + operation + ": " + response.text)
        return response.json()

    def material(self, object_id: str) -> dict:
        ref = {
            "schema_version": 2,
            "session_id": self.session_id,
            "kind": "material",
            "object_id": object_id,
            "version": 1,
        }
        read = self.send(
            "actions",
            "read-" + object_id,
            "read_material",
            {"tool": "read_material", "material": ref},
        )
        fragments = [fragment["ref"] for fragment in read["result"]["fragments"]]
        # The whole material: the observed reference without a quoted span.
        whole = {
            key: value
            for key, value in fragments[0].items()
            if key not in {"span_start", "span_end", "quote"}
        }
        return {"whole": whole, "fragments": fragments}

    def review(self, work: dict, key: str) -> tuple[dict, float]:
        made = self.send(
            "reviews",
            key,
            "reviews.create",
            {
                "subjects": [work],
                "scope": [],
                "purpose": "commitment",
                "decision": "defer_with_conditions",
            },
        )
        started = time.perf_counter()
        if not Worker(self.app.state.jobs, self.app.state.handlers).run_once():
            raise RuntimeError("no review job ran")
        seconds = time.perf_counter() - started
        feedback = self.client.get(
            "/sessions/" + self.session_id + "/feedback/" + made["result"]["review"]["object_id"],
            headers=self.headers,
        )
        feedback.raise_for_status()
        report = feedback.json()["result"]["result"]["items"][0]
        (advice,) = [row for row in report["model_advice"] if row["criterion"] == "R2.support"]
        return advice, seconds


def journal_outcomes(journal: Path, seen: set[str]) -> list[dict]:
    """Outcomes recorded since ``seen`` (directory names), in name order."""
    fresh = sorted(path.name for path in journal.iterdir() if path.name not in seen)
    seen.update(fresh)
    return [
        json.loads((journal / name / "outcome.json").read_text())
        for name in fresh
        if (journal / name / "outcome.json").is_file()
    ]


def summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "p50": round(statistics.median(ordered), 3),
        "p95": round(p95, 3),
        "max": round(ordered[-1], 3),
    }


def works(language: str) -> list[dict[str, Any]]:
    """The scenario's decision examples for ``language`` (the work and its cited materials)."""
    index = json.loads((ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    root = ROOT / index["main"][language]["root"]
    examples = json.loads((root / "decision_examples.json").read_text())
    return [example for example in examples if example["evidence"]]


def exercise(registry: Path, ref: FileRef, out: Path, language: str) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    journal = out / ("journal-" + language)
    os.environ.update(
        CAREER_LAB_MODEL_REGISTRY=str(registry),
        CAREER_LAB_MODEL_REGISTRATION=ref.model_dump_json(),
        CAREER_LAB_MODEL_JOURNAL=str(journal),
        CAREER_LAB_SCENARIO_CATALOG=str(write_catalog(out / ("catalog-" + language + ".json"))),
        CAREER_LAB_SCENARIO_ARCHIVE=str(out / ("archive-" + language)),
    )
    app = create_runtime_app("sqlite:///" + str(out / (language + ".db")), provider="local")
    results = []
    seen: set[str] = set()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            for number, example in enumerate(works(language)):
                for citation in CITATIONS:
                    session = Session(client, app, language)
                    refs = []
                    for object_id in example["evidence"]:
                        material = session.material(object_id)
                        refs.extend(
                            [material["whole"]]
                            if citation == "whole"
                            else material["fragments"][: 1 if citation == "fragments" else None]
                        )
                    # "fragments-8": up to eight quoted fragments, as a heavier citer would.
                    refs = refs[:8]
                    made = session.send(
                        "work-products",
                        "work",
                        "work_products.create",
                        {
                            "kind": "text",
                            "purpose": "commitment",
                            "title": "Pilot decision" if language == "en" else "试点决定",
                            "content": example["proposal"],
                            "evidence_refs": refs,
                        },
                    )
                    work = next(r for r in made["objects"] if r["kind"] == "product")
                    first, first_seconds = session.review(work, "review-1")
                    first_outcomes = journal_outcomes(journal, seen)
                    second, second_seconds = session.review(work, "review-2")
                    second_outcomes = journal_outcomes(journal, seen)
                    tokens = [
                        o["input_size"]["tokens"] for o in first_outcomes if "input_size" in o
                    ]
                    over = [
                        unit
                        for unit in first["units"]
                        if unit.get("reason_code") == "unit_exceeds_encoder_limit"
                    ]
                    judged = [
                        o["elapsed_seconds"]
                        for o in first_outcomes
                        if "input_size" in o and o["input_size"]["tokens"] <= 512
                    ]
                    results.append(
                        {
                            "language": language,
                            "example": number,
                            "citation": citation,
                            "candidates": len(refs),
                            "status": first["status"],
                            "error_code": first.get("error_code"),
                            "label": first.get("label"),
                            "counts": first["aggregation"]["counts"],
                            "sentences": len(first["units"]),
                            "unit_statuses": [u["status"] for u in first["units"]],
                            "tokens": summary([float(t) for t in tokens]),
                            "token_values": tokens,
                            "over_limit": len(over),
                            "over_limit_rate": round(len(over) / len(first["units"]), 3)
                            if first["units"]
                            else None,
                            "judged_sentence_seconds": summary(judged),
                            "first_review_seconds": round(first_seconds, 3),
                            "second_review_seconds": round(second_seconds, 3),
                            "second_review_journal_sentences": len(second_outcomes),
                            "second_same_units": [u["unit_hash"] for u in second["units"]]
                            == [u["unit_hash"] for u in first["units"]],
                        }
                    )
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
    return results


def recommend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """MAX_UNITS suggestion from the measured p95 seconds of a judged sentence (advice only)."""
    judged = [
        row["judged_sentence_seconds"]["p95"]
        for row in rows
        if row["judged_sentence_seconds"]["p95"]
    ]
    if not judged:
        return {
            "max_units_now": MAX_UNITS,
            "suggested_max_units": None,
            "basis": "no judged sentence",
        }
    p95 = max(judged)
    suggested = max(1, int(JOB_BUDGET_SECONDS // p95))
    return {
        "max_units_now": MAX_UNITS,
        "worst_p95_sentence_seconds": p95,
        "job_budget_seconds": JOB_BUDGET_SECONDS,
        "suggested_max_units": min(MAX_UNITS, suggested),
        "basis": "budget / worst per-sentence p95 across variants, languages and citation modes",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", default=["pair", "pack"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "model": "FacebookAI/xlm-roberta-base",
        "revision": args.revision,
        "scope": "synthetic_fixture",
        "weights_stage": "pretrained_untrained_heads",
        "claims": "loading, splitting, token measurement and abstention only; heads untrained",
        "platform": sys.platform,
        "variants": {},
    }
    rows: list[dict[str, Any]] = []
    for variant in args.variants:
        registry, ref, timings = register(args.model_dir.resolve(), args.revision, variant, out)
        loaded = measure_load(registry, ref)
        variant_rows = [
            row | {"variant": variant}
            for language in ("zh", "en")
            for row in exercise(registry, ref, out / variant, language)
        ]
        rows.extend(variant_rows)
        report["variants"][variant] = (
            timings | loaded | {"registration": ref.model_dump(mode="json"), "works": variant_rows}
        )
    report["max_units"] = recommend(rows)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(out / "report.json"), "max_units": report["max_units"]}))


if __name__ == "__main__":
    main()
