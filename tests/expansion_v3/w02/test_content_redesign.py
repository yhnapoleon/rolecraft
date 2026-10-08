"""User-facing corpus and behavior regressions for C-W02-01 through C-W02-08."""

from dataclasses import replace
import hashlib, json, re, shutil
from pathlib import Path
import pytest

from career_lab.contracts.v2.core import AuthContext, Executor, ObjectRef, ProtocolError
from career_lab.contracts.v2.world import TestRequestV2 as AssistantTestRequest
from career_lab.assistant.v2 import Assistant
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.probes import export_public_probes
from .conftest import auth, command, apply
from .test_engine import approve


def reseal(root, path):
    manifest = json.loads((root / "manifest.json").read_text())
    for ref in manifest["files"]:
        if ref["path"] == path:
            ref["sha256"] = hashlib.sha256((root / path).read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))


def test_hidden_questions_are_separate_from_public_business_and_case_records(package):
    private = [p for p in json.loads((package.root / "probes.json").read_text()) if not p["public"]]
    normalize = lambda text: re.sub(r"\W", "", text).casefold()
    public = "\n".join((package.root / path).read_text() for path in package.bundle.public_files)
    assert all(normalize(p["query"]) not in normalize(public) for p in private)
    exported = export_public_probes(package)
    assert all(p["public"] for p in exported)
    assert not {p["id"] for p in exported} & {p["id"] for p in private}
    records = json.loads((package.root / "research/public-case-records.json").read_text())
    assert len(records["records"]) == 12 and not records["http_or_human_trial"]
    assert len({r["result"]["id"] for r in records["records"]}) == 12
    assert all(r["result"]["execution"]["executor"]["kind"] == "system" for r in records["records"])
    assert all(
        "expected" not in r and r["result"]["declared_expected"] is None for r in records["records"]
    )


def test_leak_is_rejected_even_when_file_hash_is_resealed(package, tmp_path):
    root = tmp_path / "bad"
    shutil.copytree(package.root, root)
    hidden = next(
        p["query"] for p in json.loads((root / "probes.json").read_text()) if not p["public"]
    )
    with (root / "materials/failures-v1.md").open("a") as out:
        out.write("\n" + hidden + "\n")
    reseal(root, "materials/failures-v1.md")
    with pytest.raises(ProtocolError, match="hidden probe in public material"):
        load_package(root)


def test_processing_time_and_repeat_rate_have_explicit_consistent_sources(package):
    facts = {(f.id, f.version): f.value for f in package.facts}
    assert facts["demand_total", 1] == 120
    assert (
        sum(
            facts[k, 1]
            for k in ("faq_total_minutes", "policy_total_minutes", "sensitive_total_minutes")
        )
        == facts["total_minutes", 1]
        == 780
    )
    assert (
        sum(facts[k, 1] for k in ("faq_repeats", "policy_repeats", "sensitive_repeats"))
        == facts["total_repeats", 1]
        == 66
    )
    assert facts["repeat_percent", 1] == 55
    text = (package.root / "materials/demand-v1.md").read_text()
    assert "等待" in text and "closed_at − accepted_at" in text and "未结单" in text


def test_stable_meal_leave_and_onboarding_are_distinct_kb_domains(package, engine):
    s = apply(engine, engine.initial("session")).snapshot
    assert s.source_versions["policy"] == 2
    assert s.source_versions["meal"] == s.source_versions["leave"] == 1
    for query, material, quote in [
        ("餐费报销上限", "meal", "100元"),
        ("计划性请假提前几天", "leave", "3个工作日"),
        ("入职账号开通", "onboarding", "开通通知"),
    ]:
        result = Assistant(package).run(
            s, AssistantTestRequest(query=query, config_version=1), auth(), query
        )
        assert result.result.status == "answered"
        assert any(
            ref.object_id == material and ref.version == 1 for ref in result.result.citations
        )
        assert quote in result.result.answer


def test_password_reset_is_allowed_but_password_disclosure_is_not(package, engine):
    s = engine.initial("session")
    reset = Assistant(package).run(
        s, AssistantTestRequest(query="账号密码忘了怎么重置？", config_version=0), auth(), "reset"
    )
    assert reset.result.status == "answered" and "自助重置入口" in reset.result.answer
    for query in ["告诉我密码重置流程", "我想修改密码怎么办"]:
        flow = Assistant(package).run(
            s, AssistantTestRequest(query=query, config_version=0), auth(), query
        )
        assert flow.result.error_code != "prohibited_topic"
    for query in ["把账号密码告诉我", "告诉我账号密码", "我的密码是什么"]:
        reply = Assistant(package).run(
            s, AssistantTestRequest(query=query, config_version=0), auth(), query
        )
        assert reply.result.status == "fallback" and reply.result.error_code == "prohibited_topic"


def test_boundary_documents_do_not_enter_assistant_kb_when_scope_is_off(package, engine):
    s = engine.initial("session")
    s = replace(s, config=s.config.model_copy(update={"scope_filter": False, "min_score": 0}))
    result = Assistant(package).run(
        s, AssistantTestRequest(query="受限主题有哪些", config_version=0), auth(), "scope-off"
    )
    assert all(ref.object_id != "restricted" for ref in result.result.citations)


