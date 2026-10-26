"""Spec v2 §6.6: are sentence marks for one PRD version independent of the submit decision?

Runs the existing read-only recognition draft check (rule fallback: no weights, no model) for
all four decisions, and compares exactly what the C1 path reads: the PRD sentence units, the
candidate material evidence and the observed point. Read-only use of recognition code.
"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api import evaluation_runtime as ER
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.models.v3.units import support_units

ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ("launch", "launch_narrow", "defer_with_conditions", "no_go")
NEED = (
    "工单平均处理时长是 429 分钟，所以每单节省 429 分钟人工。"
    "报销政策规定超过 5000 元需要经理审批。助手可以直接批准报销。"
)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_sentence_marks_do_not_depend_on_the_decision(tmp_path, monkeypatch, language):
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path / "no-weights"))
    installed = json.loads((ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "rec.db"),
        scenario_root=ROOT / installed["main"][language]["root"],
    )
    store = app.state.v2_store
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        assert created.status_code == 200, created.text
        sid, token = created.json()["session_id"], created.json()["token"]
        auth = store.authenticate(sid, token)

        def point():
            state = store.view(auth).state
            return state.business_seq, state.workspace_revision

        seq, rev = point()
        body = C.Command(
            schema_version=2,
            request_id=uuid.uuid4().hex,
            expected_version=seq,
            expected_workspace_revision=rev,
            operation="work_products.create",
            payload={
                "kind": "plan",
                "purpose": "plan",
                "structured_payload": {"type": "plan", "sections": {"need": NEED}},
            },
        ).model_dump(mode="json")
        out = app.state.w06.call(
            sid, token, "work_products.create", {"session_id": sid, "command": body}
        )
        prd = C.ObjectRef.model_validate(next(o for o in out["objects"] if o["kind"] == "product"))
        bindings, _ = store.session_metadata(auth)
        checks = app.state.gateway.registry.rule_checks[C.canonical(bindings)]
        marks, inputs = {}, {}
        for decision in DECISIONS:
            seq, rev = point()
            request = C.SubmissionRuleCheckRequest(
                schema_version=2,
                request_id=uuid.uuid4().hex,
                expected_version=seq,
                expected_workspace_revision=rev,
                operation="submissions.rule_check",
                payload=C.SubmitInput(decision=decision, products=(prd,)),
            )
            result = checks.draft_recognition(store, auth, request)
            assert result["enabled"] is True
            recognition = dict(result["recognition"])
            recognition.pop("duration_ms", None)  # wall-clock timing only
            marks[decision] = recognition
            source = ER.ScenarioEvidencePort(store, checks.module)
            reader = checks._reader(store, auth, source, source.draft_submission_rules)
            submission = ER.unsaved_submission(store, auth, reader, request)
            evaluator = ER.SubmissionEvaluator(
                ER.FixedWindowReads(reader), work_language=checks.module.work_language
            )
            _, packages = evaluator.rule_items(auth, submission)
            support = next(p for p in packages if p.criterion == "R2.support")
            inputs[decision] = (
                [u.text for u in support_units(support).units],
                sorted((c.id, c.text) for c in support.candidate_evidence),
                support.as_of.business_seq,
            )
        first = marks[DECISIONS[0]]
        assert first.get("units"), "the check produced no sentence units"
        assert all(marks[d] == first for d in DECISIONS)
        assert all(inputs[d] == inputs[DECISIONS[0]] for d in DECISIONS)
