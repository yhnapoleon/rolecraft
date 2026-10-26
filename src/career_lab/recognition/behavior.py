"""C5 behaviour trajectories: a session as a symbol sequence, its phases, strategy and anomalies.

Symbols come from public v2 events and role turns (see ``SYMBOLS`` in the design doc,
section 4.6): ``read:<material>``, ``ask:<role>:<intent>``, ``configure``,
``test:normal|policy|oos``, ``request:<kind>``, ``approved:*`` / ``denied:*``,
``refresh_index``, ``event:policy_updated``, ``submit``, ``revise``.

Models (``$CAREER_LAB_RECOGNIZERS/behavior-v1/``, fitted in ``experiments/recognition``):
``references.json`` (scripted strategy references for DTW 1-NN and the phase names),
``hmm.npz`` (categorical HMM: start, transition, emission, vocabulary). Without them the
phases follow a rule (read/ask = explore, configure/test = test, request/submit =
decide, after the first submission = adjust), strategy is unknown, and the record is
marked ``fallback``. The four anomaly rules always run.
"""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from typing import Any

import numpy as np

from career_lab.recognition import registry
from career_lab.recognition.base import FALLBACK_REVISION, record, stopwatch

ID = "behavior-v1"
PHASES = {"zh": ("探索", "测试", "决策", "调整"), "en": ("explore", "test", "decide", "adjust")}
KEY_MATERIALS = ("brief", "demand", "business_case", "technical", "approvals", "policy", "faq")


# ---- symbolisation --------------------------------------------------------------------


def _events(view, auth) -> list:
    from career_lab.contracts.v2.requests import ResourcePage

    reader = getattr(view, "public_history", None)
    if not callable(reader):
        return []
    found, cursor = [], 0
    while cursor < view.state.business_seq:
        page = reader(ResourcePage(since_seq=cursor, limit=100), auth)
        found.extend(page.events)
        if page.next_seq <= cursor:
            break
        cursor = page.next_seq
    return found


def _test_kind(view, refs) -> str:
    """normal / policy / oos by what the question is about, not by how the test ended."""
    from career_lab.contracts.v2.world import TestResultV2

    for ref in refs:
        if ref.kind != "test":
            continue
        for stored in view.objects:
            if stored.ref.kind == "test" and stored.ref.object_id == ref.object_id:
                try:
                    test = TestResultV2.model_validate(stored.content)
                except ValueError:
                    break
                if any(domain.startswith("policy") for domain in test.observed_coverage):
                    return "policy"
                for item in test.recognition or ():
                    if item.task == "scope" and item.label == "out" and not item.fallback:
                        return "oos"
                    if item.task == "retrieval":
                        top = (item.outputs.get("top") or [{}])[0]
                        if str(top.get("domain") or "").startswith("policy") and (
                            (top.get("dense") or 0) >= 0.88 or (top.get("bm25") or 0) >= 0.3
                        ):
                            return "policy"
                if test.error_code in {"outside_scope_ood", "no_retrieval_hit"}:
                    return "oos"
                return "normal"
    return "normal"


def _decision(data: dict) -> str:
    status = str(data.get("status") or "").casefold()
    if status.startswith(("reject", "deni", "declin")):
        return "denied"
    if status.startswith("counter"):
        return "counter"
    return "approved"


def symbols(view, auth) -> list[dict[str, Any]]:
    """The session's public behaviour as ordered symbols (events and role turns)."""
    from career_lab.recognition.intent import rule_intent

    rows: list[tuple[float, dict[str, Any]]] = []
    for event in _events(view, auth):
        kind = event.type
        data = dict(event.data or {})
        symbol = None
        if kind == "material_read":
            symbol = "read:" + str(data.get("material_id", "unknown"))
        elif kind == "config_applied":
            symbol = "configure"
        elif kind == "test_assistant":
            symbol = "test:" + _test_kind(view, event.refs)
        elif kind == "business_requested":
            requested = data.get("requested") or {}
            symbol = "request:" + ("capacity" if "capacity" in requested else "resources")
        elif kind == "business_decided":
            symbol = _decision(data) + ":decision"
        elif kind in {"resource_grant_committed", "business_counteroffer_accepted"}:
            symbol = "approved:" + ("grant" if kind.startswith("resource") else "counteroffer")
        elif kind == "index_refreshed":
            symbol = "refresh_index"
        elif kind == "submitted":
            symbol = "submit"
        elif kind == "revision_opened":
            symbol = "revise"
        elif kind not in {"initial_plan_applied", "test_assistant", "material_read"} and (
            "visible_to" not in event.model_fields or "learner" in event.visible_to
        ):
            # Scenario milestones (schedule change, scope request, policy notice, ...).
            symbol = "event:policy_updated" if "policy" in kind else "event:" + kind
        if symbol is None:
            continue
        rows.append(
            (
                float(event.seq),
                {
                    "seq": event.seq,
                    "symbol": symbol,
                    "executor": event.executor.kind,
                    "event_id": event.id,
                },
            )
        )
    for stored in view.objects:
        if stored.ref.kind != "role_turn":
            continue
        content = stored.content
        turn = content.get("input") or {}
        text = str(turn.get("text") or "")
        intent, _ = rule_intent(text)
        seq = int((content.get("as_of") or {}).get("business_seq") or 0)
        executor = (content.get("executor") or {}).get("kind", "human")
        rows.append(
            (
                seq + 0.5,
                {
                    "seq": seq,
                    "symbol": f"ask:{turn.get('role_id', 'unknown')}:{intent}",
                    "executor": executor,
                    "question": text[:80],
                },
            )
        )
    rows.sort(key=lambda row: row[0])
    return [row for _, row in rows]


