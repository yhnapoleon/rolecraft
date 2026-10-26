"""JUDGE entry (N1, N2): recognizers run before the semantic Judge and arbitrate after it.

``RecognitionFeedback`` wraps the feedback engine of one job:

1. the R2.support work is cut into the product's own sentence units; each sentence gets
   its C2 top-5 evidence units, a C1 relation judgement (rule fallback without weights)
   and a C6 cost-sensitive decision;
2. a compact recognition summary (labels, confidences, sentence indices, evidence ids,
   scope tests, behaviour) is written into every package's ``rule_context`` and reaches
   the Judge through the ``model_input`` allowlist;
3. the Judge runs as before; its support check is ``RecognizerSupportVerifier``;
4. for R2.support the Judge label is compared with the recognizers' aggregate and the
   more conservative one inside the rule bound is kept (arbiter);
5. every record is attached to ``FeedbackV2.recognition``.

The Judge prompt revision recorded here is ``grounded-feedback-bilingual-v2+recognition``;
the release ``PROMPT_VERSION`` stays v1 because installed scenario releases pin it.
"""

from __future__ import annotations

import re
from typing import Any

from career_lab.contracts.v2.core import canonical, digest
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.recognition import decision, relation
from career_lab.recognition.base import FALLBACK_REVISION, record, stopwatch

PROMPT_REVISION = "grounded-feedback-bilingual-v2+recognition"
CONFIDENCE_FLOOR = 0.6
SUMMARY_BYTES = 8000
ORDER = {"NOT_MET": 0, "PARTIAL": 1, "MET": 2}

GUIDE = {
    "zh": (
        "输入的 recognition 字段是识别器对作品逐句的关系判定（标签、置信度、句索引、证据 id）"
        "以及范围检测和行为轨迹的结果。先读识别结果：标签在规则界内时以识别结果为主要依据；"
        "只有识别结果缺失、置信度低于 0.6 或与规则事实冲突时才自行判断。explanation 开头必须写"
        "[识别一致]、[识别缺失] 或 [与识别不一致：原因] 之一。citation_ids 优先引用识别器标出的"
        " evidence_ids。"
    ),
    "en": (
        "The recognition field holds the recognizers' sentence-by-sentence relation judgements "
        "on the work (label, confidence, sentence index, evidence ids) plus scope-check and "
        "behaviour results. Read them first: within the rule bound, use them as the main basis; "
        "judge on your own only when they are missing, below 0.6 confidence, or conflict with "
        "rule facts. Start the explanation with exactly one of [recognition agrees], "
        "[recognition missing] or [disagrees with recognition: reason]. Prefer the "
        "evidence_ids the recognizers selected in citation_ids."
    ),
}


def judge_guide(language: str) -> str:
    return GUIDE.get(language, GUIDE["zh"])


# ---- sentence-level analysis ----------------------------------------------------------


def _subject_keys(package: EvidencePackageV2) -> set[str]:
    from career_lab.contracts.v2.core import ObjectRef

    return {
        canonical(r.model_dump(mode="json", include=set(ObjectRef.model_fields)))
        for r in package.subjects
    }