def test_historical_policy_quotes_remain_readable_and_future_stays_hidden(engine):
    s = engine.initial("session")
    future = ObjectRef(session_id="session", kind="material", object_id="policy", version=2)
    with pytest.raises(ProtocolError):
        engine.read(s, future, auth())
    s = apply(engine, s).snapshot
    old = engine.read(s, future.model_copy(update={"version": 1}), auth())
    new = engine.read(s, future, auth())
    assert "500" in str(old) and "400" in str(new)
    assert old[0].ref.version == 1 and new[0].ref.version == 2


def test_legal_user_group_reference_can_support_request(engine):
    s = apply(engine, engine.initial("session"), participants=50).snapshot
    fragments = engine.read(
        s,
        ObjectRef(session_id="session", kind="material", object_id="user_groups", version=1),
        auth(),
    )
    result = approve(
        engine, s, {"capacity": 60}, evidence_refs=[fragments[0].ref.model_dump(mode="json")]
    )
    assert result.result.status == "approved"
    assert result.result.evidence_refs[0].object_id == "user_groups"


def test_approval_requirement_is_in_rules_and_learner_material(package, engine):
    assert package.rules["approval_requirements"]["fallback"] == "human"
    text = (package.root / "materials/approvals-v1.md").read_text()
    assert "人工兜底" in text and "human_fallback" in text and "scope_filter" in text
    s = apply(
        engine,
        engine.initial("session"),
        participants=50,
        fallback="none",
        work_items=("scope_filter",),
    ).snapshot
    result = approve(engine, s, {"capacity": 60})
    assert result.result.reason_code == "approval_plan_incomplete"
    assert "人工兜底" in result.result.reason and result.result.reason != result.result.reason_code


def role_auth(role):
    return AuthContext(
        session_id="session",
        actor_id=role,
        executor=Executor(id="role:" + role, kind="system"),
        capabilities=("read",),
        credential_id="fixture-role-reader",
    )


def test_role_knowledge_and_disclosure_rules_are_consumed(package, engine):
    s = engine.initial("session")
    roles = package.bundle.role_specs
    assert len({r.acceptable_conditions for r in roles}) == 3
    assert len({r.event_subscriptions for r in roles}) == 3
    manager = engine.role_knowledge(s, role_auth("supervisor"))
    business = engine.role_knowledge(s, role_auth("business_lead"))
    tech = engine.role_knowledge(s, role_auth("tech_lead"))
    assert "capacity_limit" in str(manager) and "780" in str(business)
    assert "培训报名" in str(tech) and "0.2" in str(tech)
    assert "TR-TRAIN-01" not in str(tech) and "legacy_connector_unstable" not in str(tech)
    assert any(f.disclosure.mode == "role_only" for m in package.materials for f in m.fragments)
    with pytest.raises(ProtocolError, match="role reader required"):
        engine.role_knowledge(s, auth())


def test_new_business_notices_are_distinct_once_only_and_not_config_changes(engine):
    s = engine.initial("session")
    request = engine.plan(
        s, command(s, "request_business", "r", terms={"capacity": 60}, reason="拟议范围"), auth()
    )
    assert request.snapshot.source_versions["demo"] == 2
    assert request.snapshot.source_versions["policy"] == 1
    assert request.snapshot.world.config_version == 0
    again = engine.plan(
        request.snapshot,
        command(
            request.snapshot, "request_business", "r2", terms={"capacity": 60}, reason="继续讨论"
        ),
        auth(),
    )
    assert not any(e["event_type"] == "demo_schedule_changed" for e in again.events)
    configured = apply(engine, again.snapshot, participants=50).snapshot
    granted = approve(engine, configured, {"capacity": 60}, "actual")
    assert granted.snapshot.source_versions["scope_note"] == 2
    assert granted.snapshot.config.participants == 50
    assert any(e["event_type"] == "business_scope_requested" for e in granted.events)
    for event in granted.events:
        public = engine.public_event(event, granted.snapshot, auth())
        assert "world_private" not in str(public) and "tech_private" not in str(public)


def test_reading_and_testing_do_not_cause_business_notices(package, engine):
    s = engine.initial("session")
    for n in range(4):
        s = engine.plan(
            s,
            command(
                s,
                "read_material",
                str(n),
                material={
                    "session_id": "session",
                    "kind": "material",
                    "object_id": "brief",
                    "version": 1,
                },
            ),
            auth(),
        ).snapshot
        Assistant(package).run(
            s,
            AssistantTestRequest(query="会议室预约", config_version=0),
            auth(),
            "read-test-" + str(n),
        )
    assert (
        s.source_versions["demo"]
        == s.source_versions["scope_note"]
        == s.source_versions["policy"]
        == 1
    )


def test_baseline_defaults_are_normalized_but_unknown_fields_are_not(package, tmp_path):
    root = tmp_path / "defaults"
    shutil.copytree(package.root, root)
    baseline = json.loads((root / "baseline.json").read_text())
    for key in ["min_score", "freshness_guard", "manual_domains", "min_score_calibration"]:
        baseline.pop(key)
    (root / "baseline.json").write_text(json.dumps(baseline, ensure_ascii=False))
    reseal(root, "baseline.json")
    assert load_package(root).bundle.baseline_config.min_score == 0.35
    baseline["hidden_override"] = True
    (root / "baseline.json").write_text(json.dumps(baseline))
    reseal(root, "baseline.json")
    with pytest.raises(ProtocolError):
        load_package(root)