# ---- phases, anomalies, strategy ------------------------------------------------------


def rule_phase(symbol: str, submitted: bool) -> int:
    if submitted and not symbol.startswith("submit"):
        return 3
    if symbol.startswith(("read:", "ask:")):
        return 0
    if symbol.startswith(("configure", "test:", "refresh_index")):
        return 1
    return 2


@lru_cache(maxsize=1)
def _model():
    entry = registry.get(ID)
    if entry is None:
        return None
    try:
        references = json.loads((entry.path / "references.json").read_text(encoding="utf-8"))
        hmm = dict(np.load(entry.path / "hmm.npz", allow_pickle=False))
        return references, hmm, entry.revision
    except Exception:  # noqa: BLE001 - a broken artifact falls back to rules
        return None


def hmm_phases(sequence: list[str], hmm: dict) -> list[int]:
    """Viterbi path over the categorical HMM; unknown symbols use a uniform emission."""
    vocabulary = [str(v) for v in hmm["vocabulary"]]
    index = {v: i for i, v in enumerate(vocabulary)}
    start, transition, emission = (
        np.log(hmm[k] + 1e-12) for k in ("start", "transition", "emission")
    )
    states = len(start)
    if not sequence:
        return []

    def emit(symbol):
        i = index.get(symbol)
        return emission[:, i] if i is not None else np.full(states, -np.log(len(vocabulary)))

    score = start + emit(sequence[0])
    back = []
    for symbol in sequence[1:]:
        candidates = score[:, None] + transition
        back.append(candidates.argmax(0))
        score = candidates.max(0) + emit(symbol)
    path = [int(score.argmax())]
    for pointers in reversed(back):
        path.append(int(pointers[path[-1]]))
    path.reverse()
    # state_order[s] is the phase index the state was named after (by its emissions).
    order = [int(v) for v in hmm.get("state_order", np.arange(states))]
    return [order[s] for s in path]


def substitution(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 0.5 if a.split(":")[0] == b.split(":")[0] else 1.0


def _dtw_matrix(a: list[str], b: list[str]) -> np.ndarray:
    n, m = len(a), len(b)
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i, j] = substitution(a[i - 1], b[j - 1]) + min(
                cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1]
            )
    return cost


def dtw(a: list[str], b: list[str]) -> float:
    return float(_dtw_matrix(a, b)[len(a), len(b)])


def dtw_path(a: list[str], b: list[str]) -> tuple[float, list[dict[str, Any]]]:
    """The DTW distance and its warping path, traced back through the cost matrix.

    Each step is ``{"i", "j", "cost"}``: ``a[i]`` was matched to ``b[j]`` at that
    substitution cost (0 same symbol, 0.5 same action on another object, 1 otherwise).
    The path is monotone from (0, 0) to (len(a) - 1, len(b) - 1); a repeated ``i`` means
    ``a`` did one thing where ``b`` did several, a repeated ``j`` the reverse. Ties prefer
    the diagonal, then the step along ``a``. Empty inputs give an empty path.
    """
    n, m = len(a), len(b)
    cost = _dtw_matrix(a, b)
    if n == 0 or m == 0:
        return float(cost[n, m]), []
    steps: list[dict[str, Any]] = []
    i, j = n, m
    while i > 0 and j > 0:
        steps.append({"i": i - 1, "j": j - 1, "cost": substitution(a[i - 1], b[j - 1])})
        _, i, j = min(
            (cost[i - 1, j - 1], i - 1, j - 1),
            (cost[i - 1, j], i - 1, j),
            (cost[i, j - 1], i, j - 1),
            key=lambda option: option[0],
        )
    steps.reverse()
    return float(cost[n, m]), steps


