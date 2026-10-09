"""Compare a fresh export with every active committed generated artifact."""

from difflib import unified_diff
from pathlib import Path

from career_lab.contracts.v2.export import export

ROOT = Path(__file__).resolve().parents[3]
FREEZE = ROOT / "docs/contracts/expansion-v3"
# Authored inputs and archived drafts are not products of the active exporter.
AUTHORED = {"compatibility.md", "module-interfaces.md", "consumer-request-resolution.json"}


def test_export_reproduces_committed_bytes(tmp_path: Path) -> None:
    export(ROOT, tmp_path)
    expected = {
        path.relative_to(FREEZE).as_posix(): path.read_bytes()
        for path in FREEZE.rglob("*")
        if path.is_file()
        and path.relative_to(FREEZE).parts[0] != "drafts"
        and path.relative_to(FREEZE).as_posix() not in AUTHORED
    }
    actual = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    differences = []
    for name in sorted(expected.keys() | actual.keys()):
        if name not in actual:
            differences.append(f"Missing generated file: {name}")
        elif name not in expected:
            differences.append(f"Unexpected generated file: {name}")
        elif expected[name] != actual[name]:
            differences.append(
                "".join(
                    unified_diff(
                        expected[name].decode("utf-8").splitlines(keepends=True),
                        actual[name].decode("utf-8").splitlines(keepends=True),
                        fromfile=f"committed/{name}",
                        tofile=f"generated/{name}",
                    )
                )
            )
    assert not differences, "Generated artifact drift:\n" + "\n".join(differences)
