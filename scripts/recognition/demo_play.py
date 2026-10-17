"""Play one showcase practice end to end, so every recognition badge has something to show.

    python -m scripts.recognition.demo_play --scenario pm_pilot --language zh [--revise]

The route (all through the public HTTP API, like the browser):
  read materials -> assistant tests (in scope, policy, out of scope: C2 / C4)
  -> one question to each colleague (C11 intent, C10 grounding, DeepSeek replies)
  -> apply the first plan (publishes the policy update) -> policy question before and
     after an index refresh (drift) -> write the work (mostly supported sentences, one
     subtle overstatement) -> submit -> wait for the Judge (C1 / C6 / arbiter)
  -> optionally a revision round that fixes the overstatement and submits again.
Prints the session id and a continue code. Export the sessions afterwards with
``scripts.recognition.demo_pack export``.
"""

from __future__ import annotations

import argparse
import sys

from scripts.recognition.client import DEFAULT_API, Session

READS = ["brief", "technical", "approvals", "user_groups", "demand", "interviews", "faq", "policy"]

TEXT = {
    ("pm_pilot", "zh"): {
        "tests": ["账号密码忘了怎么重置？", "住宿报销上限是多少？", "火星天气如何？"],
        "policy": "住宿报销上限是多少？",
        "asks": [
            ("tech_lead", "试点最多能上多少人？"),
            ("business_lead", "SD-120 里的 429 分钟能直接算成节省的人力吗？"),
            ("supervisor", "如果首批只开 20 人，还需要先申请资源吗？"),
        ],
        "work": [
            "建议首批只开放给新员工组的 20 人，先验证入口指引类问题；动态政策问题暂不自动回答，转人工核验。",
            "目前项目预留容量是 30 人，可用开发资源 3 人日，正式试点期限为第 7 天；20 人在容量以内，不需要申请扩容。",
            "政策已更新：国内出差住宿报销上限为每人每晚 400 元，超出须事前取得经理书面批准。",
            "SD-120 的 429 分钟测算把等待时长也算成了节省，不能直接当作人力节省。",
            "人工兜底已经落实：陈敏每天安排 45 分钟值班接单。",
            "第 3 天由我和技术负责人复核检索错误与转人工记录；错误边界清楚后再向经理建议扩大范围。",
        ],
        "fix": "人工兜底尚未落实：陈敏的 45 分钟只用于查看试用记录，不等于有人值班；上线前需要她确认值班人员与服务时段。",
        "title": "首批试点方案",
    },
    ("it_ticket_pilot", "zh"): {
        "tests": ["账号密码忘了怎么重置？", "P2工单的响应时限是多少？", "火星天气如何？"],
        "policy": "P2工单的响应时限是多少？",
        "asks": [
            ("tech_lead", "试点最多能上多少人？"),
            ("business_lead", "SD-120 里的 429 分钟能直接算成节省的服务台人力吗？"),
            ("supervisor", "如果首批只开 20 人，还需要先申请资源吗？"),
        ],
        "work": [
            "建议首批只开放给新员工组的 20 人，先验证 VPN、账号、打印机等入口指引类问题；SLA 时限类问题暂不自动回答，转人工核验。",
            "目前项目预留容量是 30 人，可用开发资源 3 人日，正式试点期限为第 7 天；20 人在容量以内，不需要申请扩容。",
            "SLA 已更新：P2 工单响应时限为 2 小时，超时须由业务负责人记录原因并通知提单人。",
            "SD-120 的 429 分钟测算把等待时长也算成了节省，不能直接当作服务台人力节省。",
            "人工兜底已经落实：陈敏每天安排 45 分钟值班接单。",
            "第 3 天由我和技术负责人复核检索错误与转人工记录；错误边界清楚后再向经理建议扩大范围。",
        ],
        "fix": "人工兜底尚未落实：陈敏的 45 分钟只用于查看试用记录，不等于有人值班；上线前需要她确认值班人员与服务时段。",
        "title": "首批试点方案",
    },
    ("pm_pilot", "en"): {
        "tests": [
            "How do I reset my account password?",
            "What is the hotel reimbursement limit?",
            "What is the weather on Mars?",
        ],
        "policy": "What is the hotel reimbursement limit?",
        "asks": [
            ("tech_lead", "How many people can the pilot take at most?"),
            ("business_lead", "Can the 429 minutes in SD-120 be counted directly as labor saved?"),
            ("supervisor", "If the first wave is only 20 people, do I still need to request resources?"),
        ],
        "work": [
            "Open the first wave to the 20 new hires only and validate entry-point questions first; dynamic policy questions are not answered automatically and go to a person.",
            "The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7; 20 people fit the capacity, so no capacity request is needed.",
            "The policy has been updated: the domestic hotel reimbursement cap is CNY 400 per person per night, and costs above it need prior written manager approval.",
            "The 429-minute estimate in SD-120 counts waiting time as savings, so it cannot be treated as labor saved.",
            "Human fallback is in place: Chen Min staffs a 45-minute duty slot every day.",
            "On day 3 the technical lead and I review retrieval errors and handoff records; once the error boundary is clear we recommend widening the scope to the manager.",
        ],
        "fix": "Human fallback is not in place yet: Chen Min's 45 minutes are for reviewing trial records, not a duty slot; before launch she needs to confirm staffing and service hours.",
        "title": "First-wave pilot plan",
    },
    ("it_ticket_pilot", "en"): {
        "tests": [
            "How do I reset my account password?",
            "What is the P2 ticket response time?",
            "What is the weather on Mars?",
        ],
        "policy": "What is the P2 ticket response time?",
        "asks": [
            ("tech_lead", "How many people can the pilot take at most?"),
            ("business_lead", "Can the 429 minutes in SD-120 be counted directly as service-desk labor saved?"),
            ("supervisor", "If the first wave is only 20 people, do I still need to request resources?"),
        ],
        "work": [
            "Open the first wave to the 20 new hires only and validate entry-point questions such as VPN, accounts and printers first; SLA time-limit questions are not answered automatically and go to a person.",
            "The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7; 20 people fit the capacity, so no capacity request is needed.",
            "The SLA has been updated: P2 tickets must receive a response within 2 hours, and the business lead records the reason when the limit is missed.",
            "The 429-minute estimate in SD-120 counts waiting time as savings, so it cannot be treated as service-desk labor saved.",
            "Human fallback is in place: Chen Min staffs a 45-minute duty slot every day.",
            "On day 3 the technical lead and I review retrieval errors and handoff records; once the error boundary is clear we recommend widening the scope to the manager.",
        ],
        "fix": "Human fallback is not in place yet: Chen Min's 45 minutes are for reviewing trial records, not a duty slot; before launch she needs to confirm staffing and service hours.",
        "title": "First-wave pilot plan",
    },
}


