"""Copy experiment results the system profile page (#/lab) reads into ``apps/web/public/lab/``.

    python -m experiments.recognition.publish_lab [--c1 runs/local/recognizers/c1-xlmr]

E1 comes from the C1 training output (``metrics.json``); when that directory is missing
the published ``e1_relation.json`` is left as it is. The others come from
``experiments/recognition/results``. E11–E15 are published with bulky fields the page
does not read removed (confusion matrices, predicted-label counts, the alpha grids and
meta-learner coefficients); every remaining field keeps its original key path, so a
number on the page can be traced to the same path in ``results/``. The raw E8 runs
(``e8_raw_*.jsonl``) are never published. Rebuild the web app afterwards
(``npm run build``).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from experiments.recognition.common import RESULTS, ROOT

TARGET = ROOT / "apps/web/public/lab"

# Copied byte for byte (E1–E10, already read by the page before E11–E15 were added).
WHOLE = (
    "e1_baselines",
    "e1_stack",
    "e3_retrieval",
    "e4_decision",
    "e5_scope",
    "e6_behavior",
    "e7_intent",
    "e8_judge",
    "e9_cross_domain",
    "e10_fusion",
    "e14_diagnose_public",
    "e14_review_errors",
)

# Published without these keys (at any depth).
PRUNED = {
    "e11_transfer_public": {"predicted"},
    "e12_mix_public": {"dev_grid_oof", "meta_coef", "per_class", "predicted"},
    "e13_reply": {"confusion", "per_class"},
    "e13_scope": set(),
    "e13_retrieval": {"by_kind"},
    "e13_sequence": {"confusion", "per_class", "ngram_rf_top_features"},
    "e13_intent": {"confusion", "per_class"},
    "e15_nli_zs": {"predicted"},
    "e15_nli_mix": {"predicted"},
    "e15_reply_zs": {"confusion", "per_class"},
    "e15_reply_mix": {"confusion", "per_class"},
}


def prune(value, drop: set[str]):
    """Return ``value`` without the keys in ``drop``; all other keys keep their paths."""
    if isinstance(value, dict):
        return {k: prune(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [prune(v, drop) for v in value]
    return value


def write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--c1", default=str(ROOT / "runs/local/recognizers/c1-xlmr"))
    args = parser.parse_args(argv)
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in WHOLE:
        source = RESULTS / f"{name}.json"
        if source.exists():
            shutil.copyfile(source, TARGET / source.name)
            print("published", source.name)
    for name, drop in PRUNED.items():
        source = RESULTS / f"{name}.json"
        if not source.exists():
            continue
        data = prune(json.loads(source.read_text(encoding="utf-8")), drop)
        write_json(TARGET / source.name, data)
        print("published", source.name, "without", ", ".join(sorted(drop)) or "nothing")
    metrics = Path(args.c1) / "metrics.json"
    if metrics.exists():
        data = json.loads(metrics.read_text(encoding="utf-8"))
        slim = {
            k: data[k]
            for k in ("dev", "test", "temperature", "ece_before", "ece_after", "lift", "history")
        }
        with (TARGET / "e1_relation.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(slim, handle, ensure_ascii=False)
        print("published e1_relation.json from", metrics)
    else:
        print("kept e1_relation.json:", metrics, "not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
