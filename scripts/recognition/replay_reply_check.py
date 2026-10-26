"""Re-run the C10 reply check over the colleague replies of a demo pack, before and after.

For every stored colleague reply the script runs ``check_reply`` twice on the same
visible materials (the scenario's public materials in force at the reply's point): once
with each material as one whole candidate (the behaviour before 2026-10-27) and once with
the materials cut into units (the current behaviour), and prints per sentence the label the
product stored at recording time next to both re-runs. Sentences that cite a material
(``[...]`` or a figure) are counted separately: those are the ones the product side wants to
tag "to verify", so a correct one judged contradicted or insufficient is the error that
matters (F06).

Needs the recognizer root and the C1 export, else everything is the rule fallback:

    CAREER_LAB_RECOGNIZERS=runs/local/recognizers
    CAREER_LAB_RELATION_ENCODER=runs/local/recognizers/c1-xlmr-cpu
    python -m scripts.recognition.replay_reply_check --pack demo/demo-pack-v1.json.gz \\
        --catalog demo/catalog.json [--out <json file>]
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

CITED = re.compile(r"\[[^\]]+\]|\d")


def materials_of(root: Path) -> list[dict]:
    """Public materials of a scenario package: id, version, title, text (the md file)."""
    found = []
    for entry in json.loads((root / "materials.json").read_text(encoding="utf-8")):
        if any(f["disclosure"]["mode"] != "public" for f in entry["fragments"]):
            continue
        path = root / "materials" / f"{entry['id']}-v{entry['version']}.md"
        if not path.is_file():
            continue
        found.append(
            {
                "id": entry["id"],
                "version": entry["version"],
                "title": entry["title"],
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return found


def published_at(session: dict) -> dict[tuple[str, int], int]:
    """(material id, version) -> seq of the event that published it mid-session."""
    seqs: dict[tuple[str, int], int] = {}
    for row in session["rows"].get("v2_events", []):
        record = row["record"] if isinstance(row["record"], dict) else json.loads(row["record"])
        text = json.dumps(record, ensure_ascii=False)
        for material, version in re.findall(r'"object_id": "([a-z_]+)", "version": (\d+)', text):
            if int(version) > 1:
                seqs.setdefault((material, int(version)), int(row["seq"]))
    return seqs


def visible_at(materials: list[dict], published: dict, seq: int) -> list[tuple[str, str]]:
    latest: dict[str, dict] = {}
    for m in materials:
        if m["version"] > 1 and published.get((m["id"], m["version"]), 10**9) > seq:
            continue
        if m["id"] not in latest or latest[m["id"]]["version"] < m["version"]:
            latest[m["id"]] = m
    found = []
    for m in latest.values():
        since = published.get((m["id"], m["version"]), 0) if m["version"] > 1 else 0
        found.append((f"material:{m['id']}@{m['version']}", m["text"], since, since, None))
    return found


def replies_of(session: dict) -> list[dict]:
    found = []
    for row in session["rows"].get("v2_objects", []):
        if row["kind"] != "role_reply":
            continue
        record = row["record"] if isinstance(row["record"], dict) else json.loads(row["record"])
        content = record.get("content", record)
        stored = next(
            (r for r in content.get("recognition") or () if r.get("task") == "reply_check"),
            None,
        )
        found.append(
            {
                "id": row["id"],
                "role": content.get("role_id"),
                "text": content.get("text", ""),
                "seq": int((content.get("as_of") or {}).get("business_seq", 0)),
                "stored": (stored or {}).get("outputs", {}).get("sentences", []),
            }
        )
    return found


def run(reply: str, visible, language: str, whole: bool) -> list[dict]:
    from career_lab.recognition import reply as c10

    original = c10.unitize
    if whole:
        c10.unitize = lambda sources, query="": [
            {"id": x[0], "text": x[1], "source": x[0], "span": None, "validity": tuple(x[2:])}
            for x in sources
        ]
    try:
        return c10.check_reply(reply, visible, language=language).outputs["sentences"]
    finally:
        c10.unitize = original


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    pack = json.load(gzip.open(args.pack, "rt", encoding="utf-8"))
    roots = {
        row["scenario_hash"]: Path(row["root"])
        for row in json.loads(Path(args.catalog).read_text(encoding="utf-8"))["scenarios"]
    }
    totals = {name: Counter() for name in ("stored", "whole", "units")}
    cited_totals = {name: Counter() for name in ("stored", "whole", "units")}
    report = []
    for session in pack["sessions"]:
        root = roots.get(session["scenario_manifest_sha256"])
        if root is None:
            print(f"skip {session['session_id']}: scenario not in catalog", file=sys.stderr)
            continue
        materials = materials_of(root)
        published = published_at(session)
        language = session["work_language"]
        for reply in replies_of(session):
            visible = visible_at(materials, published, reply["seq"])
            whole = run(reply["text"], visible, language, whole=True)
            units = run(reply["text"], visible, language, whole=False)
            stored = {r["quote"]: r for r in reply["stored"]}
            rows = []
            for before, after in zip(whole, units, strict=True):
                was = stored.get(before["quote"], {})
                row = {
                    "quote": before["quote"],
                    "cited": bool(CITED.search(before["quote"])),
                    "stored": was.get("label"),
                    "whole": before["label"],
                    "units": after["label"],
                    "units_decision": after["decision"],
                    "units_confidence": round(after["confidence"], 3),
                    "units_evidence": after["evidence_ids"],
                }
                rows.append(row)
                for name in totals:
                    label = row[name] or "n/a"
                    totals[name][label] += 1
                    if row["cited"]:
                        cited_totals[name][label] += 1
            report.append(
                {
                    "session": session["session_id"],
                    "scenario": session["scenario"],
                    "language": language,
                    "role": reply["role"],
                    "seq": reply["seq"],
                    "sources": len(visible),
                    "sentences": rows,
                }
            )
            for row in rows:
                mark = "*" if row["cited"] else " "
                print(
                    f"{mark} {row['stored'] or '-':<13} {row['whole']:<13} {row['units']:<13} "
                    f"{row['units_decision']:<6} {row['quote'][:70]}"
                )
    print()
    print("all sentences        ", {k: dict(v) for k, v in totals.items()})
    print("sentences with a cite", {k: dict(v) for k, v in cited_totals.items()})
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "totals": {k: dict(v) for k, v in totals.items()},
                    "cited": {k: dict(v) for k, v in cited_totals.items()},
                    "replies": report,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
