"""Optional practice consumes independently approved content and real saved feedback.

No session-link endpoint or normal v4 entry is claimed by these pure-plan checks.
"""

import importlib.util, json, os
from pathlib import Path
import pytest
from career_lab.contracts import v2 as C
from career_lab.rubrics.v4.practice import ReviewedPractice, suggestions, selection_plan

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "scenarios/pm_pilot/v2/variants"
pytestmark = pytest.mark.skipif(
    not os.environ.get("W05_W02_COMBO_ROOT"),
    reason="requires installed W02/W05 evaluation combination",
)
spec = importlib.util.spec_from_file_location(
    "frozen_w05_combination", ROOT / "tests/integration/test_w05_frozen_w02.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
combined = module.combined


def reviewed():
    data = json.loads((CATALOG / "reviewed-options-2.9.0.json").read_text())
    result = []
    for row in data["entries"]:
        row = dict(row)
        row["bindings"] = C.SessionBindings.model_validate(row["bindings"])
        row["review"] = C.FileRef.model_validate(row["review"])
        row["criteria"] = tuple(row["criteria"])
        cert = json.loads(C.read_file(CATALOG, row["review"]))
        assert cert["verdict"] == "accepted" and cert["scope"] == "authored_content_only"
        assert any(
            b["scenario_hash"] == row["bindings"].scenario.sha256
            and b["work_language"] == row["work_language"]
            for b in cert["bundles"]
        )
        result.append(ReviewedPractice(**row))
    return tuple(result)


def test_actual_feedback_can_offer_or_decline_reviewed_practice_without_rewriting_history(
    combined, tmp_path
):
    h, worker, queue, holder = combined
    h.apply(freshness_guard="warn")
    work = h.product("The current plan has not yet been tested after the policy change.")
    sub = h.submit((work,), "launch")
    assert worker.run_once()
    rows = [r for r in h.store.view(h.auth).objects if r.ref.kind == "feedback"]
    assert len(rows) == 1
    ref = rows[0].ref
    feedback = C.FeedbackV2.model_validate(rows[0].content)
    old = C.digest(feedback)
    catalog = reviewed()
    shown = suggestions(h.auth, ref, feedback, catalog, work_language=h.module.work_language)
    assert len(shown["options"]) == 2 and shown["can_decline"] and shown["can_choose_other"]
    assert all(
        x["work_language"] == h.module.work_language and x["basis"] for x in shown["options"]
    )
    declined = selection_plan(h.auth, ref, feedback, catalog, shown, choice="decline")
    selected = selection_plan(
        h.auth, ref, feedback, catalog, shown, choice="choose", option_id=shown["options"][0]["id"]
    )
    assert declined["choice"] == "decline" and declined["target"] is None
    assert not selected["creates_session"] and selected["new_session_id"] is None
    assert selected["learning_gain"] == "not_established"
    assert C.digest(C.FeedbackV2.model_validate(h.store.read(h.auth, ref).content)) == old
    assert (
        C.SubmissionV2.model_validate(
            h.store.read(
                h.auth,
                C.ObjectRef(session_id=h.sid, kind="submission", object_id=sub.id, version=1),
            ).content
        )
        == sub
    )
    (tmp_path / "reviewed-practice-plan.json").write_text(
        json.dumps(
            {
                "source": "real saved W02/W05 feedback; only suggestion/choice planning tested",
                "shown": shown,
                "declined": declined,
                "selected": selected,
                "normal_v4_entry": False,
                "cross_session_link_saved": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