def analyze_support(package: EvidencePackageV2, language: str) -> dict[str, Any]:
    from career_lab.contracts.v2.core import ObjectRef
    from career_lab.models.v3.units import support_units

    subjects = _subject_keys(package)
    candidates = [
        (c.id, c.text, c.ref.observed_at_seq, c.ref.valid_from_seq, c.ref.valid_until_seq)
        for c in package.candidate_evidence
        if canonical(c.ref.model_dump(mode="json", include=set(ObjectRef.model_fields)))
        not in subjects
    ]
    plan = support_units(package)
    rows = []
    fallback = True
    revision = FALLBACK_REVISION
    recognizer = relation.RULE_ID
    with stopwatch() as clock:
        for unit in plan.units:
            found = relation.judge(
                unit.text, candidates, language=language, as_of=package.as_of.business_seq
            )
            fallback = fallback and found.fallback
            revision, recognizer = found.revision, found.recognizer_id
            choice = decision.decide(found.probabilities)
            rows.append(
                {
                    "index": unit.index,
                    "quote": unit.text,
                    "unit_hash": unit.unit_hash,
                    "label": found.label,
                    "confidence": round(found.confidence, 3),
                    "probabilities": {k: round(v, 3) for k, v in found.probabilities.items()},
                    "evidence_ids": list(found.evidence_ids),
                    "reason": found.reason,
                    "decision": choice.action,
                    "expected_cost": round(choice.expected_cost, 3),
                    "top": [dict(t) for t in found.top[:3]],
                    "branches": found.branches,
                }
            )
    decided = [r for r in rows if r["decision"] == "decide"]
    counts = {
        "supported": sum(r["label"] == "supported" for r in decided),
        "contradicted": sum(r["label"] == "contradicted" for r in decided),
        "insufficient": sum(r["label"] == "insufficient" for r in decided),
        "deferred": sum(r["decision"] == "defer" for r in rows),
    }
    deferred = sorted(
        (r for r in rows if r["decision"] == "defer"), key=lambda r: -r["expected_cost"]
    )
    return {
        "rows": rows,
        "counts": counts,
        "aggregate": relation.criterion_label(counts),
        "recognizer": f"{recognizer}@{revision[:12]}",
        "recognizer_id": recognizer,
        "revision": revision,
        "fallback": fallback,
        "duration_ms": clock.ms,
        "deferred_queue": [r["index"] for r in deferred],
        "candidates": len(candidates),
    }


_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+")


def _closest_sentence(claim: str, text: str) -> str:
    """The sentence of an evidence unit closest to the claim: first by the quantities the two
    share (a claim about 80 people lands on the sentence that says 80 people), then by
    character bigrams (a unit can be a whole short material; the writing area shows one
    sentence)."""

    def grams(s: str) -> set[str]:
        s = _NOISE.sub("", s.lower())
        return {s[i : i + 2] for i in range(len(s) - 1)}

    want, numbers = grams(claim), relation.quantities(claim)
    parts = [p.strip(" #*-\t") for p in _SENTENCE_END.split(text) if p and p.strip(" #*-\t")]
    best = max(
        parts or [text],
        key=lambda p: (
            len(numbers & relation.quantities(p)) if numbers else 0,
            len(want & grams(p)),
        ),
    )
    return best[:160]


def preview(packages, language: str) -> dict[str, Any] | None:
    """Sentence colouring for the pre-submission preview: the same C2 + C1 + C6 pass the
    feedback worker runs on R2.support, cut down to what the writing area shows."""
    support = next((p for p in packages if p.criterion == "R2.support"), None)
    if support is None:
        return None
    # The preview is re-requested whenever the chosen versions or decision change; the same
    # package (same input hash) gives the same labels, so reuse them.
    cached = _PREVIEWS.get((support.input_hash, language))
    if cached is not None:
        return cached
    result = _preview(support, language)
    if len(_PREVIEWS) >= 64:
        _PREVIEWS.pop(next(iter(_PREVIEWS)))
    _PREVIEWS[(support.input_hash, language)] = result
    return result


_PREVIEWS: dict[tuple[str, str], dict[str, Any]] = {}


def _preview(support: EvidencePackageV2, language: str) -> dict[str, Any]:
    analysis = analyze_support(support, language)
    texts = {c.id: c.text for c in support.candidate_evidence}
    units = []
    for row in analysis["rows"]:
        ids = [e for e in row["evidence_ids"] if e in texts] or [
            t["evidence_id"] for t in row["top"][:1] if t["evidence_id"] in texts
        ]
        units.append(
            {
                "index": row["index"],
                "quote": row["quote"],
                "label": row["label"],
                "confidence": row["confidence"],
                "decision": row["decision"],
                "evidence": _closest_sentence(row["quote"], texts[ids[0]]) if ids else None,
            }
        )
    return {
        "recognizer": analysis["recognizer"],
        "fallback": analysis["fallback"],
        "counts": analysis["counts"],
        "aggregate": analysis["aggregate"],
        "duration_ms": analysis["duration_ms"],
        "units": units,
    }


