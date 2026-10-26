"""Build fresh, unpublished bilingual AIPM content; never change installed packages."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from career_lab.contracts.v2 import digest
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.release import GENERATED, business_metadata

ROOT = Path(__file__).resolve().parents[4]
CONTENT = Path(__file__).resolve().parents[1]
STEP_IDS = ("business", "stakeholders", "need", "boundary", "solution", "assurance", "decision")
REVISION = "aipm-phase1-draft-1"
EXPERIENCE = "aipm-phase1-v1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def file_ref(root, name):
    return {
        "schema_version": 2,
        "path": name,
        "sha256": sha((root / name).read_bytes()),
        "media_type": "application/json",
    }


def snapshot(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def build(output, content=CONTENT):
    output = output.resolve()
    if output.exists() or output.is_relative_to(ROOT / "scenarios/pm_pilot/v2"):
        raise ValueError("Use a fresh output outside the installed scenario tree")
    installed = json.loads((ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    present = sorted(
        str(p.relative_to(content))
        for folder in ["public", "private"]
        for p in (content / folder).rglob("*.json")
    )
    required = [
        f"public/{name}.{lang}.json"
        for name in ["company", "guide", "patterns", "design", "evaluation"]
        for lang in ["zh", "en"]
    ] + ["private/grading/design.json", "private/grading/evaluation.json"]
    missing = sorted(set(required) - set(present))
    report = {
        "schema_version": 1,
        "experience_revision": EXPERIENCE,
        "content_revision": REVISION,
        "status": "candidate_pending_confirmation",
        "published": False,
        "company_approval": "pending_user_confirmation",
        "missing_content": missing,
        "recognition": "not_validated_for_new_hash",
        "packages": {},
    }
    output.mkdir(parents=True)
    for lang in ["zh", "en"]:
        source = ROOT / installed["main"][lang]["root"]
        before = snapshot(source)
        old = ScenarioModule(source)
        package = output / lang
        package.mkdir()
        manifest = old.package.bundle.model_dump(mode="json")
        for ref in manifest["files"]:
            target = package / ref["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / ref["path"]).read_bytes())
        manifest["revision"] = REVISION
        manifest["lineage"] = [
            *manifest["lineage"],
            f"{old.package.bundle.id}@{old.package.content_hash}",
        ]
        rules = yaml.safe_load((package / "scenario.yaml").read_text())
        rules["revision"] = REVISION
        # Public company context stays outside the assistant's answerable knowledge domains.
        company = json.loads((content / f"public/company.{lang}.json").read_text())
        name = rules["material_files"]["brief"]["1"]
        original_brief = (package / name).read_text()
        company_text = (
            original_brief + "\n\n" + company["title"] + "\n" + company["status_label"] + "\n\n"
        )
        fragments = []
        for sentence in company["sentences"]:
            start = len(company_text)
            company_text += sentence["text"] + "\n\n"
            ref = {
                "schema_version": 2,
                "session_id": manifest["baseline_config"]["session_id"],
                "kind": "material",
                "object_id": "brief",
                "version": 1,
                "span_start": start,
                "span_end": start + len(sentence["text"]),
                "quote": sentence["text"],
                "observed_at_seq": 0,
                "valid_from_seq": 0,
            }
            fragments.append(
                {
                    "schema_version": 2,
                    "ref": ref,
                    "text": sentence["text"],
                    "channel": "material",
                    "disclosure": {"schema_version": 2, "mode": "public"},
                    "fact_ids": [],
                }
            )
        (package / name).write_text(company_text)
        materials = json.loads((package / "materials.json").read_text())
        brief = next(m for m in materials if m["id"] == "brief" and m["version"] == 1)
        brief["fragments"].extend(fragments)
        write(package / "materials.json", materials)
        locale = json.loads((package / "locale.json").read_text())
        next(m for m in locale["materials"] if m["id"] == "brief" and m["version"] == 1)[
            "sha256"
        ] = sha(company_text.encode())
        write(package / "locale.json", locale)
        (package / "scenario.yaml").write_text(
            yaml.safe_dump(rules, allow_unicode=True, sort_keys=True)
        )
        # Original trial snapshots and all original source spans are retained byte-for-byte.
        # The new appendix is a draft in this NEW package, not a historical trial input.
        extra = []
        for member in present:
            if member.startswith("public/") and not member.endswith(f".{lang}.json"):
                continue
            target = package / "aipm" / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((content / member).read_bytes())
            extra.append("aipm/" + member)
        content_manifest = {
            "schema_version": 1,
            "experience_revision": EXPERIENCE,
            "content_revision": REVISION,
            "work_language": lang,
            "company_approval": "pending_user_confirmation",
            "files": {p: sha((package / p).read_bytes()) for p in extra if p.startswith("aipm/")},
            "missing_content": missing,
            "base_scenario_hash": old.package.content_hash,
        }
        write(package / "aipm/manifest.json", content_manifest)
        extra.append("aipm/manifest.json")
        for name in extra:
            # Frozen loader publishes only material-backed raw files. L4 projects guide JSON.
            category = "public_files" if name.startswith("materials/company") else "private_files"
            manifest[category].append(name)
        names = sorted({ref["path"] for ref in manifest["files"]} | set(extra))
        manifest["files"] = [file_ref(package, name) for name in names]
        # New authored content gets a new release identity and no inherited approval.
        business_files = {
            ref["path"]: ref["sha256"] for ref in manifest["files"] if ref["path"] not in GENERATED
        }
        metadata = business_metadata(manifest)
        identity = digest({"files": business_files, "metadata": metadata})
        original = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        release = json.loads((package / "runtime/release.json").read_text())
        release.update(
            revision=REVISION,
            content_identity=identity,
            content_files=business_files,
            content_metadata=metadata,
            original_manifest=original,
            original_release_identity=sha(original.encode()),
            review={"status": "not_recorded", "content_identity": identity},
            code_acceptance="candidate_pending_regression",
        )
        write(package / "runtime/release.json", release)
        write(
            package / "runtime/source-files.json",
            {
                "protocol": "scenario-release-v1",
                "content_identity": identity,
                "evaluation_version": release["evaluation_version"],
            },
        )
        runtime = json.loads((package / "runtime/bundle.json").read_text())
        runtime["revision"] = REVISION
        runtime["source"]["overlay"] = file_ref(package, "runtime/source-files.json")
        write(package / "runtime/bundle.json", runtime)
        manifest["files"] = [file_ref(package, name) for name in names]
        write(package / "manifest.json", manifest)
        loaded = load_package(package)
        module = ScenarioModule(package)
        assert module.registration().bindings == module.bindings
        assert snapshot(source) == before, "Installed source changed during build"
        assert loaded.bundle.domains == old.package.bundle.domains
        report["packages"][lang] = {
            "root": str(package),
            "scenario_hash": loaded.content_hash,
            "content_identity": identity,
            "base_scenario_hash": old.package.content_hash,
            "loader": "passed",
            "scenario_module": "passed",
            "old_bytes_unchanged": True,
            "assistant_domains_unchanged": True,
            "evaluation_version": release["evaluation_version"],
            "evaluation_sha256": sha((package / "runtime/evaluation.json").read_bytes()),
        }
    write(output / "identity.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
