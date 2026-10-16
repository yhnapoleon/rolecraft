"""ROLES entry (N3): recognizers decide which sources a colleague sees and annotate the
learner's state; C10 checks the reply afterwards.

``RoleRuntime.generate`` opens ``role_recognition(...)`` around ``generate_plan``; inside
it ``ContextSnapshot.select_sources`` ranks the ordinary sources by C2 relevance to the
question (attachments, shares, memory and the "later notice first" rule are kept), and
``build_prompt`` adds a ``learner_state`` entry (C11 intent + C5 phase and progress).
Outside the context manager both behave exactly as before.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from career_lab.recognition import retrieval

_ACTIVE: ContextVar[dict[str, Any] | None] = ContextVar("role_recognition", default=None)

GUIDE = {
    "zh": (
        "\n上下文中的 learner_state 是系统识别出的学员当前状态（意图、阶段、读过与未读的材料、"
        "测试次数、待批申请），只用于决定回答的详略与提醒（例如学员未读技术材料时提醒去读），"
        "不得据此泄露学员不可见的事实。"
    ),
    "en": (
        "\nlearner_state in the context is the learner's state as recognised by the system "
        "(intent, phase, materials read and unread, tests run, pending requests). Use it only "
        "to decide how much detail to give and what to remind them of (for example, to read "
        "the technical material they have not opened); never use it to reveal facts the "
        "learner cannot see."
    ),
}


@contextmanager
def role_recognition(recognized: dict[str, Any]):
    token = _ACTIVE.set(recognized or None)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active() -> dict[str, Any] | None:
    return _ACTIVE.get()


def rank(sources: list) -> list:
    """Sources ordered by C2 relevance to the active question (stable; unmatched last)."""
    state = active()
    if state is None or len(sources) < 2:
        return sources
    hits, _, _ = retrieval.search(
        state["question"], [s.text for s in sources], k=len(sources), method="rrf"
    )
    scores = {h.index: (h.score if (h.bm25 > 0 or (h.dense or 0) > 0) else 0.0) for h in hits}
    order = sorted(range(len(sources)), key=lambda i: (-scores.get(i, 0.0), i))
    return [sources[i] for i in order]


def learner_state_entry(language: str = "zh") -> tuple[dict[str, Any] | None, str]:
    state = active()
    if state is None or not state.get("learner_state"):
        return None, ""
    return state["learner_state"], GUIDE.get(language, GUIDE["zh"])


def before_reply(view, auth, envelope) -> dict[str, Any]:
    """C11 intent and C5 learner state for one role turn; {} when recognition is off.

    Phase names are language-neutral codes (explore / test / decide / adjust); the
    colleague prompt's guidance sentence follows the session language.
    """
    from career_lab.contracts.v2.core import ObjectRef
    from career_lab.recognition import behavior, intent, registry
    from career_lab.storage.role_memory import RoleTurn

    if registry.root() is None:
        return {}
    try:
        ref = ObjectRef.model_validate(envelope.command.payload["subject"])
        request = RoleTurn.model_validate(view.get(ref).content)
    except Exception:  # noqa: BLE001 - the original handler reports the real error
        return {}
    intent_record = intent.recognize(request.input.text, as_of=request.as_of)
    try:
        state = behavior.learner_state(
            view, auth, language="en", intent_record=intent_record
        )
    except Exception:  # noqa: BLE001 - state is an annotation, never a reason to fail
        state = {
            "intent": {"label": intent_record.label, "confidence": intent_record.score}
        }
    return {"intent": intent_record, "learner_state": state, "question": request.input.text}


def after_reply(reply, snapshot, auth, recognized: dict[str, Any]):
    """C10 grounding/leak check on the finished reply, stored with it."""
    from career_lab.recognition.reply import check_reply

    try:
        visible = [
            (f"{s.ref.kind}:{s.ref.object_id}@{s.ref.version}", s.text)
            for s in snapshot.select_sources(auth, 10**9)[0]
        ]
        private = [
            (f"fact:{fact.id}@{fact.version}", fact.source.quote or f"{fact.value} {fact.unit or ''}")
            for fact in snapshot.private_facts
            if fact.disclosure.mode != "public"
        ]
        check = check_reply(
            reply.text, visible, private, language=snapshot.work_language, as_of=reply.as_of
        )
        records = (recognized["intent"], check)
    except Exception:  # noqa: BLE001
        records = (recognized["intent"],)
    return reply.model_copy(update={"recognition": records})
