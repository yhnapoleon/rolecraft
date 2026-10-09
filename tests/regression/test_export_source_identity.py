"""Fresh contract exports identify the runtime adapter behind the compatibility import."""

import hashlib
import json
from pathlib import Path

from career_lab.contracts.v2.export import export
from scripts.regression.published import ROOT


def test_contract_export_tracks_runtime_role_snapshot_source(tmp_path: Path) -> None:
    result = export(ROOT, tmp_path / "export")
    manifest = json.loads(Path(result["manifest"]).read_text())
    sources = manifest["source_files"]
    for name in (
        "src/career_lab/api/role_snapshot.py",
        "src/career_lab/runtime/role_snapshot.py",
    ):
        assert name in sources, "Export omitted the role snapshot source: " + name
        assert sources[name] == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
