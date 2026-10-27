"""AI colleagues on the engineer path, by rule (phase 2, step 3). No model is called here.

A practice is played as one role. In a product manager's practice Daniel (technical lead) is
the AI engineering colleague: a hand-over ticket assigned to him is reproduced, tried, drafted
and signed by a rule-based orchestration of the ordinary engineer tools, and reviewed by the
same trusted review. In an engineer's practice Grace (manager) receives the learner's signed
report for the product side and decides by rule whether to apply it.

Everything a colleague does is labelled as that colleague (a ``system`` executor with its own
id, and an ``actor`` naming the person and the rule orchestration); nothing is recorded as
the learner's own action or signature.
"""

from dataclasses import dataclass, field
from typing import Any

from career_lab.contracts import v2 as C

DANIEL = C.Executor(id="colleague-tech-lead", kind="system")
GRACE = C.Executor(id="colleague-supervisor", kind="system")
DANIEL_ACTOR = {
    "role_id": "tech_lead",
    "name": "Daniel",
    "kind": "ai_colleague",
    "orchestration": "rule",
}
GRACE_ACTOR = {
    "role_id": "supervisor",
    "name": "Grace",
    "kind": "ai_colleague",
    "orchestration": "rule",
}
# Daniel tries at most this many candidates; with the sign-off it stays well inside the
# ticket's experiment budget and uses one of its three reviews.
MAX_TRIALS = 3


@dataclass(frozen=True)
class CandidateRule:
    """One candidate change Daniel may try, and why it fits the failure it is tried for."""

    id: str
    # The fact about the target tests this change answers (see ``facts_of``).
    when: str
    changes: dict[str, Any] = field(default_factory=dict)
    why: dict[str, str] = field(default_factory=dict)


# Tried in this order; the first that clears the targets' failure with no public probe failing
# wins, otherwise the one with the fewest failures. Narrow changes come before broad ones.
CANDIDATE_RULES: tuple[CandidateRule, ...] = (
    CandidateRule(
        "freshness_warn",
        "index_lag",
        {"freshness_guard": "warn"},
        {
            "zh": "目标问题引用的资料比源文件旧：索引落后时让回答带上提醒。"
            "只加提醒，不关掉任何能力。",
            "en": "The target answers cite an older version than the source: warn when the "
            "index lags. It only adds a warning and switches nothing off.",
        },
    ),
    CandidateRule(
        "realtime_index",
        "index_lag",
        {"update_strategy": "realtime"},
        {
            "zh": "索引按日更新跟不上政策变化：改成源文件一变就重建索引，从根上消掉落后。",
            "en": "A daily index cannot keep up with policy changes: rebuild it whenever a "
            "source changes, which removes the lag at its cause.",
        },
    ),
    CandidateRule(
        "freshness_fallback",
        "index_lag",
        {"freshness_guard": "fallback"},
        {
            "zh": "索引落后时直接转人工。最稳，但会把本来答得对的问题也转走，所以排在最后。",
            "en": "Hand over to a person whenever the index lags. Safest, but it also hands "
            "over questions that were answered correctly, so it is tried last.",
        },
    ),
    CandidateRule(
        "lower_min_score",
        "no_hit",
        {"min_score": 0.2},
        {
            "zh": "目标问题在资料里有答案却没检索到：把最低相关分从默认值降到 0.2。",
            "en": "The target questions have answers in the materials but nothing was "
            "retrieved: lower the minimum relevance score to 0.2.",
        },
    ),
)


def facts_of(targets: list[C.TestResultV2]) -> set[str]:
    """What the target tests show, from their own records: an index behind its source, or a
    question with no retrieval hit."""
    found: set[str] = set()
    for test in targets:
        execution = test.execution
        if any(
            execution.indexed_versions.get(key) != version
            for key, version in execution.source_versions.items()
        ):
            found.add("index_lag")
        if test.error_code == "no_retrieval_hit":
            found.add("no_hit")
    return found


def rules_for(facts: set[str]) -> list[CandidateRule]:
    return [rule for rule in CANDIDATE_RULES if rule.when in facts][:MAX_TRIALS]


# The failure a handed-over question showed, which a rule can check again in a trial: an answer
# citing an older version than its source with no warning, or nothing retrieved. Whether the
# answer's content is right needs an expectation, which a handed-over question does not carry.
STALE_UNWARNED = "stale_unwarned"
NO_HIT = "no_hit"


def failure_of(
    status: str | None,
    error_code: str | None,
    cited: list[tuple[str, int]],
    sources: dict[str, int],
) -> str | None:
    if status == "answered" and any(
        version < sources.get(object_id, version) for object_id, version in cited
    ):
        return STALE_UNWARNED
    if error_code == "no_retrieval_hit":
        return NO_HIT
    return None


