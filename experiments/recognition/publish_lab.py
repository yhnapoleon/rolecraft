"""Copy experiment results the recognition lab page reads into ``apps/web/public/lab/``.

    python -m experiments.recognition.publish_lab [--c1 runs/local/recognizers/c1-xlmr]

E1 comes from the C1 training output (``metrics.json``); the others from
``experiments/recognition/results``. Rebuild the web app afterwards (``npm run build``).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from experiments.recognition.common import RESULTS, ROOT

TARGET = ROOT / "apps/web/public/lab"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--c1", default=str(ROOT / "runs/local/recognizers/c1-xlmr"))
    args = parser.parse_args(argv)
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in (
        "e1_baselines",
        "e3_retrieval",
        "e4_decision",
        "e5_scope",
        "e6_behavior",
        "e7_intent",
        "e8_judge",
        "e9_cross_domain",
        "e10_fusion",
    ):
        source = RESULTS / f"{name}.json"
        if source.exists():
            shutil.copyfile(source, TARGET / source.name)
            print("published", source.name)
    metrics = Path(args.c1) / "metrics.json"
    if metrics.exists():
        data = json.loads(metrics.read_text(encoding="utf-8"))
        slim = {k: data[k] for k in ("dev", "test", "temperature", "ece_before", "ece_after", "lift", "history")}
        with (TARGET / "e1_relation.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(slim, handle, ensure_ascii=False)
        print("published e1_relation.json from", metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
