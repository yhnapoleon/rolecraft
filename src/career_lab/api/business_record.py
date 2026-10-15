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
    "countered": ("还价 {n}，待接受", "还价第 {n} 天，待接受"),
}
# A decision without an amount for the term.
STATUSES = {
    "rejected": "未批准",
    "approved": "已批准",
    "accepted": "已接受",
    "countered": "还价待接受",
}


def decision_line(work_language, requested, status, result):
    """One request and its latest decision, e.g. "开发人日：申请 6 · 已批准 6"."""

    def amount(kind, key, value):
        count, day = AMOUNTS[kind]
        return message(work_language, day if key == "deadline_day" else count, n=value)

    def outcome(key):
        if status in AMOUNTS and key in result:
            return amount(status, key, result[key])
        return message(work_language, STATUSES.get(status, "待核验"))

    return message(work_language, "、").join(
        message(
            work_language,
            "{name}：{asked} · {outcome}",
            name=message(work_language, NAMES[key]),
            asked=amount("requested", key, value),
            outcome=outcome(key),
        )
        for key, value in sorted(requested.items())
        if key in NAMES
    )


def recorded_decisions(work_language, decisions):
    """The heading on its own line, then each (requested, status, result) on one line."""
    return "\n".join(
        [
            message(work_language, HEADING),
            *(decision_line(work_language, *decision) for decision in decisions),
        ]
    )
