"""Real frozen-loader checks for the unpublished L1 content candidate."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "aipm_content_builder", Path(__file__).with_name("build_candidate.py")
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_bilingual_candidate_loads_without_changing_old_packages(tmp_path):
    report = BUILDER.build(tmp_path / "candidate")
    assert report["published"] is False
    assert report["company_approval"] == "pending_user_confirmation"
    assert set(report["packages"]) == {"zh", "en"}
    for lang, identity in report["packages"].items():
        assert identity["old_bytes_unchanged"] and identity["assistant_domains_unchanged"]
        package = Path(identity["root"])
        module = BUILDER.ScenarioModule(package)
        assert module.release.review.status == "not_recorded"
        assert module.release.evaluation_version == "feedback-rubric-v2-final.1"
        guide = json.loads((package / f"aipm/public/guide.{lang}.json").read_text())
        assert tuple(s["id"] for s in guide["steps"]) == BUILDER.STEP_IDS
        assert all(len(s["suggested_questions"]) == 2 for s in guide["steps"])
        assert "brief" not in {m for ids in module.package.bundle.domains.values() for m in ids}
        assert module.package.project("brief", 1, "learner", 0, "proof")


def test_fresh_destination_required(tmp_path):
    with pytest.raises(ValueError, match="fresh output"):
        BUILDER.build(tmp_path)


def test_tampered_candidate_rejected(tmp_path):
    result = BUILDER.build(tmp_path / "candidate")
    package = Path(result["packages"]["en"]["root"])
    (package / "aipm/public/guide.en.json").write_text("{}")
    with pytest.raises(ValueError):
        BUILDER.ScenarioModule(package)
