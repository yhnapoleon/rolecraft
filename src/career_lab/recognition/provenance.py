"""N5: session-level recognition provenance.

Records live on the objects they shaped (``feedback.recognition``, ``test.recognition``,
``role_reply.recognition``); this module only reads them back. No separate table.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

CARRIERS = ("test", "role_reply", "feedback")


def latest_objects(view, kinds=CARRIERS):
    """The newest version of every object of the given kinds visible in this view."""
    newest: dict[tuple[str, str], Any] = {}
    for stored in view.objects:
        if stored.ref.kind not in kinds:
            continue
        key = (stored.ref.kind, stored.ref.object_id)
        if key not in newest or stored.ref.version > newest[key].ref.version:
            newest[key] = stored
    return sorted(newest.values(), key=lambda r: (r.created_storage_revision, r.ref.object_id))


def session_records(view) -> list[dict[str, Any]]:
    rows = []
    for stored in latest_objects(view):
        content = stored.content if isinstance(stored.content, dict) else {}
        for position, item in enumerate(content.get("recognition") or ()):
            rows.append(
                {
                    "carrier": {
                        "kind": stored.ref.kind,
                        "object_id": stored.ref.object_id,
                        "version": stored.ref.version,
                    },
                    "position": position,
                    "record": item,
                }
            )
    rows.sort(
        key=lambda row: (
            ((row["record"].get("as_of") or {}).get("business_seq") or 0),
            row["carrier"]["object_id"],
            row["position"],
        )
    )
    return rows


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    tally: Counter[str] = Counter()
    for row in rows:
        record = row["record"]
        tally[record["task"]] += 1
        if record["task"] == "relation":
            tally["relation_units"] += len((record.get("outputs") or {}).get("units") or ())
        if record.get("fallback"):
            tally["fallback"] += 1
    return dict(sorted(tally.items()))


def recognition_read(view, payload, auth):
    from career_lab.api.modules import V2Response

    rows = session_records(view)
    recognizers = sorted(
        {
            (row["record"]["recognizer_id"], row["record"]["revision"], row["record"]["fallback"])
            for row in rows
        }
    )
    return V2Response(
        result={
            "session_id": auth.session_id,
            "records": rows,
            "counts": counts(rows),
            "recognizers": [
                {"id": rid, "revision": revision, "fallback": fallback}
                for rid, revision, fallback in recognizers
            ],
        }
    )


def install_recognition_reads(registry, *, scenario_resolver) -> None:
    from career_lab.api.modules import Operation, V2Response
    from career_lab.contracts.v2.core import ProtocolError
    from career_lab.contracts.v2.requests import ResourcePage

    def behavior_read(view, payload, auth):
        try:
            from career_lab.recognition.behavior import analyze
        except ImportError:
            raise ProtocolError("behavior_recognizer_unavailable", status=503) from None
        module = scenario_resolver(view.bindings)
        language = getattr(module, "work_language", "zh")
        return V2Response(result=analyze(view, auth, language=language))

    for name, handler in (("recognition.read", recognition_read), ("behavior.read", behavior_read)):
        registry.register(
            Operation(
                name, "read", ResourcePage, handler, mutates=False, response_model=V2Response
            )
        )
