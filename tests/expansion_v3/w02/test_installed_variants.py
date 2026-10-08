"""Actual new-constraint sessions with installed feedback; normal v4 linking is separate."""

from pathlib import Path
from types import SimpleNamespace
import importlib.util, json, os
import pytest
from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.evidence_ports.store import create_store_fact_adapter
from career_lab.scenarios.v2.module import point

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "w05_variant_combo", ROOT / "tests/integration/test_w05_frozen_w02.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


@pytest.fixture(
    params=[
        (sid, lang) for sid in ["pm_pilot_urgent", "pm_pilot_capacity15"] for lang in ["zh", "en"]
    ]
)
def variant(request, tmp_path, monkeypatch):
    sid, lang = request.param
    monkeypatch.setenv("W05_W02_COMBO_ROOT", str(ROOT))
    monkeypatch.setenv(
        "W05_W02_SCENE_ROOT",
        str(ROOT / "scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.6" / sid),
    )
    generator = base.combined.__wrapped__(SimpleNamespace(param=lang), tmp_path)
    value = next(generator)
    h = value[0]
    h.adapter = create_store_fact_adapter(h.store, h.module, h.gateway.registry)
    h.windows.clear()
    h.events.clear()
    h.capture = lambda result=None: point(h.store.view(h.auth).state)
    try:
        yield value
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


@pytest.mark.parametrize("decision", ["launch_narrow", "defer_with_conditions"])
def test_reviewed_variant_config_change_actual_test_and_saved_feedback(variant, decision, tmp_path):
    h, worker, queue, holder = variant
    question = (
        "住宿报销上限是多少？"
        if h.module.work_language == "zh"
        else "What is the hotel reimbursement limit per night?"
    )
    initial = h.run(question)
    resources = dict(h.module.package.bundle.initial_resources)
    assert initial["config"]["differences"]
    h.apply(
        participants=min(20, resources["capacity"]),
        launch_day=resources["deadline_day"],
        freshness_guard="warn",
    )
    stale = h.run(question)
    assert "500" in stale["answer"]
    h.post("actions", "refresh_index", {"tool": "refresh_index"})
    fresh = h.run(question)
    assert "400" in fresh["answer"]
    works = (
        h.product("Scope adjusted to this assignment allocation."),
        h.product("Policy refreshed and retested. Next steps remain documented separately."),
    )
    submission = h.submit(works, decision)
    assert worker.run_once()
    rows = [r for r in h.store.view(h.auth).objects if r.ref.kind == "feedback"]
    assert len(rows) == 1
    report = C.FeedbackV2.model_validate(rows[0].content)
    labels = {i.criterion: i.label for i in report.rule_items}
    assert len(report.rule_items) == 14
    expected = "MET" if decision == "launch_narrow" else "NOT_APPLICABLE"
    assert all(
        labels[cid] == expected
        for cid in ["R3.capacity", "R3.resources", "R4.staleness_test", "R5.adjustment"]
    )
    assert not h.windows and not h.events
    digest = C.digest(report)
    assert not worker.run_once()
    assert (
        C.digest(C.FeedbackV2.model_validate(h.store.read(h.auth, rows[0].ref).content)) == digest
    )
    (tmp_path / "variant-feedback.json").write_text(
        json.dumps(
            {
                "scenario_id": h.module.package.bundle.id,
                "language": h.module.work_language,
                "decision": decision,
                "bindings": h.module.bindings.model_dump(mode="json"),
                "resources": resources,
                "initial_test": initial,
                "stale_test": stale,
                "fresh_test": fresh,
                "submission": submission.model_dump(mode="json"),
                "feedback": report.model_dump(mode="json"),
                "source": "real FastAPI/Gateway/SQLite/worker and persisted authorized history",
                "normal_v4_verified": False,
                "cross_session_link_verified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
