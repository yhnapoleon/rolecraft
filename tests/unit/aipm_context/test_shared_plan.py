"""A shared PRD (plan) reaches a colleague as its written sections, not an empty content."""

from types import SimpleNamespace

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.workspace import PlanPayload
from career_lab.runtime.roles_v2 import _readable_source
from career_lab.storage.shared_work import shared_work


def plan(content=""):
    # Only the fields shared_work reads, as on a saved WorkProductVersion.
    sections = {"need": "Tickets take 429 minutes.", "business": "Internal staff.", "boundary": " "}
    return SimpleNamespace(
        title="Pilot PRD",
        content=content,
        purpose="plan",
        structured_payload=PlanPayload(sections=sections),
    )


def test_plan_share_lists_written_sections_in_order():
    shown = shared_work(plan())
    assert "content" not in shown and shown["kind"] == "plan"
    assert shown["sections"] == [
        {"section": "need", "text": "Tickets take 429 minutes."},
        {"section": "business", "text": "Internal staff."},
    ]
    text = C.canonical(shown)
    assert _readable_source({"text": text}, "en") == (
        "Pilot PRD\nTickets take 429 minutes.\nInternal staff."
    )


def test_other_works_keep_their_shape():
    shown = shared_work(plan(content="Free text"))
    assert shown["content"] == "Free text" and "structured_payload" in shown
