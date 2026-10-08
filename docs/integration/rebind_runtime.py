"""Reproduce the W02 runtime against the frozen common manifest.

The owned W02 generator builds a separate complete package. This adapter refuses
any content change, then installs only its generated runtime and outer manifest.
Run with the repository virtualenv from its root; no hashes are substituted.
"""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from career_lab.scenarios.v2.seed import build_seed
from career_lab.scenarios.v2.module import ScenarioModule


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("scenarios/pm_pilot/v2"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--with-w05", action="store_true")
    parser.add_argument(
        "--tooling-baseline", help="Full Git commit for an authorized rebind-tool-only migration"
    )
    args = parser.parse_args()
    old = args.root
    overlay = json.loads((old / "runtime/source-files.json").read_text())
    from career_lab.scenarios.v2.rebind import verified_owned_input

    actual, tooling_update = verified_owned_input(
        Path.cwd(),
        overlay["owned_code"],
        json.loads((old / "locale.json").read_text())["locale"],
        args.tooling_baseline,
    )
    foundation = Path("docs/contracts/expansion-v3/manifest.json")
    bundle_data = json.loads((old / "manifest.json").read_text())
    paths = ["manifest.json", *[f["path"] for f in bundle_data["files"]]]
    before = {name: sha(old / name) for name in paths}
    locale = json.loads((old / "locale.json").read_text())["locale"]
    calibration_path = old / "research/retrieval-calibration.json"
    calibration = json.loads(calibration_path.read_text()) if calibration_path.exists() else None
    with tempfile.TemporaryDirectory(prefix="rolecraft-w02-rebind-") as tmp:
        generated = Path(tmp) / "scenario"
        cases = json.loads((old / "research/public-case-records.json").read_text())
        build_seed(
            generated,
            cases,
            private_diagnostic=json.loads((old / "research/private-diagnostic.json").read_text())
            if (old / "research/private-diagnostic.json").exists()
            else None,
            locale=locale,
            scenario_id=bundle_data["id"],
            revision=bundle_data["revision"],
            calibration=calibration,
            english_min_score=calibration["selected_threshold"] if calibration else 0.35,
        )
        if args.with_w05:
            from career_lab.contracts import v2 as C
            from career_lab.rubrics.v4.rubric_v2 import policies

            paths = sorted(
                [
                    *Path("src/career_lab/evidence/v2").glob("*.py"),
                    *Path("src/career_lab/rubrics/v4").glob("*.py"),
                    Path("src/career_lab/api/reviews_v2.py"),
                ]
            )
            protocol = {
                "owner": "W05",
                "installed": True,
                "mode": "advisory",
                "semantic_status": "waiting_for_model_connection",
                "formal_scoring_enabled": False,
                "policies": [policy.to_dict() for policy in policies(work_language=locale)],
                "source_files": {p.as_posix(): sha(p) for p in paths},
                "supersedes_placeholder": "rubric-reference.json remains authored immutable history; this frozen evaluation uses the source-backed W05 policies above.",
            }
            target = generated / "runtime/evaluation-protocol.json"
            target.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
            ref = C.FileRef(path="runtime/evaluation-protocol.json", sha256=sha(target))
            evaluation = C.EvaluationBundle(
                id="w05-local-advisory",
                revision="native-r12-" + C.digest(protocol)[:16],
                rubric=ref,
                rules=ref,
                graders=(),
                protocol=ref,
                mode="advisory",
            )
            (generated / "runtime/evaluation.json").write_text(
                evaluation.model_dump_json(indent=2) + "\n"
            )
            manifest = generated / "manifest.json"
            bundle = C.ScenarioBundle.model_validate_json(manifest.read_bytes())
            bundle = bundle.model_copy(
                update={
                    "files": tuple(
                        f.model_copy(update={"sha256": sha(generated / f.path)})
                        for f in bundle.files
                    )
                }
            )
            manifest.write_text(bundle.model_dump_json(indent=2) + "\n")
        after = {
            p.relative_to(generated).as_posix(): sha(p) for p in generated.rglob("*") if p.is_file()
        }
        changed = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
        invalid = [p for p in changed if p != "manifest.json" and not p.startswith("runtime/")]
        if invalid:
            raise SystemExit("Business/source changes require W02 owner: " + ", ".join(invalid))
        # Validate the real generated runtime against this tree before installing.
        ScenarioModule(generated)
        for name in changed:
            (old / name).write_bytes((generated / name).read_bytes())
    module = ScenarioModule(old)
    result = {
        "generator": "career_lab.scenarios.v2.seed.build_seed",
        "owned_source": actual,
        "tooling_update": tooling_update,
        "foundation_contract_sha256": sha(foundation),
        "changed": changed,
        "before": before,
        "after": after,
        "content_unchanged": True,
        "scenario_sha256": module.package.content_hash,
        "evaluation_binding_status": "W05 frozen local advisory, semantic model pending"
        if args.with_w05
        else "W02 placeholder",
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "changed": changed,
                "scenario_sha256": module.package.content_hash,
                "content_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
