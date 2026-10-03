import hashlib
import json
import zipfile
from pathlib import Path


def package_release(root: Path, output: Path) -> Path:
    root, output = root.resolve(), output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("release archive already exists")
    files = [root / name for name in ("pyproject.toml", "uv.lock", "README.md", "compose.yaml", ".gitignore", ".gitattributes")]
    allowed = {".py", ".md", ".yaml", ".json", ".xml", ".sql"}
    for directory in ("src/career_lab", "tests", "scenarios", "configs", "scripts", "docs"):
        files.extend(p for p in (root / directory).rglob("*") if p.is_file() and p.suffix in allowed and "__pycache__" not in p.parts and p.resolve().is_relative_to(root))
    hashes = {}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            if path.exists():
                name = path.relative_to(root).as_posix()
                raw = path.read_bytes()
                hashes[name] = hashlib.sha256(raw).hexdigest()
                archive.writestr(name, raw)
        archive.writestr("release-manifest.json", json.dumps({"files": hashes, "scope": "source-and-reproducible-scripts; no credentials/raw-data/model-binaries"}, indent=2))
    return output