def alignment(sequence: list[str], reference: list[str]) -> dict[str, Any]:
    have, want = Counter(sequence), Counter(reference)
    missing = sorted((want - have).elements())
    extra = sorted((have - want).elements())
    swapped = []
    first = {s: i for i, s in reversed(list(enumerate(sequence)))}
    ref_first = {s: i for i, s in reversed(list(enumerate(reference)))}
    shared = [s for s in ref_first if s in first]
    for i, a in enumerate(shared):
        for b in shared[i + 1 :]:
            if (ref_first[a] < ref_first[b]) != (first[a] < first[b]):
                swapped.append([a, b] if first[a] < first[b] else [b, a])
    return {"missing": missing, "extra": extra, "swapped": swapped[:6]}


def anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    seq = [row["symbol"] for row in rows]
    # 1. The world changed (a notice or an index refresh) and the learner submitted
    #    without testing afterwards.
    for i, s in enumerate(seq):
        if s.startswith("event:") or s == "refresh_index":
            later = seq[i + 1 :]
            if "submit" in later and not any(
                x.startswith("test:") for x in later[: later.index("submit")]
            ):
                found.append(
                    {
                        "rule": "policy_update_untested_submit",
                        "score": 0.9,
                        "at_seq": rows[i]["seq"],
                    }
                )
                break
    # 2. Requested resources before reading the technical material.
    for i, s in enumerate(seq):
        if s.startswith("request:"):
            if "read:technical" not in seq[:i]:
                found.append(
                    {"rule": "request_before_technical", "score": 0.7, "at_seq": rows[i]["seq"]}
                )
            break
    # 3. Configured right after a request, before any approval came back.
    for i, s in enumerate(seq):
        if s.startswith("request:"):
            after = seq[i + 1 :]
            for j, x in enumerate(after):
                if x.startswith(("approved:", "denied:")):
                    break
                if x == "configure":
                    found.append(
                        {
                            "rule": "configured_before_approval",
                            "score": 0.75,
                            "at_seq": rows[i + 1 + j]["seq"],
                        }
                    )
                    break
            break
    # 4. Submitted twice with no configuration change in between.
    last_submit = None
    for i, s in enumerate(seq):
        if s == "configure":
            last_submit = None
        elif s == "submit":
            if last_submit is not None:
                found.append(
                    {"rule": "repeated_submit_same_config", "score": 0.6, "at_seq": rows[i]["seq"]}
                )
                break
            last_submit = i
    return found


