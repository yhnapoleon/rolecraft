"""Focused Chinese-slice content and immutable-runtime handoff checks."""

from pathlib import Path
import hashlib, json
import pytest
from career_lab.contracts.v2 import ProtocolError
from career_lab.scenarios.v2.localization import runtime_source_files
from career_lab.scenarios.v2.rebind import rebind
from .conftest import apply
from .test_content_redesign import role_auth

ROOT = Path(__file__).resolve().parents[3]


def test_public_trials_are_a_readable_table_with_complete_traceable_cards(package):
    main = (package.root / "materials/failures-v1.md").read_text()
    details = (package.root / "materials/trial_details-v1.md").read_text()
    assert "| 试验 | 提问 |" in main and main.count("| Q") == 12
    assert "{" not in main and "试用配置与完整回答" in main
    records = json.loads((package.root / "research/public-case-records.json").read_bytes())
    for record in records["records"]:
        assert f"## {record['trial_id']}" in details
        assert record["result"]["answer"] in details
        assert record["result"]["config"]["requested"]["id"] in details
    assert "| 参数 | 请求配置 | 实际配置 |" in details


def test_business_role_owns_its_claim_and_corrects_on_evidence(package):
    role = next(r for r in package.bundle.role_specs if r.id == "business_lead")
    assert any("起初支持BC-01的429" in goal for goal in role.goals)
    assert any("具体字段反证后承认并修正" in goal for goal in role.goals)
    assert any("不否认BC-01原文" in goal and "不因学员忠实引用" in goal for goal in role.goals)
    assert any("没有实际转达或回复记录" in item for item in role.responsibilities)
    public = (package.root / "materials/business_case-v1.md").read_text()
    assert "我想用这个数争取试点" in public and "反证后承认" not in public
    assert "若需要回查，给我" not in (package.root / "materials/demand-v1.md").read_text()
    assert (
        "可带导出批次、行号和字段名与陈敏讨论"
        in (package.root / "materials/demand-v1.md").read_text()
    )


def test_static_zero_is_not_the_runtime_activation_for_role_facts(package, engine):
    state = apply(engine, engine.initial("session")).snapshot
    static = next(f for f in package.facts if f.id == "hotel_limit" and f.version == 2)
    assert static.source.valid_from_seq == 0
    current = engine.role_knowledge(
        state, role_auth("business_lead"), known_versions=state.source_versions
    )
    hotel = next(f for f in current if "hotel_limit" in f.fact_ids)
    assert hotel.ref.version == 2
    assert hotel.ref.valid_from_seq == state.material_activation["policy:2"] > 0
    assert hotel.ref.observed_at_seq == state.world.business_seq
    initial = engine.role_knowledge(state, role_auth("business_lead"))
    assert next(f for f in initial if "hotel_limit" in f.fact_ids).ref.version == 1


def test_chinese_runtime_pins_shared_code_and_isolates_english_only_dependencies(package):
    bound = json.loads((package.root / "runtime/source-files.json").read_bytes())["owned_code"]
    from career_lab.contracts.v2 import RuntimeBundle, digest
    from career_lab.scenarios.v2.module import ScenarioModule

    runtime = RuntimeBundle.model_validate_json((package.root / "runtime/bundle.json").read_bytes())
    assert digest(bound) == runtime.source.source_digest
    assert ScenarioModule(package.root).work_language == "zh"
    current = runtime_source_files(ROOT, "zh")
    assert set(bound) <= set(current)
    assert "src/career_lab/scenarios/v2/module.py" in bound
    assert "src/career_lab/assistant/v2/service.py" in bound
    assert "src/career_lab/scenarios/v2/content_en.py" not in bound
    assert "src/career_lab/assistant/v2/english.py" not in bound
    en = runtime_source_files(ROOT, "en")
    assert set(bound) < set(en)
    assert "src/career_lab/assistant/v2/english.py" in en


def test_narrow_rebind_refuses_false_public_identity_before_output(package, tmp_path):
    before = (package.root / "manifest.json").read_bytes()
    with pytest.raises(ProtocolError, match="public manifest mismatch"):
        rebind(
            package.root,
            tmp_path / "wrong",
            contract_revision="expansion-v3-" + "f" * 64,
            scenario_revision="2.5.0-check",
            runtime_revision="check",
        )
    assert (
        not (tmp_path / "wrong").exists()
        and (package.root / "manifest.json").read_bytes() == before
    )
