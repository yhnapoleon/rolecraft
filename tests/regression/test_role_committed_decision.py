"""Local colleague replies lead with what happened, never with the learner's own words.

N1 and the 124 review P1s: a committed approval supersedes the initial brief for the
resources it granted, also for natural questions such as "current capacity", and a
recalled earlier question is context only, never the first cited passage.
"""

from .conftest import PublishedSession

CURRENT = {"zh": "当前试点容量是多少？", "en": "What is the current pilot capacity?"}
APPROVED_Q = {"zh": "目前已批准的容量是多少？", "en": "What capacity has been approved?"}
FOLLOW_UPS = {
    "zh": ["试点能覆盖多少人？", "我们应该现在就把试点开放给所有人吗？"],
    "en": ["Should we open the pilot to everyone now?", "How many people can the pilot cover?"],
}
APPROVED = {"zh": "已批准", "en": "approved"}
ORIGINAL = {"zh": "原始委托", "en": "original brief"}
DECISION = {"zh": "[业务决定 · v", "en": "[Business decision · v"}
BRIEF = {"zh": "[经理委托：", "en": "[Manager brief:"}
RECALL = {"zh": "[对话记录 · v", "en": "[Conversation · v"}


def ask(session: PublishedSession, key: str, question: str) -> list[str]:
    session.send(
        "turns", key, "turns.create", {"role_id": "supervisor", "text": question, "shares": []}
    )
    session.run_job()
    job = session.get("requests/" + key).json()
    assert job["jobs"][0]["status"] == "completed", job
    reply = [
        row["content"]
        for row in session.get("timeline").json()["result"]["result"]["objects"]
        if row["ref"]["kind"] == "role_reply" and row["content"]["question"] == question
    ][-1]
    assert reply["generation_mode"] == "local"
    assert "record_kind" not in reply["text"] and '{"' not in reply["text"]
    return [line for line in reply["text"].splitlines() if line.startswith("[")]


def approve_capacity(session: PublishedSession, amount: int) -> None:
    config = session.get("timeline").json()["result"]["result"]["workspace"]["config"]
    base = {
        "session_id": session.session_id,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    session.send(
        "configuration",
        "need",
        "configuration.apply",
        {
            "base": base,
            "settings": {
                "participants": amount,
                "work_items": ["scope_filter", "human_fallback"],
                "fallback": "human",
            },
        },
    )
    request = session.send(
        "actions",
        "ask",
        "request_business",
        {"tool": "request_business", "terms": {"capacity": amount}, "reason": "Pilot users."},
    )["result"]["request"]
    decided = session.send(
        "approvals/resolve",
        "grant",
        "resolve_approval",
        {"request": request, "expected_request_revision": 1},
    )
    assert decided["result"]["decision"]["status"] == "approved", decided


def test_current_capacity_leads_with_the_committed_decision(
    published_session: PublishedSession,
) -> None:
    session = published_session
    language = session.language
    before = ask(session, "before", CURRENT[language])
    assert before[0].startswith(BRIEF[language]) and "30" in before[0], before
    approve_capacity(session, 50)
    for key, question in [
        ("current", CURRENT[language]),
        ("approved", APPROVED_Q[language]),
        ("cover", FOLLOW_UPS[language][-1 if language == "en" else 0]),
    ]:
        cited = ask(session, key, question)
        first = cited[0]
        assert first.startswith(DECISION[language]), cited
        assert "50" in first and APPROVED[language] in first and ORIGINAL[language] in first
        # The initial brief and earlier questions may follow as context, never ahead of it.
        assert not any(line.startswith(RECALL[language]) for line in cited[:1]), cited
        brief = [i for i, line in enumerate(cited) if line.startswith(BRIEF[language])]
        assert all(i > 0 for i in brief), cited


def test_recalled_question_never_leads_a_follow_up(published_session: PublishedSession) -> None:
    session = published_session
    language = session.language
    ask(session, "first", CURRENT[language])
    for index, question in enumerate(FOLLOW_UPS[language]):
        cited = ask(session, f"follow-{index}", question)
        if not cited:
            continue
        assert not cited[0].startswith(RECALL[language]), cited
        recall = [i for i, line in enumerate(cited) if line.startswith(RECALL[language])]
        other = [i for i, line in enumerate(cited) if not line.startswith(RECALL[language])]
        assert all(r > o for r in recall for o in other), cited
