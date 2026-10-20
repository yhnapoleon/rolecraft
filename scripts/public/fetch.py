"""Download the public sources of data plan 3.3 into ``data/raw/public/<source>/``.

    python -m scripts.public.fetch                 # every source
    python -m scripts.public.fetch vitaminc cfever # only these

Each source directory gets ``source.json``: URL, pinned revision (commit or dataset sha),
retrieval date, licence and the SHA-256 of the licence file and of every downloaded file.
Files are pinned to a revision, downloads resume (``curl -C -``), and nothing here is
shipped: ``data/raw/`` is git-ignored. The Public Jira Dataset is streamed separately by
``scripts.public.jira_stream`` because the dump is 5.8 GB.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "public"
HF = "https://hf-mirror.com/datasets"

SOURCES = {
    "vitaminc": {
        "kind": "hf",
        "repo": "tals/vitaminc",
        "revision": "be6febb761b0b2807687e61e0b5282e459df2fa0",
        "files": ["train.jsonl", "dev.jsonl", "test.jsonl", "LICENSE", "README.md"],
        "license": "CC-BY-SA-3.0",
        "license_file": "LICENSE",
        "page": "https://github.com/TalSchuster/VitaminC",
        "citation": (
            "Schuster, Fisch and Barzilay. Get Your Vitamin C! Robust Fact Verification with "
            "Contrastive Evidence. NAACL 2021."
        ),
    },
    "cfever": {
        "kind": "hf",
        "repo": "IKMLab-team/cfever",
        "revision": "1f8fa4bd290832d7ad3109f49e347eb5dc77b7ad",
        "files": ["train.jsonl", "dev.jsonl", "test.jsonl", "LICENSE", "README.md"]
        + [f"wiki-{i:03d}.jsonl" for i in range(1, 25)],
        "license": "Apache-2.0",
        "license_file": "LICENSE",
        "page": "https://github.com/IKMLab/CFEVER-data",
        "citation": (
            "Lin et al. CFEVER: A Chinese Fact Extraction and VERification Dataset. AAAI 2024."
        ),
    },
    "site-policy": {
        "kind": "git",
        "url": "https://github.com/github/site-policy.git",
        "depth": None,  # full history: the policy revisions are the point
        "license": "CC0-1.0",
        "license_file": "LICENSE.md",
        "page": "https://github.com/github/site-policy",
    },
    "k8s-enhancements": {
        "kind": "git",
        "url": "https://github.com/kubernetes/enhancements.git",
        "depth": 1,
        "license": "Apache-2.0",
        "license_file": "LICENSE",
        "page": "https://github.com/kubernetes/enhancements",
    },
    "theagentcompany": {
        "kind": "git",
        "url": "https://github.com/TheAgentCompany/TheAgentCompany.git",
        "depth": 1,
        "license": "MIT",
        "license_file": "LICENSE",
        "page": "https://github.com/TheAgentCompany/TheAgentCompany",
        "citation": "Xu et al. TheAgentCompany. arXiv:2412.14161, 2024.",
    },
    "tau-bench": {
        "kind": "git",
        "url": "https://github.com/sierra-research/tau-bench.git",
        "depth": 1,
        "license": "MIT",
        "license_file": "LICENSE",
        "page": "https://github.com/sierra-research/tau-bench",
        "citation": "Yao et al. tau-bench. arXiv:2406.12045, 2024.",
    },
    "contractnli": {
        "kind": "existing",
        "path": "data/raw/contractnli",
        "files": ["contract-nli.zip", "LICENSE.txt"],
        "url": "https://stanfordnlp.github.io/contract-nli/resources/contract-nli.zip",
        "retrieved_at": "2026-10-02",
        "license": "CC-BY-4.0",
        "license_file": "LICENSE.txt",
        "page": "https://stanfordnlp.github.io/contract-nli/",
        "citation": (
            "Koreeda and Manning. ContractNLI: A Dataset for Document-level Natural Language "
            "Inference for Contracts. Findings of EMNLP 2021."
        ),
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def fetch_hf(name: str, spec: dict, out: Path) -> dict:
    files = {}
    for file in spec["files"]:
        target = out / file
        url = f"{HF}/{spec['repo']}/resolve/{spec['revision']}/{file}"
        for attempt in range(6):
            done = subprocess.run(
                ["curl", "-sSL", "-C", "-", "--retry", "3", "-o", str(target), url]
            )
            if done.returncode in (0, 33):  # 33: range not satisfiable = already complete
                break
            time.sleep(3 + 5 * attempt)
        else:
            raise SystemExit(f"{name}: {file} failed")
        files[file] = {"url": url, "sha256": sha256(target), "bytes": target.stat().st_size}
        print(name, file, files[file]["bytes"], flush=True)
    return {"repo": spec["repo"], "revision": spec["revision"], "files": files}


def fetch_git(name: str, spec: dict, out: Path) -> dict:
    repo = out / "repo"
    if not (repo / ".git").exists():
        args = ["git", "clone", "-q"]
        if spec["depth"]:
            args += ["--depth", str(spec["depth"])]
        run(*args, spec["url"], str(repo))
    commit = run("git", "rev-parse", "HEAD", cwd=repo).strip()
    date = run("git", "log", "-1", "--format=%cI", cwd=repo).strip()
    print(name, commit, date, flush=True)
    return {"url": spec["url"], "commit": commit, "commit_date": date, "depth": spec["depth"]}


def fetch(name: str) -> None:
    spec = SOURCES[name]
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "hf":
        record = fetch_hf(name, spec, out)
        license_path = out / spec["license_file"]
    elif spec["kind"] == "git":
        record = fetch_git(name, spec, out)
        license_path = out / "repo" / spec["license_file"]
    else:
        base = ROOT / spec["path"]
        record = {
            "url": spec["url"],
            "local_path": spec["path"],
            "files": {f: {"sha256": sha256(base / f)} for f in spec["files"]},
        }
        license_path = base / spec["license_file"]
    record.update(
        {
            "source_id": name,
            "page": spec["page"],
            "retrieved_at": spec.get("retrieved_at", time.strftime("%Y-%m-%d")),
            "license": spec["license"],
            "license_file": str(license_path.relative_to(ROOT)).replace("\\", "/"),
            "license_sha256": sha256(license_path),
            "citation": spec.get("citation"),
        }
    )
    with (out / "source.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    for source in sys.argv[1:] or list(SOURCES):
        fetch(source)
