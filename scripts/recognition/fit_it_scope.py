"""Fit C4 (scope-mahalanobis-v1) for the playable it_ticket_pilot and re-register it.

    PYTHONUTF8=1 .venv-encoder/Scripts/python -m scripts.recognition.fit_it_scope

E9 showed the pm_pilot fit does not transfer (AUROC 0.60/0.50) while a fit on the IT
knowledge base alone does (0.99/0.95). This writes that fit for the built package: Ledoit-Wolf
on the package's KB paragraphs (as e5 queries), threshold at 95 % TPR on the it-ticket-v1
in-domain questions. scope_on drops the policy domains, as the pm_pilot fit does. The
recognizer directory is re-hashed and re-registered; restart the API and worker afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from sklearn.covariance import LedoitWolf

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scenarios/it_ticket_pilot/v2/candidates/it-1/it_ticket_pilot"
QUERIES = ROOT / "data/releases/it-ticket-v1/queries.jsonl"
os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(ROOT / "runs/local/recognizers"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", nargs="+", default=["zh"])
    args = parser.parse_args(argv)
    from career_lab.recognition import registry
    from career_lab.recognition.embedder import Embedder
    from career_lab.scenarios.v2.loader import load_package

    embedder = Embedder.get()
    if embedder is None:
        raise SystemExit("embedder unavailable: run under .venv-encoder with retrieval-e5 present")
    target = registry.root() / "scope-mahalanobis-v1"
    fits = json.loads((target / "fits.json").read_text(encoding="utf-8"))
    queries = [json.loads(line) for line in QUERIES.read_text(encoding="utf-8").splitlines()]
    for language in args.languages:
        package = load_package(PACKAGE if language == "zh" else PACKAGE / "locales/en")
        kb = {mid: domain for domain, mids in package.bundle.domains.items() for mid in mids}
        units = [(kb[m.id], f.text) for m in package.materials if m.id in kb for f in m.fragments]
        vectors = embedder.encode([text for _, text in units], "query")
        passages = embedder.encode([text for _, text in units], "passage")
        same = [
            1.0 - float(passages[i] @ passages[j])
            for i in range(len(units))
            for j in range(i + 1, len(units))
            if units[i][0] == units[j][0]
        ]
        rows = [q for q in queries if q["language"] == language and q["kind"].startswith("in_")]
        q_vectors = embedder.encode([q["query"] for q in rows], "query")
        for setting in ("scope_off", "scope_on"):
            keep = [
                i
                for i, (domain, _) in enumerate(units)
                if setting == "scope_off" or not domain.startswith("policy")
            ]
            lw = LedoitWolf().fit(vectors[keep])
            mean, precision = lw.location_, lw.precision_
            d = vectors.shape[1]
            inside = np.array(
                [setting == "scope_off" or "sla" not in str(q.get("domain")) for q in rows]
            )
            delta = q_vectors[inside] - mean
            scores = np.sqrt(np.einsum("ij,jk,ik->i", delta, precision, delta).clip(0)) / np.sqrt(d)
            key = f"it_ticket_pilot/{language}/{setting}"
            fits[key] = {
                "threshold": float(np.quantile(scores, 0.95)),
                "dims": d,
                "n": len(keep),
                "drift_mean": float(np.mean(same)),
                "drift_std": float(np.std(same)),
            }
            np.savez(target / (key.replace("/", "__") + ".npz"), mean=mean, precision=precision)
            print(key, json.dumps(fits[key]))
    with (target / "fits.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(fits, handle, indent=2)
    print(registry.add("scope-mahalanobis-v1", "scope", "scope-mahalanobis-v1", ["zh", "en"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
