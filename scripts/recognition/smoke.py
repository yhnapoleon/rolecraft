"""End-to-end smoke check against a running API + worker (S0 acceptance and later stages).

    uv run python -m scripts.recognition.smoke --language zh

Creates a session, reads the brief, writes a three-paragraph work product, runs one
assistant test, submits, waits for the feedback job and prints a compact summary of the
feedback items, the model advice and (from S1 on) the recognition records.
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.recognition.client import DEFAULT_API, Session

WORK = {
    "zh": (
        "试点先只开放给已完成人工复核的团队，有据可查。若名额超过上限，需要先申请扩容。\n\n"
        "政策规定住宿上限为每晚500元。超出部分必须事先取得书面批准。我们计划安排 50 人参加试点。\n\n"
        "- 保留人工兜底\n- 记录未知条件"
    ),
    "en": (
        "Open the pilot only to teams with completed human review, as documented. "
        "If seats exceed the limit, request capacity first.\n\n"
        "The policy caps hotels at CNY 500 per night. Any excess needs written approval in "
        "advance. We plan to put 50 people into the pilot.\n\n"
        "- Keep human fallback\n- Record unknown conditions"
    ),
}
QUERY = {"zh": "住宿报销上限是多少？", "en": "What is the hotel reimbursement limit?"}
ASK = {"zh": "试点最多能上多少人？", "en": "How many people can the pilot take at most?"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--language", default="zh", choices=["zh", "en"])
    parser.add_argument("--dump", help="write the raw feedback JSON here")
    parser.add_argument(
        "--continue-code", action="store_true", help="issue a continue code to open it in a browser"
    )
    args = parser.parse_args(argv)

    session = Session(args.api, args.language)
    print("session", session.session_id)
    read = session.read("brief")
    fragments = read["result"]["fragments"]
    product = session.draft(WORK[args.language], [fragments[min(1, len(fragments) - 1)]["ref"]])
    trial = session.test(QUERY[args.language])
    test = trial["result"]["test"]
    print("test:", test.get("status"), "|", (test.get("answer") or "")[:80])
    if "recognition" in (test.get("data") or {}) or "recognition" in test:
        print("test recognition:", json.dumps(test.get("recognition") or test["data"]["recognition"], ensure_ascii=False)[:400])
    asked = session.ask("tech_lead", ASK[args.language])
    session.wait_request(asked["_request_id"])
    for reply in session.objects("role_reply"):
        content = reply["content"]
        print("reply:", " ".join((content.get("text") or "")[:80].split()))
        for rec in content.get("recognition") or []:
            print("   ", rec["task"], rec["recognizer_id"], rec["label"], rec["score"], "fallback" if rec["fallback"] else "", rec["outputs"].get("grounded"), rec["outputs"].get("leaks"))
    submitted = session.submit([product])
    restored = session.wait_request(submitted["_request_id"])
    print("jobs:", [job["status"] for job in restored["jobs"]])
    submission_id = submitted["result"]["submission"]["object_id"]
    body = session.feedback(submission_id)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(body, handle, ensure_ascii=False, indent=2)
    report = body["result"]["result"]["items"][0]
    for item in report.get("items", []):
        print(
            f"  {item.get('criterion_id', item.get('criterion')):<22} "
            f"{str(item.get('label')):<14} {str(item.get('source', '')):<10} "
            f"{(item.get('explanation') or '')[:70]!r}"
        )
    for advice in report.get("model_advice", []):
        units = advice.get("units") or []
        print(
            f"  advice {advice.get('criterion')} status={advice.get('status')} units={len(units)}"
        )
        for unit in units[:8]:
            print(f"    [{unit.get('index')}] {unit.get('label')} {unit['subject']['quote'][:50]!r}")
    for rec in report.get("recognition") or []:
        out = rec["outputs"]
        print("  rec", rec["task"], rec["recognizer_id"], rec["label"], "fallback" if rec["fallback"] else "", out.get("criterion"), out.get("counts") or out.get("agreement") or out.get("deferred"))
        for unit in (out.get("units") or [])[:8]:
            print("      ", unit["index"], unit["label"], unit["confidence"], unit["decision"], unit["reason"], unit["quote"][:30])
    try:
        rec = session.get("recognition")
        print("GET /recognition counts:", rec["result"]["result"]["counts"])
    except Exception as error:  # noqa: BLE001 - route exists from S1 on
        print("GET /recognition:", type(error).__name__)
    behavior = session.get("behavior")["result"]["result"]
    print("GET /behavior sequence:", [row["symbol"] for row in behavior["sequence"]])
    print("  phases:", [(p["name"], p["from_seq"], p["to_seq"]) for p in behavior["phases"]])
    print("  anomalies:", behavior["anomalies"], "executor:", behavior["executor"])
    if args.continue_code:
        issued = session.http.post(
            session.path("continue-code"),
            headers=session.headers,
            json={"expected_generation": 0},
        )
        issued.raise_for_status()
        body = issued.json()
        print("continue code:", (body.get("result") or body).get("code"))
    session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
