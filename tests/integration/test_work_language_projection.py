"""A saved test plan reads in the session's work language wherever its text is projected.

The draft check's sentence list ("Check this version") and the result page read the work
through the evidence reader; the scenario module checks quotes of the same work. Both take
the language of the session's scenario module, so their texts are the same, and quotes
stored before English labels (2026-10-27) still resolve.
"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api import evaluation_runtime as ER
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, product_text
from career_lab.storage.v2_lifecycle import point

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "zh": [
        {"id": "c1", "query": "每晚住宿报销上限是多少？", "declared_expected": "每晚 500 元"},
        {"id": "c2", "query": "火星上天气怎么样？", "declared_expected": "说明超出范围并转人工"},
    ],
    "en": [
        {
            "id": "c1",
            "query": "What is the hotel reimbursement limit per night?",
            "declared_expected": "CNY 500 per person per night",
        },
        {
            "id": "c2",
            "query": "What is the weather on Mars?",
            "declared_expected": "Say it is out of scope and hand over to a person",
        },
    ],
}
LABEL = {"zh": "\n预期（待验证）：", "en": "\nExpected outcome (unverified): "}


def has_cjk(text):
    return any("　" <= ch <= "鿿" or "＀" <= ch <= "￯" for ch in text)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_test_plan_text_follows_the_work_language(tmp_path, monkeypatch, language):
    # Rule fallback recognition: no weights and no model call.
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path / "no-weights"))
    installed = json.loads((ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "plan.db"),
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

        def command(operation, payload):
            state = store.view(auth).state
            return C.Command(
                schema_version=2,
                request_id=uuid.uuid4().hex,
                expected_version=state.business_seq,
                expected_workspace_revision=state.workspace_revision,
                operation=operation,
                payload=payload,
            ).model_dump(mode="json")

        body = command(
            "work_products.create",
            {
                "kind": "test_plan",
                "purpose": "test_plan",
                "title": "Evaluation plan",
                "structured_payload": {"type": "test_plan", "cases": CASES[language]},
            },
        )
        out = app.state.w06.call(
            sid, token, "work_products.create", {"session_id": sid, "command": body}
        )
        plan = C.ObjectRef.model_validate(next(o for o in out["objects"] if o["kind"] == "product"))
        work = C.WorkProductVersion.model_validate(store.read(auth, plan).content)
        expected = product_text(work, work_language=language)
        assert expected.count(LABEL[language]) == 2
        assert has_cjk(expected) == (language == "zh")

        bindings, _ = store.session_metadata(auth)
        checks = app.state.gateway.registry.rule_checks[C.canonical(bindings)]
        assert checks.module.work_language == language
        state = store.view(auth).state
        request = C.SubmissionRuleCheckRequest(
            schema_version=2,
            request_id=uuid.uuid4().hex,
            expected_version=state.business_seq,
            expected_workspace_revision=state.workspace_revision,
            operation="submissions.rule_check",
            payload=C.SubmitInput(decision="launch", products=(plan,)),
        )
        # The sentence list the draft check shows for this work.
        recognition = checks.draft_recognition(store, auth, request)["recognition"]
        quotes = [unit["quote"] for unit in recognition["units"]]
        assert any(LABEL[language].strip() in quote for quote in quotes), quotes
        if language == "en":
            assert not any(has_cjk(quote) for quote in quotes), quotes

        # The evidence reader the check uses and the module's own quote check agree.
        source = ER.ScenarioEvidencePort(store, checks.module)
        reader = checks._reader(store, auth, source, source.draft_submission_rules)
        record = reader.read(auth, plan, reader.captured_at)
        assert record.text == expected
        start = expected.index(LABEL[language].strip())
        quoted = record.ref.model_copy(
            update={
                "span_start": start,
                "span_end": expected.index("\n\n"),
                "quote": expected[start : expected.index("\n\n")],
            }
        )
        assert store.query(auth, lambda view: checks.module.check_evidence(view, auth, quoted))
        resolved = EvidenceAssemblerV2(reader, work_language=language).resolve(
            auth, quoted, point(state)
        )
        assert resolved.text == quoted.quote

        # A quote stored while English work still carried the Chinese label still resolves;
        # a Chinese session keeps exactly one projection.
        legacy = product_text(work)
        assert record.earlier_texts == (() if language == "zh" else (legacy,))
        if language == "en":
            start = legacy.index("预期")
            old = record.ref.model_copy(
                update={
                    "span_start": start,
                    "span_end": legacy.index("\n\n"),
                    "quote": legacy[start : legacy.index("\n\n")],
                }
            )
            assert store.query(auth, lambda view: checks.module.check_evidence(view, auth, old))
            assert EvidenceAssemblerV2(reader).resolve(auth, old, point(state)).text == old.quote
