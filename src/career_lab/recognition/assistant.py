"""ASSISTANT entry: C2 retrieval and C4 scope decide what the knowledge assistant sees.

Called from ``assistant/v2/service.py::Assistant.run`` only for the learner's own tests
(``recognize=True``); hidden probes and engineer replays keep the rule path so rule
evaluation is unchanged.

- C2: candidates that pass the product's coverage gate (``min_score`` keeps its meaning)
  are re-ranked by reciprocal rank fusion of BM25 and e5 cosine, so ``retrieval_limit``
  keeps the best units rather than the best token overlap.
- C4: the query is checked against the in-domain distribution of this scenario, language
  and ``scope_filter`` setting; out of scope gives ``outside_scope_ood`` before any
  retrieval verdict ("out of domain: do not look at retrieval").
"""

from __future__ import annotations

from career_lab.recognition import retrieval, scope
from career_lab.recognition.base import record, stopwatch

RETRIEVAL_ID = "retrieval-c2"
# E3: on paraphrased questions e5 alone beats RRF (Recall@5 zh 0.82 vs 0.65, en 0.79 vs
# 0.57; direct questions tie), so the assistant ranks by dense similarity.
METHOD = "dense"
TOP_K = 5
# e5 cosine -> [0, 1] per language: 0 at the median best match of near out-of-domain
# questions, 1 at the median of direct in-domain questions (assistant-queries-v1).
DENSE_ANCHORS = {"zh": (0.877, 0.935), "en": (0.811, 0.885)}


def dense_relevance(cosine: float | None, language: str) -> float:
    if cosine is None:
        return 0.0
    low, high = DENSE_ANCHORS.get(language, DENSE_ANCHORS["zh"])
    return max(0.0, min(1.0, (cosine - low) / (high - low)))


def scenario_id(package) -> str:
    bundle = getattr(package, "bundle", None)
    return str(getattr(bundle, "id", None) or "pm_pilot")


def rerank(
    query: str,
    candidates: list,
    scored: list,
    *,
    as_of=None,
    coverage: dict | None = None,
    min_score: float = 0.35,
    language: str = "zh",
    allow_dense: bool = True,
):
    """C2 scoring: relevance = max(token coverage, calibrated e5 similarity).

    ``min_score`` keeps its meaning (a relevance floor in [0, 1]); a candidate now passes
    when either its token coverage or its dense relevance reaches it, so paraphrased
    questions are no longer lost for lack of shared words. Returns the passing
    (relevance, candidate) pairs in C2 order and the retrieval record.
    """
    coverage = coverage or {}
    with stopwatch() as clock:
        texts = [c.text for c in candidates]
        hits, used, fallback = retrieval.search(query, texts, k=len(texts), method=METHOD)
    by_index = {h.index: h for h in hits}
    passing = []
    for i, candidate in enumerate(candidates):
        hit = by_index.get(i)
        dense = dense_relevance(hit.dense if hit else None, language) if allow_dense else 0.0
        relevance = max(coverage.get(candidate.id, 0.0), dense)
        if relevance >= min_score and (coverage.get(candidate.id, 0.0) > 0 or dense > 0):
            passing.append((relevance, candidate))
    if fallback or not allow_dense:
        passing = list(scored)
    rank = {candidates[h.index].id: h.rank for h in hits}
    passing.sort(key=lambda pair: (-pair[0], rank.get(pair[1].id, 10**6), pair[1].id))
    top = hits[:TOP_K]
    best = top[0] if top else None
    top_score = None
    if best is not None:
        top_score = best.dense if best.dense is not None else best.bm25
    return passing, record(
        RETRIEVAL_ID,
        "rule-fallback" if fallback else used,
        "retrieval",
        {"query": query, "candidates": [c.id for c in candidates]},
        label=candidates[best.index].material_id if best is not None else None,
        score=top_score,
        outputs={
            "method": used,
            "requested_method": METHOD,
            "top": [
                {
                    "rank": h.rank,
                    "material_id": candidates[h.index].material_id,
                    "domain": candidates[h.index].domain,
                    "chunk_id": candidates[h.index].id,
                    "quote": candidates[h.index].text[:120],
                    "bm25": h.bm25,
                    "dense": h.dense,
                    "coverage": coverage.get(candidates[h.index].id, 0.0),
                    "dense_relevance": dense_relevance(h.dense, language),
                    "passes_gate": candidates[h.index].id in {c.id for _, c in passing},
                }
                for h in top
            ],
            "gate": "max(coverage, dense_relevance)>=min_score",
            "min_score": min_score,
            "passing": len(passing),
            "passing_by_coverage_only": len(scored),
        },
        as_of=as_of,
        duration_ms=clock.ms,
        fallback=fallback,
    )


def narrowed(cfg) -> bool:
    """The learner narrowed scope: filtering is on and the policy domains are left out."""
    return bool(cfg.scope_filter) and not any(str(d).startswith("policy") for d in cfg.domains)


def scope_check(package, query: str, cfg, *, rule_hit: bool, as_of=None):
    return scope.detect(
        query,
        scenario=scenario_id(package),
        language=getattr(package, "locale", "zh"),
        scope_filter=narrowed(cfg),
        rule_hit=rule_hit,
        as_of=as_of,
    )


def drift_record(package, previous, current):
    """Drift between this test and an earlier one with the same query on another index."""
    return scope.drift(
        current.query,
        previous.answer,
        current.answer,
        scenario=scenario_id(package),
        language=getattr(package, "locale", "zh"),
        scope_filter=narrowed(current.config.effective),
        as_of=current.as_of,
    )


def with_drift(package, view, run):
    """Append a drift record when the same question was tested on another index version."""
    from dataclasses import replace

    from career_lab.contracts.v2.world import TestResultV2

    result = run.result
    if result.recognition is None or not result.answer:
        return run
    query = result.query.strip()
    earlier = []
    for stored in view.objects:
        if stored.ref.kind != "test":
            continue
        try:
            item = TestResultV2.model_validate(stored.content)
        except ValueError:
            continue
        if (
            item.query.strip() == query
            and item.answer
            and item.execution.used_versions != result.execution.used_versions
        ):
            earlier.append(item)
    if not earlier:
        return run
    previous = max(earlier, key=lambda item: item.as_of.business_seq)
    drift = drift_record(package, previous, result)
    drift = drift.model_copy(update={"outputs": {**drift.outputs, "previous_test_id": previous.id}})
    updated = result.model_copy(update={"recognition": (*result.recognition, drift)})
    return replace(run, result=updated)
