"""Download official ContractNLI once; import five source-train documents only."""
import hashlib
import json
import zipfile
from pathlib import Path

import httpx

from career_lab.datasets.import_contractnli import import_contractnli
from career_lab.datasets.release import build_release

URL = "https://stanfordnlp.github.io/contract-nli/resources/contract-nli.zip"
root = Path("data/raw/contractnli")
root.mkdir(parents=True, exist_ok=True)
archive = root / "contract-nli.zip"
if not archive.exists():
    with httpx.stream("GET", URL, timeout=60, follow_redirects=True) as response:
        response.raise_for_status()
        total = 0
        with archive.with_suffix(".partial").open("wb") as out:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > 80_000_000:
                    raise ValueError("download exceeds expected size")
                out.write(chunk)
    archive.with_suffix(".partial").replace(archive)
with zipfile.ZipFile(archive) as z:
    names = z.namelist()
    train_name = next(n for n in names if n.endswith("/train.json") or n == "train.json")
    data = json.loads(z.read(train_name))
    license_name = next(n for n in names if Path(n).name.upper().startswith("LICENSE"))
    (root / "LICENSE.txt").write_bytes(z.read(license_name))
    data["documents"] = data["documents"][:5]
rows = import_contractnli(data, "train", "train")
manifest = build_release(Path("data/releases/contractnli-pilot-v1"), rows)
registry = {"source_id": "contractnli", "official_page": "https://stanfordnlp.github.io/contract-nli/", "download_url": URL,
            "download_date": "2026-10-02", "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "license": "CC-BY-4.0", "license_snapshot": str(root / "LICENSE.txt"), "license_sha256": hashlib.sha256((root / "LICENSE.txt").read_bytes()).hexdigest(),
            "source_split": "train", "documents": 5, "items": len(rows), "language": "en", "authors": "Yuta Koreeda and Christopher D. Manning",
            "citation": "ContractNLI: A Dataset for Document-level Natural Language Inference for Contracts. Findings of EMNLP 2021.",
            "manifest": str(manifest), "evidence_evaluable": False, "note": "original spans preserved without treating them as minimal sufficient sets"}
Path("docs/reports/task-07-public-source.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
print(json.dumps({"documents": 5, "items": len(rows), "manifest": str(manifest)}))
