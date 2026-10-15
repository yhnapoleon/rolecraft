"""The recorded business decisions as feedback states them: one sentence per request.

Resource names are the request panel's and the approval decision card's (名额／开发人日／截止日);
every word comes from the shared localization table. Only newly written feedback uses this:
stored feedback keeps the text it was written with.
"""

from career_lab.evidence.v2.localization import message

HEADING = "已记录的业务决定（规则核实）："
NAMES = {"capacity": "名额", "dev_days": "开发人日", "deadline_day": "截止日"}
# The amount asked and the amount decided; a deadline reads as a day.
AMOUNTS = {
    "requested": ("申请 {n}", "申请第 {n} 天"),
    "approved": ("已批准 {n}", "已批准第 {n} 天"),
    "accepted": ("已接受 {n}", "已接受第 {n} 天"),
    "countered": ("还价 {n}", "还价第 {n} 天"),
}
# A decision said once, after its terms, when it carries no amounts for them.
STATUSES = {
    "rejected": "未批准",
    "approved": "已批准",
    "accepted": "已接受",
    "countered": "还价待接受",
}
NO_TERMS = "一项申请（没有可读的条款）"


def latest_decisions(objects):
    """Each request's latest decision, in the order the requests were made.

    A request was made at the storage revision of its first recorded version; one whose record
    is not in the window falls back to its decision's revision. Object ids never decide order.
    """
    made, latest = {}, {}
    for row in objects:
        revision = row.created_storage_revision
        if row.ref.kind == "business_request":
            made[row.ref.object_id] = min(made.get(row.ref.object_id, revision), revision)
        elif row.ref.kind == "business_decision":
            request = row.content.get("request", {}).get("object_id")
            if request and (
                request not in latest or revision > latest[request].created_storage_revision
            ):
                latest[request] = row
    return sorted(
        latest.items(),
        key=lambda item: (made.get(item[0], item[1].created_storage_revision), item[0]),
    )


def decision_line(work_language, requested, status, result):
    """One request and its latest decision, e.g. "开发人日：申请 6 · 已批准 6".

    The decision is the whole request's. Approved, accepted or countered amounts stay with each
    term ("还价 60", and "，待接受" once at the end); a decision without amounts is said once,
    after all terms. A request without readable terms still gets its line.
    """

    def amount(kind, key, value):
        count, day = AMOUNTS[kind]
        return message(work_language, day if key == "deadline_day" else count, n=value)

    def term(key, decided):
        name = message(work_language, NAMES[key])
        asked = amount("requested", key, requested[key])
        if not decided:
            return message(work_language, "{name}：{asked}", name=name, asked=asked)
        outcome = amount(status, key, result[key])
        return message(
            work_language, "{name}：{asked} · {outcome}", name=name, asked=asked, outcome=outcome
        )

    keys = [key for key in sorted(requested) if key in NAMES]
    decided = bool(keys) and status in AMOUNTS and all(key in result for key in keys)
    terms = message(work_language, "、").join(term(key, decided) for key in keys)
    if decided:
        return (
            message(work_language, "{terms}，待接受", terms=terms)
            if status == "countered"
            else terms
        )
    return message(
        work_language,
        "{terms} · {status}",
        terms=terms or message(work_language, NO_TERMS),
        status=message(work_language, STATUSES.get(status, "待核验")),
    )


def recorded_decisions(work_language, decisions):
    """The heading on its own line, then each (requested, status, result) on one line."""
    return "\n".join(
        [
            message(work_language, HEADING),
            *(decision_line(work_language, *decision) for decision in decisions),
        ]
    )
