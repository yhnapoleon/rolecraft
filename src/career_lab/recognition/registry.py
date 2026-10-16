"""Recognizer registration and loading.

``CAREER_LAB_RECOGNIZERS=<dir>`` names the recognizer root; unset means every recognizer
uses its rule fallback. ``<dir>/manifest.json`` lists the weight directories::

    [{"id": "scope-mahalanobis-v1", "task": "scope", "path": "scope-mahalanobis-v1",
      "sha256": "<tree hash>", "revision": "<first 12>", "languages": ["zh", "en"]}]

The tree hash is the SHA-256 of ``"<relative path>\\t<file sha256>\\n"`` lines in sorted
order. A directory whose hash differs is not loaded and its recognizer falls back. C1 does
not live here: it stays on ``CAREER_LAB_MODEL_REGISTRATIONS`` and ``registry_cli``.

Register or refresh one entry::

    python -m career_lab.recognition.registry add <id> <task> <relative path> [--languages zh en]
    python -m career_lab.recognition.registry status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENV = "CAREER_LAB_RECOGNIZERS"
KNOWN = (
    ("retrieval-e5", "retrieval"),
    ("scope-mahalanobis-v1", "scope"),
    ("intent-tfidf-lr-v1", "intent"),
    ("behavior-v1", "behavior"),
)


@dataclass(frozen=True)
class Entry:
    id: str
    task: str
    path: Path
    sha256: str
    revision: str
    languages: tuple[str, ...]


def root() -> Path | None:
    value = os.environ.get(ENV)
    return Path(value) if value else None


def tree_sha256(path: Path) -> str:
    lines = []
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        h = hashlib.sha256()
        with file.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                h.update(block)
        lines.append(f"{file.relative_to(path).as_posix()}\t{h.hexdigest()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _read_manifest(base: Path) -> list[dict]:
    path = base / "manifest.json"
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in rows if isinstance(row, dict) and "id" in row]


@lru_cache(maxsize=1)
def load_all() -> dict[str, Entry | str]:
    """Every known recognizer mapped to its verified entry or a fallback reason."""
    base = root()
    status: dict[str, Entry | str] = {rid: "not_configured" for rid, _ in KNOWN}
    if base is None:
        return status
    for row in _read_manifest(base):
        path = (base / row.get("path", row["id"])).resolve()
        if not path.is_dir():
            status[row["id"]] = "missing"
            continue
        actual = tree_sha256(path)
        if row.get("sha256") and actual != row["sha256"]:
            status[row["id"]] = "hash_mismatch"
            continue
        status[row["id"]] = Entry(
            id=row["id"],
            task=row.get("task", ""),
            path=path,
            sha256=actual,
            revision=row.get("revision") or actual[:12],
            languages=tuple(row.get("languages", ("zh", "en"))),
        )
    for rid, value in status.items():
        if value == "not_configured" and (base / rid).is_dir() and rid == "retrieval-e5":
            # The embedder directory is a plain Hugging Face checkout; allow it unlisted.
            path = (base / rid).resolve()
            status[rid] = Entry(rid, "retrieval", path, "", "unhashed", ("zh", "en"))
    return status


def get(recognizer_id: str) -> Entry | None:
    found = load_all().get(recognizer_id)
    return found if isinstance(found, Entry) else None


def print_status(stream=sys.stderr) -> None:
    for rid, value in load_all().items():
        if isinstance(value, Entry):
            print(f"career-lab recognizer {rid}: loaded revision={value.revision}", file=stream)
        else:
            print(f"career-lab recognizer {rid}: rule-fallback ({value})", file=stream)


def add(recognizer_id: str, task: str, relative: str, languages: list[str]) -> dict:
    base = root()
    if base is None:
        raise SystemExit(ENV + " is not set")
    path = (base / relative).resolve()
    if not path.is_dir():
        raise SystemExit(f"{path} is not a directory")
    sha = tree_sha256(path)
    rows = [row for row in _read_manifest(base) if row["id"] != recognizer_id]
    entry = {
        "id": recognizer_id,
        "task": task,
        "path": relative.replace("\\", "/"),
        "sha256": sha,
        "revision": sha[:12],
        "languages": languages,
    }
    rows.append(entry)
    rows.sort(key=lambda row: row["id"])
    with (base / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    load_all.cache_clear()
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="career_lab.recognition.registry")
    sub = parser.add_subparsers(dest="command", required=True)
    added = sub.add_parser("add")
    added.add_argument("id")
    added.add_argument("task")
    added.add_argument("path")
    added.add_argument("--languages", nargs="+", default=["zh", "en"])
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "add":
        print(json.dumps(add(args.id, args.task, args.path, args.languages), indent=2))
    else:
        print_status(sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
