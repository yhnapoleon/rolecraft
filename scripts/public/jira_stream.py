"""Stream the Public Jira Dataset dump and keep issues whose plan visibly slipped.

    uv run --no-project --with pymongo python -m scripts.public.jira_stream --limit 400

The Zenodo record (CC BY 4.0, 5.8 GB) is a zip holding one gzip-compressed mongodump
archive with four collections dumped concurrently. Downloading it whole runs at about
0.7 MB/s, so this reads the zip member over HTTP ranges (several in flight), decompresses
on the fly, parses the archive blocks and stops once ``--limit`` issues are kept. The
selection is reproducible: the first issues in dump order that satisfy ``keep()``.

Kept issues go to ``data/raw/public/jira/issues.jsonl`` (Extended JSON, anonymised by the
dataset authors) and ``source.json`` records the record id, file checksum, the selection
rule and how far into the stream the scan went.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import time
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bson
from bson import json_util

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "public" / "jira"
RECORD = "https://zenodo.org/records/15719919"
URL = "https://zenodo.org/api/records/15719919/files/2025-06-23%20ThePublicJiraDataset.zip/content"
MEMBER = "ThePublicJiraDataset/3. DataDump/mongodump-JiraReposAnon.archive"
CHUNK = 4 << 20
INFLIGHT = 8
TERMINATOR = b"\xff\xff\xff\xff"


class RangeFile(io.RawIOBase):
    """Seekable read-only view of a remote file; sequential reads prefetch ahead."""

    def __init__(self, url: str):
        self.url = url
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self.pos = 0
        self.pool = ThreadPoolExecutor(INFLIGHT)
        self.futures: dict[int, object] = {}
        self.fetched = 0

    def _get(self, start: int) -> bytes:
        end = min(start + CHUNK, self.size) - 1
        for attempt in range(8):
            try:
                req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = r.read()
                if len(data) == end - start + 1:
                    return data
            except Exception:  # noqa: BLE001 - retry transient network failures
                pass
            time.sleep(2 + 4 * attempt)
        raise OSError(f"range {start}-{end} failed")

    def _chunk(self, index: int) -> bytes:
        for ahead in range(index, index + INFLIGHT):
            if ahead * CHUNK < self.size and ahead not in self.futures:
                self.futures[ahead] = self.pool.submit(self._get, ahead * CHUNK)
        data = self.futures.pop(index).result()
        for stale in [k for k in self.futures if k < index]:
            self.futures.pop(stale)
        self.fetched += len(data)
        return data

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, offset, whence=0):
        self.pos = (
            offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        )
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, buffer):
        if self.pos >= self.size or not len(buffer):
            return 0
        index, skip = divmod(self.pos, CHUNK)
        data = self._chunk(index)[skip : skip + len(buffer)]
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


class Inflate:
    """Byte stream of the gzip layer inside the zip member."""

    def __init__(self, member):
        self.member = member
        self.gz = zlib.decompressobj(31)
        self.buf = bytearray()

    def read(self, n: int) -> bytes:
        while len(self.buf) < n:
            raw = self.member.read(1 << 20)
            if not raw:
                break
            self.buf += self.gz.decompress(raw)
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out


def documents(stream: Inflate):
    """Yield (collection, document) from a mongodump archive stream."""
    if stream.read(4) != b"\x6d\xe2\x99\x81":
        raise ValueError("not a mongodump archive")
    while True:  # prelude: header + collection metadata, then a terminator
        size = stream.read(4)
        if size == TERMINATOR:
            break
        stream.read(struct.unpack("<i", size)[0] - 4)
    while True:
        size = stream.read(4)
        if len(size) < 4:
            return
        header = bson.decode(size + stream.read(struct.unpack("<i", size)[0] - 4))
        collection = header.get("collection")
        while True:
            size = stream.read(4)
            if size == TERMINATOR or len(size) < 4:
                break
            body = stream.read(struct.unpack("<i", size)[0] - 4)
            if not header.get("EOF"):
                yield collection, bson.decode(size + body)


def fix_version_changes(issue: dict) -> list[dict]:
    histories = (issue.get("changelog") or {}).get("histories") or []
    out = []
    for history in histories:
        for item in history.get("items") or []:
            if item.get("field") in ("Fix Version", "duedate"):
                out.append(
                    {
                        "at": history.get("created"),
                        "field": item.get("field"),
                        "from": item.get("fromString"),
                        "to": item.get("toString"),
                    }
                )
    return out


FIELDS = (
    "summary",
    "description",
    "issuetype",
    "status",
    "priority",
    "resolution",
    "fixVersions",
    "versions",
    "created",
    "updated",
    "resolutiondate",
    "duedate",
    "components",
    "project",
    "issuelinks",
    "timeoriginalestimate",
    "timespent",
    "labels",
)
HISTORY_FIELDS = {
    "status",
    "Fix Version",
    "duedate",
    "resolution",
    "priority",
    "Version",
    "assignee",
    "Sprint",
    "Link",
    "timeestimate",
    "timeoriginalestimate",
}


def name_of(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("value") or value.get("key")
    if isinstance(value, list):
        return [name_of(v) for v in value]
    return value


def trim(issue: dict, collection: str) -> dict:
    """The PM-relevant part of an issue; custom fields and avatars are dropped."""
    fields = issue.get("fields") or {}
    out = {"collection": collection, "key": issue.get("key"), "id": issue.get("id")}
    for name in FIELDS:
        value = fields.get(name)
        if name == "issuelinks":
            value = [
                {
                    "type": (link.get("type") or {}).get("name"),
                    "direction": "outward" if "outwardIssue" in link else "inward",
                    "key": (link.get("outwardIssue") or link.get("inwardIssue") or {}).get("key"),
                    "status": name_of(
                        (
                            (link.get("outwardIssue") or link.get("inwardIssue") or {}).get(
                                "fields"
                            )
                            or {}
                        ).get("status")
                    ),
                }
                for link in value or []
            ]
        elif name in ("project",):
            value = {"key": (value or {}).get("key"), "name": (value or {}).get("name")}
        elif name not in (
            "summary",
            "description",
            "created",
            "updated",
            "resolutiondate",
            "duedate",
        ):
            value = name_of(value)
        out[name] = value
    out["history"] = [
        {
            "at": history.get("created"),
            "items": [
                {"field": i.get("field"), "from": i.get("fromString"), "to": i.get("toString")}
                for i in history.get("items") or []
                if i.get("field") in HISTORY_FIELDS
            ],
        }
        for history in (issue.get("changelog") or {}).get("histories") or []
    ]
    out["history"] = [h for h in out["history"] if h["items"]]
    return out


def keep(issue: dict) -> bool:
    """A slipped plan: the target version (or due date) was moved at least twice."""
    changes = fix_version_changes(issue)
    moved = [c for c in changes if c["from"] or (c["field"] == "duedate" and c["to"])]
    return len(moved) >= 2 and bool((issue.get("fields") or {}).get("summary"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--per-collection", type=int, default=150)
    parser.add_argument("--probe", action="store_true", help="print the first issue and stop")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    remote = RangeFile(URL)
    archive = zipfile.ZipFile(io.BufferedReader(remote, buffer_size=CHUNK))
    for name in ("LICENSE-CCBY4.0.md", "README.md"):
        (OUT / name).write_bytes(archive.read(f"ThePublicJiraDataset/{name}"))
    stream = Inflate(archive.open(MEMBER))
    kept: list[dict] = []
    seen: dict[str, int] = {}
    per: dict[str, int] = {}
    started = time.time()
    for collection, issue in documents(stream):
        seen[collection] = seen.get(collection, 0) + 1
        if args.probe:
            print(
                collection, json.dumps(json_util.loads(json_util.dumps(issue)), default=str)[:6000]
            )
            return
        if per.get(collection, 0) >= args.per_collection or not keep(issue):
            continue
        per[collection] = per.get(collection, 0) + 1
        kept.append(trim(issue, collection))
        if len(kept) % 25 == 0:
            print(
                f"kept {len(kept)} scanned {sum(seen.values())} "
                f"fetched {remote.fetched / 1e6:.0f} MB {time.time() - started:.0f}s {per}",
                flush=True,
            )
        if len(kept) >= args.limit:
            break
    path = OUT / "issues.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for issue in kept:
            handle.write(json.dumps(issue, ensure_ascii=False, default=str) + "\n")
    record = {
        "source_id": "jira",
        "page": RECORD,
        "download_url": URL,
        "member": MEMBER,
        "archive_md5": "02f85309d966092ea130ca0797aea795",
        "retrieved_at": time.strftime("%Y-%m-%d"),
        "license": "CC-BY-4.0",
        "license_note": "data CC BY 4.0, scripts MIT (LICENSE-CCBY4.0.md in the record)",
        "license_file": "data/raw/public/jira/LICENSE-CCBY4.0.md",
        "license_sha256": hashlib.sha256((OUT / "LICENSE-CCBY4.0.md").read_bytes()).hexdigest(),
        "citation": (
            "Montgomery, Lüders and Maalej. An Alternative Issue Tracking Dataset of Public "
            "Jira Repositories. MSR 2022."
        ),
        "selection": {
            "rule": "first issues in dump order whose Fix Version or due date moved >= 2 times",
            "limit": args.limit,
            "per_collection": args.per_collection,
            "scanned_per_collection": seen,
            "kept_per_collection": per,
            "compressed_bytes_read": remote.fetched,
        },
        "files": {
            "issues.jsonl": {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "records": len(kept),
            }
        },
    }
    with (OUT / "source.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(record["selection"], ensure_ascii=False))


if __name__ == "__main__":
    main()
