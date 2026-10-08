"""Reproduce E1 dev evaluation and non-deployable candidate registrations."""

import argparse
import json
from pathlib import Path

from career_lab.evals.runner import RunnerConfig, run_eval
from career_lab.models.training import load_candidate
from career_lab.registry.models import register_candidate, verify_record
from career_lab.scenarios.loader import load_scenario
from career_lab.storage.sessions import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/releases/v1/manifest.json"))
    parser.add_argument("--models", type=Path, default=Path("runs/models/pilot-v1"))
    parser.add_argument("--output", type=Path, default=Path("runs/e1-dev"))
    args = parser.parse_args()
    spec = load_scenario(Path("scenarios/pm_pilot/v1/scenario.yaml"))
    rubric_hash = digest(spec.rubric.model_dump(mode="json"))
    reports, records = {}, []
    for name in ("linear", "encoder", "ensemble"):
        manifest = args.models / f"{name}.json"
        candidate = load_candidate(manifest)
        config = RunnerConfig(
            suite="e1-dev",
            dataset_manifest=str(args.manifest),
            candidate=candidate.revision,
            prompt_version="relation-v1",
            input_mode="oracle",
            decode={},
            seeds=[5002],
            concurrency=1,
            output_dir=str(args.output / "evals"),
            split="dev",
        )
        report = run_eval(config, candidate)
        reports[name] = report.model_dump(mode="json")
        record = register_candidate(manifest, report.manifest_path, rubric_hash=rubric_hash)
        verify_record(record, rubric_hash)
        records.append(record)
    (args.output / "e1-dev.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    (args.output / "registry.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps({name: report["metrics"]["macro_f1"] for name, report in reports.items()}))


if __name__ == "__main__":
    main()
