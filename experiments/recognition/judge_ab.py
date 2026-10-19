"""E8: the Judge with and without the recognition layer, on the same submissions.

    # 1. recognition on  (dev server started normally)
    python -m experiments.recognition.judge_ab run --condition on  --count 2
    # 2. recognition off (dev server restarted without CAREER_LAB_RECOGNIZERS)
    python -m experiments.recognition.judge_ab run --condition off --count 2
    # 3. compare
    python -m experiments.recognition.judge_ab compare

Both runs replay identical scripted sessions (same strategies, seeds, wording and work
text) against the DeepSeek-backed dev server, so the Judge input differs only by the
recognition layer (unitised candidates, the recognition summary in the prompt, the
recognizer support check, arbitration). Reported: per-criterion label agreement between
the conditions, the share of semantic criteria left pending, the explanation prefix
rates ([recognition agrees] / [missing] / [disagrees]), citations per item, and the
Judge-recognizer conflict rate on R2.support (arbiter records).
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter

from experiments.recognition.common import RESULTS, save
from scripts.recognition.run_strategies import STRATEGIES, Run

SEMANTIC = None  # every item whose source is model_advice or pending counts as semantic


def run(args) -> None:
    out = RESULTS / f"e8_raw_{args.condition}_{args.languages.replace(',', '')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {
            (r["strategy"], r["seed"], r["language"])
            for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())
        }
    names = [n for n in STRATEGIES if n != "revise_loop"]
    with out.open("a", encoding="utf-8", newline="\n") as handle:
        for language in args.languages.split(","):
            for i in range(args.count):
                for name in names:
                    seed = 777000 + 100 * names.index(name) + i + (0 if language == "zh" else 50)
                    if (name, seed, language) in done:
                        continue
                    r = Run(args.api, language, random.Random(seed))
                    error = None
                    try:
                        original = r.submit

                        def submit_and_wait(
                            decision, n, wait=False, *, _submit=original, **numbers
                        ):
                            return _submit(decision, n, wait=True, **numbers)

                        r.submit = submit_and_wait
                        STRATEGIES[name](r)
                    except Exception as exc:  # noqa: BLE001
                        error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    feedback = None
                    if r.submissions:
                        try:
                            body = r.s.feedback(r.submissions[-1]["object_id"])
                            feedback = body["result"]["result"]["items"][0]
                        except Exception as exc:  # noqa: BLE001
                            error = error or f"feedback: {exc}"
                    row = {
                        "condition": args.condition,
                        "strategy": name,
                        "seed": seed,
                        "language": language,
                        "error": error,
                        "items": [
                            {
                                "criterion": it["criterion"],
                                "label": it["label"],
                                "source": it["source"],
                                "citations": len(it.get("citations") or []),
                                "explanation": (it.get("explanation") or "")[:400],
                            }
                            for it in (feedback or {}).get("items", [])
                        ],
                        "recognition": [
                            {
                                k: rec.get(k)
                                for k in ("task", "recognizer_id", "label", "fallback", "outputs")
                            }
                            for rec in (feedback or {}).get("recognition") or []
                            if rec.get("task") in {"arbiter", "relation", "decision"}
                        ],
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    print(
                        args.condition,
                        language,
                        name,
                        i,
                        "items",
                        len(row["items"]),
                        "err",
                        error,
                        flush=True,
                    )
                    r.s.close()


PREFIX = {
    "agree": ("[识别一致]", "[recognition agrees]"),
    "missing": ("[识别缺失]", "[recognition missing]"),
    "disagree": ("[与识别不一致", "[disagrees with recognition"),
}


def semantic(items):
    return [it for it in items if it["source"] in {"model_advice", "pending"}]


def compare(args) -> None:
    rows = {}
    for condition in ("on", "off"):
        rows[condition] = {
            (r["strategy"], r["seed"], r["language"]): r
            for path in sorted(RESULTS.glob(f"e8_raw_{condition}_*.jsonl"))
            for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())
            if r["items"]
        }
    keys = sorted(set(rows["on"]) & set(rows["off"]))
    report = {"pairs": len(keys), "by_condition": {}, "agreement": {}}
    for condition in ("on", "off"):
        items = [it for k in keys for it in semantic(rows[condition][k]["items"])]
        prefixes = Counter()
        for it in items:
            for name, marks in PREFIX.items():
                if any(m in it["explanation"] for m in marks):
                    prefixes[name] += 1
        report["by_condition"][condition] = {
            "semantic_items": len(items),
            "pending_rate": sum(it["source"] == "pending" for it in items) / max(1, len(items)),
            "labelled_rate": sum(it["source"] == "model_advice" for it in items)
            / max(1, len(items)),
            "mean_citations": sum(it["citations"] for it in items) / max(1, len(items)),
            "label_distribution": dict(Counter(it["label"] for it in items)),
            "prefix_rate": {k: v / max(1, len(items)) for k, v in prefixes.items()},
        }
    same = total = 0
    per_criterion = Counter(), Counter()
    for k in keys:
        on = {it["criterion"]: it for it in semantic(rows["on"][k]["items"])}
        off = {it["criterion"]: it for it in semantic(rows["off"][k]["items"])}
        for criterion in set(on) & set(off):
            total += 1
            per_criterion[1][criterion] += 1
            if on[criterion]["label"] == off[criterion]["label"]:
                same += 1
                per_criterion[0][criterion] += 1
    report["agreement"] = {
        "label_agreement": same / max(1, total),
        "compared": total,
        "per_criterion": {c: per_criterion[0][c] / per_criterion[1][c] for c in per_criterion[1]},
    }
    arbiters = [
        rec for k in keys for rec in rows["on"][k]["recognition"] if rec["task"] == "arbiter"
    ]
    decided = [a for a in arbiters if a["label"] in {"agree", "conservative"}]
    report["arbiter"] = {
        "records": len(arbiters),
        "judge_decided": len(decided),
        "conflict_rate": sum(a["label"] == "conservative" for a in decided) / max(1, len(decided)),
    }
    save("e8_judge", report)
    print(json.dumps(report, ensure_ascii=False, indent=1)[:3000])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--condition", choices=["on", "off"], required=True)
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--api", default="http://127.0.0.1:18562")
    p.add_argument("--languages", default="zh,en")
    sub.add_parser("compare")
    args = parser.parse_args(argv)
    run(args) if args.command == "run" else compare(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