def scope_tests(package: EvidencePackageV2) -> list[dict[str, Any]]:
    """Scope-check results of the learner's tests, read from the package's test records."""
    found = []
    for test in package.rule_context.get("tests") or ():
        data = (test or {}).get("record") or {}
        for item in data.get("recognition") or ():
            if item.get("task") == "scope":
                found.append(
                    {
                        "query": str(data.get("query", ""))[:80],
                        "scope": item.get("label"),
                        "score": item.get("score"),
                    }
                )
    return found[-6:]


def summary(analysis: dict | None, tests: list, behaviour: dict | None) -> dict[str, Any]:
    body: dict[str, Any] = {"prompt_revision": PROMPT_REVISION}
    if analysis is not None:
        body["recognizer"] = analysis["recognizer"]
        body["counts"] = analysis["counts"]
        rows = [
            {
                "index": r["index"],
                "quote": r["quote"][:120],
                "label": r["label"],
                "confidence": r["confidence"],
                "evidence_ids": r["evidence_ids"],
                "decision": r["decision"],
            }
            for r in analysis["rows"]
        ]
        # Over budget, drop the least confident sentences first (they say the least).
        while rows and len(canonical(rows).encode()) > SUMMARY_BYTES:
            rows.remove(min(rows, key=lambda r: r["confidence"]))
        body["relation_units"] = sorted(rows, key=lambda r: r["index"])
    if tests:
        body["scope_tests"] = tests
    if behaviour:
        body["behavior"] = behaviour
    return body


def with_recognition(package: EvidencePackageV2, body: dict[str, Any]) -> EvidencePackageV2:
    raw = package.model_dump(mode="json", exclude={"input_hash"})
    raw["rule_context"] = {**raw["rule_context"], "recognition": body}
    return EvidencePackageV2.model_validate(raw | {"input_hash": digest(raw)})


# ---- support verification (SUPPORT slot) ----------------------------------------------

_QUOTES = re.compile(r"[“「『\"]([^”」』\"]{4,})[”」』\"]")
_SPLIT = re.compile(r"……|\.\.\.|…")
_NOISE = re.compile(r"[\s，,。．.；;：:！!？?、（）()【】\[\]《》“”\"'‘’]")


def _norm(text: str) -> str:
    return _NOISE.sub("", text).casefold()


