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


def test_english_brief_uses_one_company_name(tmp_path):
    report = BUILDER.build(tmp_path / "candidate")
    installed = json.loads(
        (BUILDER.ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text()
    )
    for lang, identity in report["packages"].items():
        package = Path(identity["root"])
        brief = (package / "materials/brief-v1.md").read_text()
        source = (
            BUILDER.ROOT / installed["main"][lang]["root"] / "materials/brief-v1.md"
        ).read_text()
        materials = json.loads((package / "materials.json").read_text())
        fragments = next(m for m in materials if m["id"] == "brief")["fragments"]
        assert all(
            brief[f["ref"]["span_start"] : f["ref"]["span_end"]] == f["text"] for f in fragments
        )
        if lang == "en":
            assert "Xingqiao" not in brief and "Xingqiao Digital" in source
            assert brief.startswith(
                source.replace("Xingqiao Digital", "Starbridge Digital").replace(
                    "developer-day", "person-day"
                )
            )
        else:
            assert brief.startswith(source)


def test_english_candidate_says_person_days(tmp_path):
    report = BUILDER.build(tmp_path / "candidate")
    package = Path(report["packages"]["en"]["root"])
    assert BUILDER.untouched_terms(package, "en") == []
    materials = json.loads((package / "materials.json").read_text())
    for name, object_id in [
        ("brief-v1.md", "brief"),
        ("approvals-v1.md", "approvals"),
        ("technical-v1.md", "technical"),
    ]:
        text = (package / "materials" / name).read_text()
        assert "person-day" in text
        fragments = next(m for m in materials if m["id"] == object_id)["fragments"]
        assert all(
            text[f["ref"]["span_start"] : f["ref"]["span_end"]] == f["text"] for f in fragments
        )
    assert "3 person-days" in (package / "materials/brief-v1.md").read_text()
    facts = {f["id"]: f for f in json.loads((package / "facts.json").read_text())}
    assert facts["dev_days"]["unit"] == "person-days"
    assert facts["dev_days"]["value"] == 3
    roles = json.dumps(json.loads((package / "roles.json").read_text()))
    assert "Approve capacity, person-days and deadlines" in roles
    module = BUILDER.ScenarioModule(package)
    assert module.package.bundle.role_specs[0].responsibilities[1] == (
        "Approve capacity, person-days and deadlines"
    )
    zh = Path(report["packages"]["zh"]["root"])
    assert "人日" in (zh / "materials/brief-v1.md").read_text()