def config_version(s: Session) -> int:
    body = s.get("timeline")
    while isinstance(body.get("result"), dict):
        body = body["result"]
    return body["workspace"]["config"]["config_version"]


def config_ref(s: Session) -> dict | None:
    """The applied configuration the submission is bound to, exactly as the workbench picks it
    (rules check capacity, resources and tests against it)."""
    body = s.get("timeline")
    while isinstance(body.get("result"), dict):
        body = body["result"]
    cfg = body["workspace"]["config"]
    for row in body.get("objects", []):
        ref = row["ref"]
        if (
            ref["kind"] == "config"
            and ref["object_id"] == cfg["id"]
            and ref["version"] == cfg["version"]
            and ref.get("config_version") == cfg["config_version"]
        ):
            return ref
    return None


def submit(s: Session, product: dict) -> dict:
    payload = {"decision": "launch_narrow", "products": [product]}
    ref = config_ref(s)
    if ref is not None:
        payload["config"] = ref
    return s.send("submissions", "submissions.create", payload)


def configure(s: Session, **settings) -> None:
    body = s.get("timeline")
    while isinstance(body.get("result"), dict):
        body = body["result"]
    config = body["workspace"]["config"]
    base = {
        "schema_version": 2,
        "session_id": s.session_id,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    s.send("configuration", "configuration.apply", {"base": base, "settings": settings})


def test(s: Session, query: str) -> None:
    result = s.test(query, config_version=config_version(s))["result"]["test"]
    recs = result.get("recognition") or (result.get("data") or {}).get("recognition") or []
    tags = ", ".join(f"{r['task']}={r['label']}" for r in recs)
    print(f"  test {query[:24]!r}: {result.get('status')} [{tags}]")


def play(
    api: str,
    scenario: str,
    language: str,
    revise: bool,
    clean: bool = True,
    draft_only: bool = False,
) -> tuple[str, str | None]:
    text = TEXT[(scenario, language)]
    s = Session(api, language, scenario=scenario + "_v2")
    print(scenario, language, "session", s.session_id)
    fragments = {}
    for material in READS:
        fragments[material] = s.read(material)["result"]["fragments"]
    for query in text["tests"]:
        test(s, query)
    for role, question in text["asks"]:
        asked = s.ask(role, question)
        restored = s.wait_request(asked["_request_id"], timeout=300)
        statuses = [j["status"] for j in restored.get("jobs") or []]
        print(f"  ask {role}: {statuses}")
        if clean and statuses != ["completed"]:
            # A withheld colleague reply (the LLM help review is nondeterministic) would show
            # as a failed bubble; a demo recording starts over instead.
            print("  colleague reply withheld; abandoning this session")
            s.close()
            return s.session_id, None
    configure(s, participants=20)  # the first applied plan publishes the policy update
    test(s, text["policy"])
    s.send("actions", "refresh_index", {"tool": "refresh_index"})
    test(s, text["policy"])
    updated = s.read("policy", 2)["result"]["fragments"]
    refs = [fragments["brief"][1]["ref"], updated[0]["ref"]]
    product = s.draft("\n\n".join(text["work"]), refs, title=text["title"])
    if draft_only:
        # Left before submission: opening the submit panel shows the sentence-coloured
        # pre-submission preview live.
        print("  draft saved, not submitted")
        issued = s.http.post(s.path("continue-code"), headers=s.headers, json={"expected_generation": 0})
        code = (issued.json().get("result") or {}).get("code") if issued.status_code == 200 else None
        print("  continue code:", code)
        s.close()
        return s.session_id, code
    submitted = submit(s, product)
    restored = s.wait_request(submitted["_request_id"], timeout=900)
    print("  submit:", [j["status"] for j in restored.get("jobs") or []])
    if revise:
        parent = submitted["result"]["submission"]
        reason = "根据反馈修订人工兜底" if language == "zh" else "Fix the human-fallback claim"
        s.send("revision-cycles", "begin_revision", {"parent_submission": parent, "reason": reason})
        work = [text["fix"] if i == 4 else line for i, line in enumerate(text["work"])]
        product = s.draft("\n\n".join(work), refs, title=text["title"] + " v2")
        submitted = submit(s, product)
        restored = s.wait_request(submitted["_request_id"], timeout=900)
        print("  resubmit:", [j["status"] for j in restored.get("jobs") or []])
    issued = s.http.post(s.path("continue-code"), headers=s.headers, json={"expected_generation": 0})
    code = (issued.json().get("result") or {}).get("code") if issued.status_code == 200 else None
    print("  continue code:", code)
    s.close()
    return s.session_id, code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--scenario", default="pm_pilot", choices=["pm_pilot", "it_ticket_pilot"])
    parser.add_argument("--language", default="zh", choices=["zh", "en"])
    parser.add_argument("--revise", action="store_true")
    parser.add_argument("--tries", type=int, default=3, help="start over when a colleague reply is withheld")
    parser.add_argument("--draft-only", action="store_true", help="stop before submitting")
    args = parser.parse_args(argv)
    for _ in range(args.tries):
        _, code = play(
            args.api,
            args.scenario,
            args.language,
            args.revise,
            clean=args.tries > 1,
            draft_only=args.draft_only,
        )
        if code is not None:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