class RecognizerSupportVerifier:
    """Support check by recognizers first, the LLM verifier only when they cannot decide.

    Quoted spans in the Judge's explanation must occur in the fixed input (rule
    grounding); numeric sentences of the explanation are checked against the cited
    evidence with C1 (rule fallback). Grounded quotes with no contradiction give
    ``supported``; a confident contradiction gives ``unsupported`` only with C1 weights;
    everything else is delegated to the configured LLM verifier.
    """

    def __init__(self, llm=None, records: list | None = None):
        self.llm = llm
        self.records = records if records is not None else []

    @property
    def revision(self):
        base = getattr(self.llm, "revision", "unavailable")
        return f"recognizer+{base}"

    def __call__(self, package, advice):
        return self.verify(package, advice).verdict

    def verify(self, package, advice, *, work_language="zh"):
        from career_lab.rubrics.v4.support import SupportResult

        with stopwatch() as clock:
            texts = {c.id: c.text for c in package.candidate_evidence}
            by_ref = {canonical(c.ref): c.id for c in package.candidate_evidence}
            cited = [by_ref.get(canonical(ref)) for ref in advice.citations]
            cited_pairs = [(cid, texts[cid]) for cid in cited if cid]
            pool = _norm("".join(texts.values()))
            quotes = [
                piece
                for match in _QUOTES.findall(advice.explanation or "")
                for piece in _SPLIT.split(match)
                if len(_norm(piece)) >= 4
            ]
            grounded = sum(_norm(q) in pool for q in quotes)
            contradictions = []
            model = relation.encoder_relation()
            # Explanation sentences are critiques ("plans 50 but capacity is 30"), so the
            # numeric rule would misread them; only a trained C1 checks them for conflict.
            for sentence in re.split(r"(?<=[。；;.!?！？])", advice.explanation or ""):
                if model is None or not relation.quantities(sentence) or not cited_pairs:
                    continue
                found = relation.judge(sentence, cited_pairs, language=work_language, k=3)
                if found.label == "contradicted":
                    contradictions.append(
                        {"sentence": sentence[:120], "confidence": round(found.confidence, 3)}
                    )
            # The recognizers may only clear a citation (every quote found in the input);
            # they never veto: Judge explanations are critiques, so a "contradiction"
            # between an explanation sentence and its evidence is usually the point made.
            verdict, status, delegated = None, "recognizer", False
            if quotes and grounded == len(quotes) and cited_pairs:
                verdict = "supported"
            if verdict is None:
                delegated = self.llm is not None
                if self.llm is not None:
                    checked = self.llm.verify(package, advice, work_language=work_language)
                    verdict, status = checked.verdict, "delegated_" + checked.status
                else:
                    verdict, status = "unverified", "recognizer_undecided"
        self.records.append(
            record(
                "support-check-v1",
                FALLBACK_REVISION if model is None else "xlm-r-pair-v1",
                "relation",
                {"criterion": advice.criterion, "explanation": advice.explanation},
                label=verdict,
                outputs={
                    "criterion": advice.criterion,
                    "mode": "support_check",
                    "quotes": len(quotes),
                    "quotes_grounded": grounded,
                    "contradictions": contradictions,
                    "delegated_to_llm": delegated,
                    "proposed_label": advice.label,
                },
                duration_ms=clock.ms,
                fallback=model is None,
            )
        )
        return SupportResult(verdict, status, self.revision)


# ---- the wrapper ---------------------------------------------------------------------


def _criterion_label_from_judge(item) -> str | None:
    return item.label if item.label in ORDER else None


