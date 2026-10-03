from career_lab.assistant.service import TrainingService
from career_lab.evidence.assembler import EvidenceAssembler
from career_lab.evidence.serializer import serialize_prompt
from career_lab.storage.sessions import SessionStore


def make_submission(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'evidence.db'}")
    store.create_session(spec, "s")
    service = TrainingService(store)
    plan = {"participants": 20, "knowledge_domains": ["stable_faq"], "launch_day": 7, "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}
    service.action("s", "update_pilot", {"plan": plan}, "c", 0)
    artifact = service.save_artifact("s", {"rationale": "限定稳定FAQ，遵守人数限制"}, "a")
    submission = service.submit_plan("s", artifact["id"], 1, "s")
    return store, submission


def test_no_future_or_private_evidence(tmp_path, spec):
    store, submission = make_submission(tmp_path, spec)
    item = EvidenceAssembler(store).assemble_item(submission["id"], "R3.capacity", "oracle")
    prompt = str(serialize_prompt(item))
    assert "legacy_connector" not in prompt
    assert "400元" not in prompt
    assert item.input_hash
    assert item.context.capacity == 30


def test_overflow_is_explicit(tmp_path, spec):
    store, submission = make_submission(tmp_path, spec)
    item = EvidenceAssembler(store, token_budget=10).assemble_item(submission["id"], "R3.capacity", "oracle")
    assert item.completeness == "overflow"
    assert item.context is None


def test_missing_test_object_is_unknown_not_not_met(tmp_path, spec):
    from sqlalchemy import delete
    from career_lab.storage.database import objects
    from career_lab.rubrics.checks import run_rule_checks
    store = SessionStore(f"sqlite:///{tmp_path / 'missing.db'}")
    store.create_session(spec, "s")
    service = TrainingService(store)
    plan = {"participants": 20, "knowledge_domains": ["stable_faq"], "launch_day": 7, "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}
    service.action("s", "update_pilot", {"plan": plan}, "c", 0)
    test = service.run_assistant_test("s", "如何申请会议室？", 1, "test")
    artifact = service.save_artifact("s", {}, "a")
    submission = service.submit_plan("s", artifact["id"], 1, "s")
    with store.db.transaction() as conn:
        conn.execute(delete(objects).where(objects.c.id == test["id"]))
    item = EvidenceAssembler(store).assemble_item(submission["id"], "R4.functional_tests", "oracle")
    assert not item.context.logs_complete
    assert run_rule_checks(item)[0].label == "INSUFFICIENT"


def test_old_config_test_does_not_validate_new_config(tmp_path, spec):
    from career_lab.rubrics.checks import run_rule_checks
    store = SessionStore(f"sqlite:///{tmp_path / 'changed.db'}")
    store.create_session(spec, "s")
    service = TrainingService(store)
    plan = {"participants": 20, "knowledge_domains": ["stable_faq"], "launch_day": 7, "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}
    service.action("s", "update_pilot", {"plan": plan}, "c", 0)
    service.run_assistant_test("s", "如何申请会议室？", 1, "test")
    service.action("s", "update_pilot", {"plan": plan | {"knowledge_domains": ["policy"]}}, "c2", store.get_state("s").version)
    artifact = service.save_artifact("s", {}, "a")
    submission = service.submit_plan("s", artifact["id"], 2, "s")
    item = EvidenceAssembler(store).assemble_item(submission["id"], "R4.functional_tests", "oracle")
    assert run_rule_checks(item)[0].label == "NOT_MET"
