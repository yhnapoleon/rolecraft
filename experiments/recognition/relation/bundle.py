"""Pack relation-v3 and the training script for Colab: ``runs/local/colab/c1-bundle.zip``.

    python -m experiments.recognition.relation.bundle
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    out = ROOT / "runs/local/colab/c1-bundle.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "data/releases/relation-v3/relation.jsonl", "relation.jsonl")
        archive.write(Path(__file__).with_name("train_c1.py"), "train_c1.py")
    print(out, out.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
