"""Whether the recognition layer is on, as the workbench needs to know it (demo edition).

The layer is on when ``CAREER_LAB_RECOGNIZERS`` names a recognizer root (a missing directory
still counts: every recognizer then uses its rule fallback); unset means off. The recognition
reads are served outside the frozen OpenAPI and their results are free JSON, so saying
``enabled`` there changes no public contract. Off, the behaviour read computes nothing.
"""

from __future__ import annotations

from dataclasses import replace


def recognition_enabled() -> bool:
    from career_lab.recognition import registry

    return registry.root() is not None


def signal_recognition_reads(registry) -> None:
    """Wrap the installed recognition and behaviour reads so each result says ``enabled``."""
    from career_lab.api.modules import V2Response

    recognition = registry.operations.get("recognition.read")
    behavior = registry.operations.get("behavior.read")
    if recognition is not None:
        inner_recognition = recognition.handler

        def recognition_read(view, payload, auth):
            response = inner_recognition(view, payload, auth)
            return V2Response(result={**response.result, "enabled": recognition_enabled()})

        registry.operations["recognition.read"] = replace(recognition, handler=recognition_read)
    if behavior is not None:
        inner_behavior = behavior.handler

        def behavior_read(view, payload, auth):
            if not recognition_enabled():
                return V2Response(result={"enabled": False})
            response = inner_behavior(view, payload, auth)
            return V2Response(result={**response.result, "enabled": True})

        registry.operations["behavior.read"] = replace(behavior, handler=behavior_read)


_SENTENCES: dict[tuple[str, str], dict] = {}


def _heading(text: str) -> str | None:
    """A material passage's own title: its first markdown heading, without the "#"."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:80] or None
        if line:
            return None
    return None


def sentence_preview(packages, language: str, title_of=None) -> dict | None:
    """The writing-area sentence labels with what the lens shows for each sentence: relation,
    probabilities, the recorded reason (fusion and rule numbers), the cost decision, the top
    retrieval hits and the matched material sentence with its material and version. The same
    C2 + C1 + C6 pass as ``recognition.judge.preview`` (read only, not changed here), cached by
    the support package's input hash so a repeated choice does not recompute. ``title_of`` names
    the material of an evidence reference; without it the passage's own heading is used."""
    from career_lab.recognition import decision
    from career_lab.recognition.judge import _closest_sentence, analyze_support

    support = next((p for p in packages if p.criterion == "R2.support"), None)
    if support is None:
        return None
    key = (support.input_hash, language)
    cached = _SENTENCES.get(key)
    if cached is not None:
        return cached
    analysis = analyze_support(support, language)
    candidates = {c.id: c for c in support.candidate_evidence}
    units = []
    for row in analysis["rows"]:
        ids = [e for e in row["evidence_ids"] if e in candidates] or [
            t["evidence_id"] for t in row["top"][:1] if t["evidence_id"] in candidates
        ]
        source = candidates[ids[0]] if ids else None
        units.append(
            {
                **{
                    k: row[k]
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
                    )
                },
                "evidence": _closest_sentence(row["quote"], source.text) if source else None,
                "source": {
                    "kind": source.ref.kind,
                    "object_id": source.ref.object_id,
                    "version": source.ref.version,
                    "title": (title_of(source.ref) if title_of else None) or _heading(source.text),
                }
                if source
                else None,
                "top": [
                    {
                        "rank": t["rank"],
                        "evidence_id": t["evidence_id"],
                        "quote": t["quote"],
                        "bm25": t.get("bm25"),
                        "dense": t.get("dense"),
                    }
                    for t in row["top"][:3]
                ],
            }
        )
    result = {
        "recognizer": analysis["recognizer"],
        "fallback": analysis["fallback"],
        "counts": analysis["counts"],
        "aggregate": analysis["aggregate"],
        "duration_ms": analysis["duration_ms"],
        "defer_cost": decision.costs().get("defer"),
        "units": units,
    }
    if len(_SENTENCES) >= 64:
        _SENTENCES.pop(next(iter(_SENTENCES)))
    _SENTENCES[key] = result
    return result
