from career_lab.storage.sessions import SessionStore
from career_lab.assistant.service import TrainingService


def setup_service(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'assistant.db'}")
    store.create_session(spec, "s")
    return TrainingService(store)


def plan():
    return {"participants": 20, "knowledge_domains": ["stable_faq", "policy"], "launch_day": 7,
            "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}


def test_source_index_and_config_version_recorded(tmp_path, spec):
    service = setup_service(tmp_path, spec)
    service.action("s", "update_pilot", {"plan": plan()}, "config", 0)
    service.action("s", "read_material", {"material_id": "brief"}, "read1", 1)
    service.action("s", "read_material", {"material_id": "business"}, "read2", 2)
    run = service.run_assistant_test("s", "住宿报销上限是多少？", 1, "test")
    assert run["source_versions"]["policy"] == 2
    assert run["indexed_versions"]["policy"] == 1
    assert "500" in run["answer"]
    assert run["stale"] is True
    assert service.run_assistant_test("s", "住宿报销上限是多少？", 1, "test") == run
    current = service.store.get_state("s")
    service.action("s", "update_pilot", {"plan": plan() | {"update_strategy": "manual_policy"}}, "config2", current.version)
    new = service.run_assistant_test("s", "住宿报销上限是多少？", 2, "test2")
    assert new["fallback"] is True
    assert new["config_version"] == 2

