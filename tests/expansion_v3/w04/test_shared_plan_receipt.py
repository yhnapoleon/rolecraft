"""After a plan is shared with a colleague, that colleague keeps talking (QA X-1, 2026-10-27).

Every later turn replays the share receipts of earlier turns; the replay must recompute the
fragment text with the same projection the context port wrote it with.
"""

from pathlib import Path

import pytest
from test_cooperative_help import Dialogue

from career_lab.contracts.v2 import WorkProductVersion, canonical
from career_lab.runtime.context_v2 import role_text
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.storage.shared_work import receipt_texts, shared_work_text

SECTIONS = {
    "zh": {
        "business": "内部员工问报销和差旅政策。",
        "need": "工单平均 429 分钟结单。",
        "boundary": "",
    },
    "en": {
        "business": "Staff ask about expense and travel policy.",
        "need": "Tickets take 429 minutes to close.",
        "boundary": "",
    },
}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_colleague_answers_again_after_a_plan_was_shared(
    tmp_path: Path, language: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []
    complete = LocalRoleModel.complete

    def recording(self, messages, tools):
        prompts.append(messages[0]["content"])
        return complete(self, messages, tools)

    monkeypatch.setattr(LocalRoleModel, "complete", recording)
    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    own_work = role_text(language, "own_work_reply")
    try:
        greeted = dialogue.ask("Hello", role="business_lead")
        assert greeted["status"] == "completed", greeted
        assert own_work not in prompts[-1]
        product = dialogue.command(
            "work_products.create",
            {
                "kind": "plan",
                "purpose": "plan",
                "title": "PRD",
                "structured_payload": {"type": "plan", "sections": SECTIONS[language]},
            },
        )["result"]["ref"]
        share = dialogue.command(
            "work_products.shares.create",
            {
                "product_id": product["object_id"],
                "product_version": 1,
                "recipient_role": "business_lead",
            },
        )["result"]["ref"]
        first = dialogue.command(
            "turns.create",
            {"role_id": "business_lead", "text": "Is the need right?", "shares": [share]},
        )
        dialogue.worker.run_once()
        assert dialogue.jobs.get(first["result"]["queued_jobs"][0])["status"] == "completed"
        # With the learner's own work in front of them, the two-sentence rule comes last.
        assert prompts[-1].split("\nCONTEXT\n", 1)[0].endswith(own_work)
        # Receipts written before the plan projection (2026-10-26) carry the four-field text.
        stored = next(
            x for x in dialogue.store.view(dialogue.auth).objects if x.ref.kind == "product"
        )
        current = shared_work_text(WorkProductVersion.model_validate(stored.content))
        legacy = canonical(
            {k: stored.content[k] for k in ("title", "content", "purpose", "structured_payload")}
        )
        assert current != legacy and '"sections"' in current
        assert receipt_texts(stored.content) == {current, legacy}
        for question in ("And the boundary?", "One more thing."):
            later = dialogue.ask(question, role="business_lead")
            assert later["status"] == "completed", later
    finally:
        dialogue.close()