def analyze(view, auth, *, language: str = "zh") -> dict[str, Any]:
    """The GET /behavior body: sequence, phases, strategy, alignment, anomalies, executor."""
    with stopwatch() as clock:
        rows = symbols(view, auth)
        sequence = [row["symbol"] for row in rows]
        loaded = _model()
        names = PHASES.get(language, PHASES["zh"])
        strategy = None
        aligned = {"missing": [], "extra": [], "swapped": []}
        if loaded is not None and sequence:
            references, hmm, revision = loaded
            names = tuple(references.get("phase_names", {}).get(language, names))
            path = hmm_phases(sequence, hmm)
            # Constraint: "adjust" exists only after a first submission; before it, a
            # state named adjust falls back to the rule phase of that symbol.
            submitted = False
            for i, symbol in enumerate(sequence):
                if path[i] == 3 and not submitted:
                    path[i] = rule_phase(symbol, False)
                submitted = submitted or symbol == "submit"
            ranked = sorted(
                (
                    (dtw(sequence, ref["sequence"]) / max(len(ref["sequence"]), 1), i, ref)
                    for i, ref in enumerate(references.get("references", []))
                ),
                key=lambda row: row[0],
            )
            if ranked:
                distance, index, nearest = ranked[0]
                strategy = {
                    "nearest": nearest["strategy"],
                    "distance": distance,
                    "top3": [
                        {"strategy": ref["strategy"], "distance": d} for d, _, ref in ranked[:3]
                    ],
                    # The reference trajectory this session was matched to: its place in
                    # references.json of this revision and its symbols, so "your trajectory
                    # vs. the reference" can be drawn and the match found again later.
                    "reference": {
                        "id": f"{ID}@{revision}#{index}",
                        "index": index,
                        "strategy": nearest["strategy"],
                        "sequence": [str(s) for s in nearest["sequence"]],
                    },
                    # Step-by-step alignment to that reference (request #2 of the product
                    # side): which of this session's steps answers which reference step,
                    # so the two trajectories can be drawn with their connecting lines.
                    # Only the nearest reference carries it; the top-3 stay distances.
                    "path": dtw_path(sequence, [str(s) for s in nearest["sequence"]])[1],
                }
                aligned = alignment(sequence, nearest["sequence"])
        else:
            revision = FALLBACK_REVISION
            submitted = False
            path = []
            for symbol in sequence:
                path.append(rule_phase(symbol, submitted))
                submitted = submitted or symbol == "submit"
        for row, state in zip(rows, path, strict=False):
            row["phase"] = names[min(state, len(names) - 1)]
        phases = []
        for row in rows:
            if phases and phases[-1]["name"] == row["phase"]:
                phases[-1]["to_seq"] = row["seq"]
            else:
                phases.append({"name": row["phase"], "from_seq": row["seq"], "to_seq": row["seq"]})
        flagged = anomalies(rows)
        kinds = Counter(row.get("executor", "human") for row in rows)
        declared = kinds.most_common(1)[0][0] if kinds else "human"
        executor = {
            "declared": {"external_agent": "own_agent", "reference_agent": "reference_agent"}.get(
                declared, "human"
            ),
            "predicted": None,
            "confidence": None,
        }
        # The window the symbols came from: every public event and role turn of the view,
        # from the start of the session to the view's business point (for a feedback job,
        # the point the work was handed in at).
        window = {
            "from_seq": 0,
            "to_seq": int(view.state.business_seq),
            "events": sum("event_id" in row for row in rows),
            "turns": sum("event_id" not in row for row in rows),
        }
    signature = record(
        ID,
        revision,
        "behavior",
        {"sequence": sequence},
        label=strategy["nearest"] if strategy else None,
        score=strategy["distance"] if strategy else None,
        outputs={
            "length": len(sequence),
            "phase_now": rows[-1]["phase"] if rows else None,
            "anomalies": [a["rule"] for a in flagged],
            "window": window,
            # Each step with the event it came from, so a frozen record can be laid next to
            # the live trajectory of the same session step by step.
            "steps": [
                {"seq": row["seq"], "symbol": row["symbol"], "event_id": row.get("event_id")}
                for row in rows
            ],
            "reference": strategy["reference"]["id"] if strategy else None,
        },
        duration_ms=clock.ms,
    )
    return {
        "sequence": rows,
        "strategy": strategy,
        "alignment": aligned,
        "phases": phases,
        "anomalies": flagged,
        "executor": executor,
        "window": window,
        "recognizer": f"{ID}@{revision}",
        "record": signature.model_dump(mode="json"),
    }


def learner_state(view, auth, *, language: str = "zh", intent_record=None) -> dict[str, Any]:
    """Compact state for the ROLES prompt (N3): phase, what was read, tests, pending asks."""
    result = analyze(view, auth, language=language)
    sequence = [row["symbol"] for row in result["sequence"]]
    read = sorted({s.split(":", 1)[1] for s in sequence if s.startswith("read:")})
    pending = [
        s.split(":", 1)[1]
        for i, s in enumerate(sequence)
        if s.startswith("request:")
        and not any(x.startswith(("approved:", "denied:")) for x in sequence[i + 1 :])
    ]
    state = {
        "phase": result["sequence"][-1]["phase"] if result["sequence"] else PHASES[language][0],
        "materials_read": [m for m in read if m in KEY_MATERIALS],
        "materials_unread": [m for m in KEY_MATERIALS if m not in read],
        "tests_run": sum(s.startswith("test:") for s in sequence),
        "requests_pending": pending,
        "anomalies": [a["rule"] for a in result["anomalies"]],
        "recognizer": result["recognizer"],
    }
    if intent_record is not None:
        state["intent"] = {
            "label": intent_record.label,
            "confidence": intent_record.score,
            "recognizer": f"{intent_record.recognizer_id}@{intent_record.revision}",
        }
    brief = _aipm_brief(view, auth, language)
    if brief:
        state["aipm"] = brief
    return state


def _aipm_brief(view, auth, language: str) -> dict[str, Any] | None:
    """The AI PM colleague brief (request #4 of the product side): the step the learner is
    on, the state of each sheet and the gaps of the latest review, in a few hundred
    characters, produced by ``career_lab.aipm.colleague_brief(view, auth, language)`` when
    the aipm module provides it. None outside an AI PM session, when the function does not
    exist yet, or when it fails: the brief is an annotation, never a reason to fail."""
    try:
        from career_lab import aipm

        brief = getattr(aipm, "colleague_brief", None)
        if brief is None:
            from career_lab.aipm import progress

            brief = getattr(progress, "colleague_brief", None)
        if brief is None:
            return None
        return dict(brief(view, auth, language) or {}) or None
    except Exception:  # noqa: BLE001
        return None
