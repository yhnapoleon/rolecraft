"""The v3 supplementary return package and its standard-library self-check.

The responsible party runs ``python3 -I check_package.py <dir>`` on receipt; these tests run
it the same way. After any edit inside ``docs/data/return-v3/`` regenerate the list::

    cd docs/data/return-v3 && find . -type f ! -name SHA256SUMS ! -name '.*' \\
      ! -path '*/__pycache__/*' | sed 's|^\\./||' | LC_ALL=C sort | xargs shasum -a 256 > SHA256SUMS
"""

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "docs/data/return-v3"
CHECKER = PACKAGE / "check_package.py"
PUBLISHED = {
    "README.md",
    "check_package.py",
    "dataset-split-sealed-v1.md",
    "encoder-pair-aggregate.examples.json",
    "encoder-return.md",
    "fusion-selection.md",
    "linear-return.md",
    "linear-text-v1.golden.jsonl",
    "predictions-v3.md",
    "reference/export_hf_return.py",
    "reference/export_sklearn_linear.py",
    "reference/linear_text_v1.py",
    "test-opening-v1.md",
}


def listed(root=PACKAGE):
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    return [line.split("  ", 1)[1] for line in lines]


def run_check(root):
    result = subprocess.run(
        [sys.executable, "-I", str(CHECKER), str(root)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def codes(summary, path=None):
    return {e["code"] for e in summary["errors"] if path is None or e.get("path") == path}


def write_sums(root):
    names = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS"
    )
    lines = [hashlib.sha256((root / n).read_bytes()).hexdigest() + "  " + n for n in names]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def package_copy(tmp_path):
    """Only the listed files and the list itself, so local clutter cannot leak in."""
    target = tmp_path / "return-v3"
    for name in [*listed(), "SHA256SUMS"]:
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACKAGE / name, target / name)
    return target


def test_pkg_01_published_directory_passes_the_isolated_self_check(tmp_path):
    """Everything in the directory except ``__pycache__``: other tests load the reference
    scripts by file, which writes that (git-ignored) cache when bytecode writing is on."""
    assert set(listed()) == PUBLISHED, "the published file set changed; update PUBLISHED"
    shipped = tmp_path / "return-v3"
    shutil.copytree(PACKAGE, shipped, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    code, summary = run_check(shipped)
    assert summary["errors"] == [], "regenerate SHA256SUMS (see module docstring)"
    assert code == 0 and summary["status"] == "ok"
    assert summary["listed"] == summary["verified"] == len(PUBLISHED)
    assert summary["parsed"] == {"json": 1, "jsonl": 1}


def test_pkg_02_a_one_byte_change_to_any_listed_file_fails(package_copy):
    for name in listed(package_copy):
        path = package_copy / name
        original = path.read_bytes()
        changed = bytearray(original)
        changed[len(changed) // 2] ^= 0x01
        path.write_bytes(bytes(changed))
        code, summary = run_check(package_copy)
        assert code == 1 and summary["status"] == "failed", name
        assert "file_hash_mismatch" in codes(summary, name), name
        path.write_bytes(original)
    assert run_check(package_copy)[0] == 0


@pytest.mark.parametrize(
    "name", [".DS_Store", "reference/.DS_Store", "reference/__pycache__/x.pyc"]
)
def test_pkg_03_an_unlisted_file_fails_including_hidden_ones(package_copy, name):
    (package_copy / name).parent.mkdir(parents=True, exist_ok=True)
    (package_copy / name).write_bytes(b"\x00\x00\x00\x01Bud1")
    code, summary = run_check(package_copy)
    assert code == 1 and codes(summary, name) == {"unlisted_file"}


def test_pkg_04_a_missing_listed_file_fails(package_copy):
    (package_copy / "reference/linear_text_v1.py").unlink()
    code, summary = run_check(package_copy)
    assert code == 1 and codes(summary) == {"file_missing"}


def test_pkg_05_unparsable_json_fails_even_when_the_list_matches(package_copy):
    golden = package_copy / "linear-text-v1.golden.jsonl"
    golden.write_bytes(golden.read_bytes() + b"{not json}\n")
    examples = package_copy / "encoder-pair-aggregate.examples.json"
    examples.write_bytes(b'{"a": 1, "a": 2}\n')
    write_sums(package_copy)
    code, summary = run_check(package_copy)
    assert code == 1
    assert codes(summary) == {"json_invalid"}
    assert {e["path"] for e in summary["errors"]} == {golden.name, examples.name}


@pytest.mark.parametrize(
    "line",
    [
        "0" * 64 + "  ../outside.md",
        "0" * 64 + "  /etc/hosts",
        "0" * 64 + "  SHA256SUMS",
        "0" * 64 + " *README.md",
        "XYZ  README.md",
    ],
)
def test_pkg_06_unsafe_or_malformed_list_entries_fail(package_copy, line):
    sums = package_copy / "SHA256SUMS"
    sums.write_text(sums.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
    code, summary = run_check(package_copy)
    assert code == 1
    assert codes(summary) & {"checksum_line_invalid", "checksum_path_invalid"}


def test_pkg_07_a_symlink_anywhere_fails(package_copy):
    (package_copy / "reference/linked.md").symlink_to(package_copy / "README.md")
    code, summary = run_check(package_copy)
    assert code == 1 and codes(summary, "reference/linked.md") == {"symlink_not_allowed"}


def test_pkg_08_the_checker_imports_only_the_standard_library():
    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }
    assert modules and modules <= sys.stdlib_module_names, modules - sys.stdlib_module_names


def test_pkg_09_readme_links_point_to_listed_files():
    text = (PACKAGE / "README.md").read_text(encoding="utf-8")
    targets = {t.split("#", 1)[0] for t in re.findall(r"\]\(([^)\s]+)\)", text)}
    local = {t for t in targets if t and "://" not in t}
    assert local and local <= set(listed()), local - set(listed())


def option_default(script, command, option):
    """The argparse default of ``option`` in ``script``'s ``command``, read without importing
    it (the encoder reference script imports torch)."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    parsers = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "attr", None) == "add_parser"
        ):
            parsers[node.targets[0].id] = node.value.args[0].value
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "add_argument"
            and parsers.get(getattr(node.func.value, "id", None)) == command
            and node.args
            and node.args[0].value == option
        ):
            defaults = [k.value for k in node.keywords if k.arg == "default"]
            return ast.literal_eval(defaults[0]) if defaults else None
    raise AssertionError(f"{command} {option} not found")


def test_plug_01_encoder_token_limit_defaults_to_the_xlmr_position_limit():
    """160 C3: the normal entry encodes 391-474 tokens per sentence (pair, 150 smoke), so a
    256 default or sample would abstain on every sentence; 512 is XLM-R base's limit."""
    script = PACKAGE / "reference/export_hf_return.py"
    assert option_default(script, "export", "--max-tokens") == 512
    spec = (PACKAGE / "encoder-return.md").read_text(encoding="utf-8")
    samples = re.findall(r"--max-tokens (\d+)", spec)
    assert samples and set(samples) == {"512"}, samples
    assert "391–474" in spec and "不截断" in spec
