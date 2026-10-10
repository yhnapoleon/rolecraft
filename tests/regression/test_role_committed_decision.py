"""A committed approval is a fact the deciding colleague states in local mode (N1)."""

from .conftest import PublishedSession

QUESTION = {"zh": "目前已批准的容量是多少？", "en": "What capacity has been approved?"}
APPROVED = {"zh": "已批准", "en": "approved"}
TAG = {"zh": "[业务决定 · v", "en": "[Business decision · v"}


def test_approved_capacity_reaches_the_local_colleague_reply(
    published_session: PublishedSession,
) -> None:
    session = published_session
    language = session.language
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
        "need50",
        "configuration.apply",
        {
            "base": base,
            "settings": {
                "participants": 50,
                "work_items": ["scope_filter", "human_fallback"],
                "fallback": "human",
            },
        },
    )
    request = session.send(
        "actions",
        "ask50",
        "request_business",
        {"tool": "request_business", "terms": {"capacity": 50}, "reason": "50 pilot users."},
    )["result"]["request"]
    decided = session.send(
        "approvals/resolve",
        "grant50",
        "resolve_approval",
        {"request": request, "expected_request_revision": 1},
    )
    assert decided["result"]["decision"]["status"] == "approved", decided
    session.send(
        "turns",
        "question",
        "turns.create",
        {"role_id": "supervisor", "text": QUESTION[language], "shares": []},
    )
    session.run_job()
    job = session.get("requests/question").json()
    assert job["jobs"][0]["status"] == "completed", job
    reply = next(
        row["content"]
        for row in session.get("timeline").json()["result"]["result"]["objects"]
        if row["ref"]["kind"] == "role_reply"
    )
    assert reply["generation_mode"] == "local"
    cited = [x for x in reply["text"].splitlines() if x.startswith("[")]
    # The committed decision is the first cited passage, ahead of the initial brief.
    assert cited and cited[0].startswith(TAG[language]), reply["text"]
    lines = cited[:1]
    assert "50" in lines[0] and APPROVED[language] in lines[0], reply["text"]
    assert "record_kind" not in reply["text"] and "{" not in lines[0]
