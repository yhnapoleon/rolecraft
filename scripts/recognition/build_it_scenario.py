"""Build the playable it_ticket_pilot package (design 6.1) and print its catalog entries.

    PYTHONUTF8=1 python -m scripts.recognition.build_it_scenario [--languages zh en]

Same path as the pm_pilot variants, shortened for the demo: build_seed twice (the second
time with the pre-event trial records), borrow pm_pilot's registered c2.1 evaluation files,
re-hash the manifest, then the release rebind installs the final rubric and writes
runtime/release.json. Output: scenarios/it_ticket_pilot/v2/candidates/it-1/it_ticket_pilot
(English under locales/en). Add the printed entries to runs/local/dev/catalog.json and
restart the API and the worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from career_lab.contracts.v2 import FileRef, ScenarioBundle
from career_lab.rubrics.v4.final_rubric import FINAL_RUBRIC_REVISION
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.public_cases import record_public_cases
from career_lab.scenarios.v2.rebind import rebind
from career_lab.scenarios.v2.release import PROTOCOL
from career_lab.scenarios.v2.seed import build_seed

ROOT = Path(__file__).resolve().parents[2]
# The repository stores text as LF (.gitattributes eol=lf) and the manifest pins every
# file's bytes; the release tools call write_text, which writes CRLF on Windows. Force LF so
# the committed package hashes the same on every checkout.
_write_text = Path.write_text


def _write_text_lf(self, data, encoding=None, errors=None, newline=None):
    return _write_text(self, data, encoding=encoding or "utf-8", errors=errors, newline=newline or "\n")


Path.write_text = _write_text_lf
SCENARIO = "it_ticket_pilot"
REVISION = "it-1.0.0"
EVAL_SOURCE = ROOT / "scenarios/pm_pilot/v2/candidates/semantic-rules-v1-2.9.6/pm_pilot"
EVAL_FILES = (
    "evaluation/rubric-v2-candidate-2.json",
    "evaluation/rules-v4-rubric-v2-c2.json",
    "runtime/evaluation.json",
    "runtime/evaluation-protocol.json",
    "runtime/evaluation-rules.json",
    "rubric-reference.json",
)
OUT = ROOT / "scenarios/it_ticket_pilot/v2/candidates/it-1" / SCENARIO


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stage(locale: str, work: Path) -> Path:
    first = work / f"first-{locale}"
    build_seed(first, locale=locale, scenario_id=SCENARIO, revision=REVISION)
    records = record_public_cases(load_package(first))
    staged = work / f"stage-{locale}"
    build_seed(staged, records, locale=locale, scenario_id=SCENARIO, revision=REVISION)
    source = EVAL_SOURCE if locale == "zh" else EVAL_SOURCE / "locales/en"
    for path in EVAL_FILES:
        target = staged / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / path, target)
    bundle = ScenarioBundle.model_validate_json((staged / "manifest.json").read_bytes())
    listed = {ref.path for ref in bundle.files}
    files = tuple(
        ref.model_copy(update={"sha256": sha((staged / ref.path).read_bytes())})
        for ref in bundle.files
    ) + tuple(
        FileRef(path=path, sha256=sha((staged / path).read_bytes()))
        for path in EVAL_FILES
        if path not in listed
    )
    private = tuple(dict.fromkeys((*bundle.private_files, *(p for p in EVAL_FILES if p not in listed))))
    bundle = bundle.model_copy(update={"files": files, "private_files": private})
    # Bytes, not write_text: on Windows text mode would write CRLF, and the release record
    # compares the manifest read back as text (LF) with the hash of the raw bytes.
    (staged / "manifest.json").write_bytes((bundle.model_dump_json(indent=2) + "\n").encode())
    load_package(staged)
    return staged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", nargs="+", default=["zh"], choices=["zh", "en"])
    args = parser.parse_args(argv)
    contract = "expansion-v3-" + sha((ROOT / "docs/contracts/expansion-v3/manifest.json").read_bytes())
    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        for locale in args.languages:
            staged = stage(locale, Path(tmp))
            destination = OUT if locale == "zh" else OUT / "locales/en"
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            receipt = rebind(
                staged,
                destination,
                protocol=PROTOCOL,
                evaluation=FINAL_RUBRIC_REVISION,
                contract_revision=contract,
                scenario_revision=REVISION.replace("1.0.0", "1.0.1"),
                runtime_revision=f"{REVISION}-{locale}",
            )
            digest = sha((destination / "manifest.json").read_bytes())
            assert digest == receipt["target_scenario_hash"], "manifest hash drifted"
            entries.append(
                {
                    "root": str(destination),
                    "work_language": locale,
                    "scenario_hash": digest,
                    "authored_manifest": digest,
                }
            )
            print(locale, "built", destination, receipt["evaluation_version"])
    print(json.dumps(entries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
