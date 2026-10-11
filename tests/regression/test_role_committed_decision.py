"""Local colleague replies lead with what happened, never with the learner's own words.

N1 and the 124 review P1s: a committed approval supersedes the initial brief for the
resources it granted, also for natural questions such as "current capacity"; a material
that arrived with a later world change (the demo moved to day 4) precedes the initial
brief; a recalled earlier question is context only, never the first or only citation;
and a decision leads only when the question shares a term with it.
"""

import json

from career_lab.runtime.roles_v2 import LocalRoleModel

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
NOTICE = {"zh": "[经理日程变更通知 · v2]", "en": "[Manager's calendar change · v2]"}
DEMO_Q = {"zh": "内部演示安排在第几天？", "en": "Which day is the internal demonstration?"}
DEMO_DAY = {"zh": "第4天", "en": "day 4"}
POLICY_Q = {
    "zh": "政策更新后需要重新测试吗？",
    "en": "Do we need to retest after the policy update?",
}
KEYWORD = {"zh": "试点期限", "en": "pilot deadline"}
STALE = {"zh": "容量是30人", "en": "capacity for 30 people"}


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
    for key, question in [("current", CURRENT[language]), ("approved", APPROVED_Q[language])]:
        cited = ask(session, key, question)
        first = cited[0]
        assert first.startswith(DECISION[language]), cited
        assert "50" in first and APPROVED[language] in first and ORIGINAL[language] in first
        # The initial brief and earlier questions may follow as context, never ahead of it.
        assert not any(line.startswith(RECALL[language]) for line in cited[:1]), cited
        brief = [i for i, line in enumerate(cited) if line.startswith(BRIEF[language])]
        assert all(i > 0 for i in brief), cited
    # No shared term with the decision: it does not lead by itself, but it still comes
    # before any cited passage that gives the superseded initial figure.
    cited = ask(session, "cover", FOLLOW_UPS[language][-1 if language == "en" else 0])
    decision = [i for i, line in enumerate(cited) if line.startswith(DECISION[language])]
    stale = [i for i, line in enumerate(cited) if STALE[language] in line]
    assert decision and all(decision[0] < i for i in stale), cited


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


def test_newer_notice_precedes_the_initial_brief(published_session: PublishedSession) -> None:
    """P1-B: the first request moves the demo from day 5 to day 4 (demo_schedule_changed)."""
    session = published_session
    language = session.language
    # Earlier conversation fills the prompt budget, as in a real session.
    for index, question in enumerate([CURRENT[language], *FOLLOW_UPS[language]]):
        ask(session, f"earlier-{index}", question)
    approve_capacity(session, 50)
    for key, question in [("current", CURRENT[language]), ("policy", POLICY_Q[language])]:
        ask(session, key, question)
    cited = ask(session, "demo", DEMO_Q[language])
    assert cited[0].startswith(NOTICE[language]) and DEMO_DAY[language] in cited[0], cited
    brief = [i for i, line in enumerate(cited) if line.startswith(BRIEF[language])]
    assert all(i > 0 for i in brief), cited


def test_decision_leads_only_on_a_shared_term(published_session: PublishedSession) -> None:
    """P2-4: a passage that merely names the resource does not put the decision first."""
    session = published_session
    language = session.language
    approve_capacity(session, 50)
    cited = ask(session, "policy", POLICY_Q[language])
    assert cited and not cited[0].startswith(DECISION[language]), cited


def test_keyword_question_leads_with_the_material_containing_it(
    published_session: PublishedSession,
) -> None:
    """P1-A: the material that contains the asked keyword is the first citation."""
    session = published_session
    language = session.language
    cited = ask(session, "keyword", KEYWORD[language])
    assert KEYWORD[language] in cited[0].casefold(), cited


def local_reply(language: str, sources: list[dict], question: str) -> str:
    context = {
        "work_language": language,
        "responsibilities": ["x"],
        "omissions": {"learner_scope": 0},
        "sources": sources,
    }
    return (
        LocalRoleModel()
        .complete(
            [
                {"role": "system", "content": "t\nCONTEXT\n" + json.dumps(context)},
                {"role": "user", "content": question},
            ],
            [],
        )
        .text
    )


def test_recall_alone_is_listed_not_cited() -> None:
    """A recalled question that is the only match is listed, so no reply leads with it."""
    for language, label, question in [
        ("zh", "对话记录 · v1", "当前试点容量是多少？"),
        ("en", "Conversation · v1", "What is the current pilot capacity?"),
    ]:
        recall = json.dumps({"historical_question": question, "historical_reply": "r"})
        text = local_reply(
            language,
            [
                {"display_name": "Brief · v1", "text": "unrelated text", "channel": "material"},
                {"display_name": label, "text": recall, "channel": "memory"},
            ],
            question,
        )
        assert not [line for line in text.splitlines() if line.startswith("[")], text
        assert f"[{label}]" in text.splitlines()[-1], text


def test_newer_notice_is_admitted_before_initial_materials() -> None:
    """P1-B: a relevant later notice is never crowded out by earlier, equally matching ones."""
    for language, notice, question in [
        ("zh", "内部演示改到第4天。", "内部演示安排在第几天？"),
        (
            "en",
            "The internal demonstration moves to day 4.",
            "Which day is the internal demonstration?",
        ),
    ]:
        initial = [
            {
                "display_name": f"Material {i} · v1",
                "text": f"{notice.replace('4', '5')} {i}",
                "channel": "material",
                "observed_at_seq": 0,
            }
            for i in range(5)
        ]
        later = {
            "display_name": "Notice · v2",
            "text": notice,
            "channel": "material",
            "observed_at_seq": 4,
        }
        text = local_reply(language, [*initial, later], question)
        cited = [line for line in text.splitlines() if line.startswith("[")]
        assert cited[0] == f"[Notice · v2] {notice}", text


SCOPE_Q = {"zh": "试点范围应该怎么定？", "en": "How should we set the pilot scope?"}
INVITE_Q = {"zh": "可以邀请更多人参加试点吗？", "en": "Can we invite more people to the pilot?"}
DEADLINE_Q = {"zh": "正式试点期限是第几天？", "en": "Which day is the pilot deadline?"}
DEADLINE = {"zh": "第7天", "en": "day 7"}


def test_notice_needs_two_terms_and_keeps_given_figures_first(
    published_session: PublishedSession,
) -> None:
    """P2-5: the attendee notice shares one generic word with scope or invitation
    questions and must not lead; for the deadline the brief's figure stays first."""
    session = published_session
    language = session.language
    approve_capacity(session, 50)
    for key, question in [("scope", SCOPE_Q[language]), ("invite", INVITE_Q[language])]:
        cited = ask(session, key, question)
        assert not cited or not cited[0].startswith(NOTICE[language]), cited
    for key, question in [("deadline", DEADLINE_Q[language]), ("keyword", KEYWORD[language])]:
        cited = ask(session, key, question)
        assert DEADLINE[language] in cited[0], cited
