"""Self-check for the RoleCraft return v3 supplementary package (Python standard library only).

Usage::

    python3 -I check_package.py [package directory]   # default: this file's directory

Rules:

1. ``SHA256SUMS`` lines are ``<64 lowercase hex>  <relative path>`` (two spaces, the
   ``sha256sum``/``shasum -a 256`` text form). Paths are relative with ``/`` separators and no
   empty, ``.`` or ``..`` segments; no duplicates; the list never names itself.
2. Every listed file exists as a regular file and its SHA-256 matches.
3. Every file under the directory is listed. ``SHA256SUMS`` itself is the only exception, so
   hidden files (``.DS_Store``), ``__pycache__`` and editor backups fail; a symbolic link
   anywhere fails. Directories themselves are not checked.
4. Every listed ``.json`` file, and every line of every listed ``.jsonl`` file, is UTF-8 JSON
   without NaN/Infinity or duplicate keys.

Prints one JSON summary; exit status 0 when every rule holds, otherwise 1. It reads files
only: it never imports, runs or writes anything in the package.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

PROTOCOL = "rolecraft-return-v3-package-check-v1"
SUMS = "SHA256SUMS"
LINE = re.compile(r"([0-9a-f]{64})  (.+)")


class JsonError(ValueError):
    """Valid JSON that the package rules still reject."""


def _no_duplicates(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise JsonError("duplicate key")
    return dict(pairs)


def _no_constants(name):
    raise JsonError(name + " is not allowed")


def _strict_json(text):
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)


def _safe_path(name):
    parts = name.split("/")
    return (
        name != SUMS
        and "\\" not in name
        and "\x00" not in name
        and all(part not in ("", ".", "..") for part in parts)
    )


def _walk(root, relative, files, errors):
    with os.scandir(os.path.join(root, *relative)) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            name = "/".join([*relative, entry.name])
            if entry.is_symlink():
                errors.append({"code": "symlink_not_allowed", "path": name})
            elif entry.is_dir(follow_symlinks=False):
                _walk(root, [*relative, entry.name], files, errors)
            elif entry.is_file(follow_symlinks=False):
                files.add(name)
            else:
                errors.append({"code": "file_not_regular", "path": name})


def _read_list(root, errors):
    path = root / SUMS
    if path.is_symlink() or not path.is_file():
        errors.append({"code": "checksum_list_missing", "path": SUMS})
        return {}
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        errors.append({"code": "checksum_list_unreadable", "path": SUMS})
        return {}
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    expected = {}
    for number, line in enumerate(lines, start=1):
        match = LINE.fullmatch(line)
        if match is None:
            errors.append({"code": "checksum_line_invalid", "path": SUMS, "line": number})
        elif not _safe_path(match.group(2)):
            errors.append({"code": "checksum_path_invalid", "path": SUMS, "line": number})
        elif match.group(2) in expected:
            errors.append({"code": "checksum_path_duplicate", "path": match.group(2)})
        else:
            expected[match.group(2)] = match.group(1)
    return expected


def _parse(path, name, errors):
    """Return the parsed kind, or None when the file is not JSON or does not parse."""
    if name.endswith(".json"):
        try:
            _strict_json(path.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            errors.append({"code": "json_invalid", "path": name})
            return None
        return "json"
    if name.endswith(".jsonl"):
        try:
            lines = path.read_bytes().decode("utf-8").split("\n")
        except UnicodeDecodeError:
            errors.append({"code": "json_invalid", "path": name})
            return None
        if lines and lines[-1] == "":
            lines.pop()
        for number, line in enumerate(lines, start=1):
            try:
                _strict_json(line)
            except ValueError:
                errors.append({"code": "json_invalid", "path": name, "line": number})
                return None
        return "jsonl"
    return None


def check(root):
    root = Path(root).resolve()
    errors = []
    summary = {"protocol": PROTOCOL, "root": str(root), "status": "failed"}
    if not root.is_dir():
        errors.append({"code": "package_root_invalid", "path": str(root)})
        summary.update(listed=0, verified=0, parsed={}, errors=errors)
        return summary
    expected = _read_list(root, errors)
    present = set()
    _walk(str(root), [], present, errors)
    linked = {e["path"] for e in errors if e["code"] == "symlink_not_allowed"}
    verified = 0
    parsed = {"json": 0, "jsonl": 0}
    for name in sorted(expected):
        if name not in present:
            if name not in linked:
                errors.append({"code": "file_missing", "path": name})
            continue
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() == expected[name]:
            verified += 1
        else:
            errors.append({"code": "file_hash_mismatch", "path": name})
        kind = _parse(path, name, errors)
        if kind is not None:
            parsed[kind] += 1
    for name in sorted(present - set(expected) - {SUMS}):
        errors.append({"code": "unlisted_file", "path": name})
    summary.update(
        status="failed" if errors else "ok",
        listed=len(expected),
        verified=verified,
        parsed=parsed,
        errors=errors,
    )
    return summary


def main(argv):
    if len(argv) > 2:
        result = {"protocol": PROTOCOL, "status": "failed", "errors": [{"code": "usage"}]}
    else:
        result = check(argv[1] if len(argv) == 2 else Path(__file__).resolve().parent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