class RecognitionFeedback:
    def __init__(self, inner, *, view=None, auth=None, verifier=None, language="zh"):
        self.inner = inner
        self.view, self.auth = view, auth
        self.verifier = verifier
        self.language = language

    @property
    def dependencies(self):
        return getattr(self.inner, "dependencies", {})

    def _behaviour(self) -> dict | None:
        if self.view is None or self.auth is None:
            return None
        try:
            from career_lab.recognition.behavior import analyze

            result = analyze(self.view, self.auth, language=self.language)
        except Exception:  # noqa: BLE001
            return None
        return {
            "strategy_nearest": (result["strategy"] or {}).get("nearest"),
            "phase_sequence": [p["name"] for p in result["phases"]],
            "anomalies": [a["rule"] for a in result["anomalies"]],
            "window": result.get("window"),
            "steps": len(result["sequence"]),
            "record": result["record"],
        }

    def evaluate(
        self,
        session_id,
        subject,
        evaluation,
        as_of,
        packages,
        expected_model_revision=None,
        *,
        work_language="zh",
    ):
        support = next((p for p in packages if p.criterion == "R2.support"), None)
        analysis = analyze_support(support, work_language) if support is not None else None
        tests = scope_tests(packages[0]) if packages else []
        behaviour = self._behaviour()
        body = summary(
            analysis, tests, {k: v for k, v in (behaviour or {}).items() if k != "record"}
        )
        packages = tuple(with_recognition(p, body) for p in packages)
        report, diagnostics = self.inner.evaluate(
            session_id,
            subject,
            evaluation,
            as_of,
            packages,
            expected_model_revision,
            work_language=work_language,
        )
        records = []
        if analysis is not None:
            records.extend(self._analysis_records(analysis, as_of))
            report, arbiter = self._arbitrate(report, support, analysis, as_of)
            if arbiter is not None:
                records.append(arbiter)
        if self.verifier is not None:
            records.extend(r.model_copy(update={"as_of": as_of}) for r in self.verifier.records)
        if behaviour and behaviour.get("record"):
            from career_lab.contracts.v2.recognition import RecognitionRecord

            records.append(
                RecognitionRecord.model_validate(behaviour["record"]).model_copy(
                    update={"as_of": as_of}
                )
            )
        existing = tuple(report.recognition or ())
        return report.model_copy(update={"recognition": existing + tuple(records)}), diagnostics

    def _analysis_records(self, analysis, as_of):
        rows = analysis["rows"]
        relation_record = record(
            analysis["recognizer_id"],
            analysis["revision"],
            "relation",
            {"units": [r["unit_hash"] for r in rows]},
            label=analysis["aggregate"],
            outputs={
                "criterion": None,
                "units": [
                    {
                        k: r[k]
                        for k in (
                            "index",
                            "quote",
                            "label",
                            "confidence",
                            "probabilities",
                            "evidence_ids",
                            "reason",
                            "decision",
                            "expected_cost",
                            "branches",
                        )
                    }
                    for r in rows
                ],
                "counts": analysis["counts"],
                "candidates": analysis["candidates"],
            },
            as_of=as_of,
            duration_ms=analysis["duration_ms"],
            fallback=analysis["fallback"],
        )
        retrieval_record = record(
            "retrieval-c2",
            "rrf",
            "retrieval",
            {"units": [r["unit_hash"] for r in rows]},
            label=None,
            outputs={
                "per_sentence_top": [{"index": r["index"], "top": r["top"]} for r in rows],
                "k": relation.TOP_K,
                "candidates": analysis["candidates"],
            },
            as_of=as_of,
        )
        lift = decision.lift()
        decision_record = record(
            "cost-decision-v1",
            "costs.json",
            "decision",
            {"units": [r["unit_hash"] for r in rows]},
            label=f"deferred:{analysis['counts']['deferred']}",
            outputs={
                "deferred": analysis["counts"]["deferred"],
                "queue": analysis["deferred_queue"],
                "costs": decision.costs(),
                "lift": lift,
            },
            as_of=as_of,
            fallback=analysis["fallback"],
        )
        return [relation_record, retrieval_record, decision_record]

    def _arbitrate(self, report, package, analysis, as_of):
        recognized = analysis["aggregate"]
        items = list(report.items)
        index = next((i for i, item in enumerate(items) if item.criterion == "R2.support"), None)
        if index is None or recognized is None:
            return report, None
        item = items[index]
        judged = _criterion_label_from_judge(item) if item.source == "model_advice" else None
        if judged is None:
            return report, record(
                "arbiter-v1",
                PROMPT_REVISION,
                "arbiter",
                {"judge": item.label, "recognizer": recognized},
                label="judge_undecided",
                outputs={
                    "criterion": "R2.support",
                    "agreement": False,
                    "judge_label": item.label,
                    "recognizer_label": recognized,
                    "final": item.label,
                },
                as_of=as_of,
                fallback=analysis["fallback"],
            )
        bound = item.rule_bound or package.rule_bound
        lower = ORDER[bound.lower] if bound else 0
        upper = ORDER[bound.upper] if bound else 2
        agreement = judged == recognized
        final = judged
        if not agreement:
            candidate = min(ORDER[judged], ORDER[recognized])
            candidate = max(lower, min(upper, candidate))
            final = next(k for k, v in ORDER.items() if v == candidate)
            note = (
                f"仲裁：识别器 {recognized} / 评审 {judged}，取保守 {final}。"
                if self.language != "en"
                else f"Arbiter: recognizer {recognized} / reviewer {judged}; "
                f"kept the conservative {final}. "
            )
            items[index] = item.model_copy(
                update={"label": final, "explanation": note + item.explanation}
            )
            report = report.model_copy(update={"items": tuple(items)})
        return report, record(
            "arbiter-v1",
            PROMPT_REVISION,
            "arbiter",
            {"judge": judged, "recognizer": recognized},
            label="agree" if agreement else "conservative",
            outputs={
                "criterion": "R2.support",
                "agreement": agreement,
                "judge_label": judged,
                "recognizer_label": recognized,
                "final": final,
            },
            as_of=as_of,
            fallback=analysis["fallback"],
        )