def target_check(
    failing: dict[str, str], rows: list[dict[str, Any]], sources: dict[str, int]
) -> dict[str, Any] | None:
    """Whether a trial cleared the failure each handed-over question showed, by rule.

    ``failing`` maps a target question (as trial rows summarise it) to its failure. A row that
    could not run has not cleared anything. None when no target showed a rule-checkable failure.
    """
    checked = [row for row in rows if row["is_target"] and row["query"] in failing]
    if not checked:
        return None
    cleared = sum(
        row["result"] != "error"
        and failure_of(
            row["actual_status"],
            row["error_code"],
            [(c["object_id"], c["version"]) for c in row["citations"]],
            sources,
        )
        != failing[row["query"]]
        for row in checked
    )
    return {
        "failures": sorted({failing[row["query"]] for row in checked}),
        "questions": len(checked),
        "cleared": cleared,
    }


def cleared(trial: dict[str, Any]) -> bool:
    check = trial.get("target")
    return check is None or check["cleared"] == check["questions"]


def pick(tried: list[tuple[CandidateRule, dict[str, Any]]]) -> tuple[CandidateRule, dict[str, Any]]:
    """The first candidate that clears the targets' failure with no failure or error on the
    public probes; otherwise the one clearing the targets with the fewest, else the fewest."""

    def failures(t: tuple[CandidateRule, dict[str, Any]]) -> int:
        return t[1]["counts"]["failed"] + t[1]["counts"]["errors"]

    return min(tried, key=lambda t: (not cleared(t[1]), failures(t)))


# Grace's rule on a signed report: apply only a fix that the trusted review found to repair
# the targets (E1 MET) without a new failure (E2 MET), with the claimed results matching.
def grace_rule(evaluation: dict[str, Any], review_status: str) -> dict[str, Any]:
    by = {item["criterion"]: item for item in evaluation.get("criteria", [])}
    fixed, kept = by.get("E1.target_fixed", {}), by.get("E2.no_regressions", {})
    reasons, probes, hidden = [], [], 0
    if fixed.get("label") != "MET":
        reasons.append("target_not_fixed")
        probes += list(fixed.get("probe_ids", ()))
        hidden += int(fixed.get("hidden_probes", 0) or 0)
    if kept.get("label") != "MET":
        reasons.append("new_failures")
        probes += list(kept.get("probe_ids", ()))
        hidden += int(kept.get("hidden_probes", 0) or 0)
    if review_status != "verified":
        reasons.append("claims_not_verified")
    return {
        "result": "returned" if reasons else "applied",
        "reasons": reasons,
        "probe_ids": sorted(set(probes)),
        "hidden_probes": hidden,
    }


REASON_TEXT = {
    "zh": {
        "target_not_fixed": "目标问题还没修好",
        "new_failures": "改动让原本通过的检查失败了",
        "claims_not_verified": "报告里自报的结果和复核结果对不上",
        "config_moved": "报告基于的配置已经不是当前版本",
    },
    "en": {
        "target_not_fixed": "the target questions are not fixed yet",
        "new_failures": "the change made checks fail that passed before",
        "claims_not_verified": "the results claimed in the report do not match the review",
        "config_moved": "the report was built on a configuration that is no longer current",
    },
}


def grace_reply(language: str, decision: dict[str, Any]) -> str:
    """Grace's message, in the practice's work language, generated by rule from the decision."""
    if decision["result"] == "applied":
        before, after = decision.get("from_version"), decision.get("to_version")
        return (
            f"已由 Grace 应用，配置从 v{before} 变为 v{after}。复核显示目标修好、没有新增失败。"
            if language == "zh"
            else f"Applied by Grace: configuration v{before} → v{after}. The review shows the "
            "targets fixed and no new failures."
        )
    words = REASON_TEXT[language]
    parts = [words[r] for r in decision["reasons"] if r in words]
    probes = ", ".join(decision.get("probe_ids", ()))
    hidden = decision.get("hidden_probes", 0)
    detail = (
        (f"（公开检查 {probes}" if probes else "（")
        + (f"，另有 {hidden} 项隐藏检查" if hidden else "")
        + "）"
        if language == "zh"
        else (f" (public checks {probes}" if probes else " (")
        + (f"; {hidden} hidden checks" if hidden else "")
        + ")"
    )
    if detail in ("（）", " ()"):
        detail = ""
    return (
        "先不应用，退回给你：" + "；".join(parts) + detail + "。改好再签字交回。"
        if language == "zh"
        else "Not applied; back to you: " + "; ".join(parts) + detail + ". Sign it again "
        "when it is fixed."
    )


def credential(
    store: Any,
    owner: C.AuthContext,
    executor: C.Executor,
    capabilities: tuple[str, ...],
    actions: tuple[str, ...],
) -> C.AuthContext:
    """A short-lived credential for one colleague's run, limited to the operations it needs;
    revoke it right after (``golive.revoke``), as the go-live does with its own."""
    import secrets
    from uuid import uuid4

    context = C.AuthContext(
        session_id=owner.session_id,
        actor_id="learner",
        executor=executor,
        capabilities=capabilities,
        allowed_actions=actions,
        credential_id=uuid4().hex,
    )
    with store.db.transaction() as connection:
        store._credential(connection, context, secrets.token_urlsafe(32))
    return context
