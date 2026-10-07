"""Local module CLI integration using synthetic fixtures; no live API/model claims."""
import json
import subprocess
from pathlib import Path
import sys

# Permit isolated integration invocation, independent of pytest collection order.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unit'))
from test_w07_pipeline import make_case
from career_lab.datasets.v3.common import json_bytes


def run(*args):
    return subprocess.run([sys.executable, "-m", "career_lab.datasets.v3", *map(str, args)], capture_output=True, text=True)


def test_cli_export_label_and_validate_fixture_release(tmp_path):
    snapshot, units, policies = make_case(tmp_path)
    data = {"session_id": snapshot.session_id, "actor_id": snapshot.actor_id,
        "point": snapshot.point.model_dump(mode="json"), "source_digest": snapshot.source_digest, "origin": snapshot.origin,
        "objects": [{"ref": x.ref.model_dump(mode="json"), "text": x.text, "available_at": x.available_at.model_dump(mode="json"),
                     "readers": list(x.readers), "usage": x.usage,"validity_known":x.validity_known,"valid_from_seq":x.valid_from_seq,"valid_until_seq":x.valid_until_seq} for x in snapshot.objects]}
    (tmp_path / "snapshot.json").write_bytes(json_bytes(data))
    (tmp_path / "units.json").write_bytes(json_bytes([{"family": u.family, "model_input": u.model_input.model_dump(mode="json"),
        "lineage": u.lineage.model_dump(mode="json"), "provenance": u.provenance.model_dump(mode="json"),"evaluation_time_known":u.evaluation_time_known} for u in units]))
    (tmp_path / "policies.json").write_bytes(json_bytes(policies))
    out = run("export", "--snapshot", tmp_path / "snapshot.json", "--units", tmp_path / "units.json", "--output", tmp_path / "export")
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["records"] == 4
    out = run("label", "prepare", "--export", tmp_path / "export", "--output", tmp_path / "batch", "--annotation-version", "fixture-v1", "--executor-id", "fixture-agent", "--source-root", tmp_path, "--policies", tmp_path / "policies.json")
    assert out.returncode == 0, out.stdout + out.stderr
    out = run("publish", "--export", tmp_path / "export", "--source-root", tmp_path, "--policies", tmp_path / "policies.json", "--output", tmp_path / "release", "--fixture", "--allow-pending")
    assert out.returncode == 0, out.stdout + out.stderr
    out = run("validate-data", "--release", tmp_path / "release")
    assert out.returncode == 0 and json.loads(out.stdout)["records"] == 4
    (tmp_path / "release/records.json").write_text("[]")
    out = run("validate-data", "--release", tmp_path / "release")
    assert out.returncode != 0 and json.loads(out.stdout)["error"] == "file_hash_mismatch"


def test_cli_help_and_missing_arguments():
    assert run("--help").returncode == 0
    assert run("export").returncode != 0


def test_registration_preserves_existing_commands():
    import argparse
    from career_lab.datasets.v3.cli import register_commands, dispatch
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("existing")
    register_commands(commands)
    assert parser.parse_args(["existing"]).command == "existing"
    args = parser.parse_args(["validate-data", "--release", "/missing"])
    assert args.w07_handler is dispatch


def test_cli_invalid_input_error_does_not_echo_private_payload(tmp_path):
    (tmp_path / "snapshot.json").write_text(json.dumps({"origin": "fixture", "objects": [{"ref": {"private-canary": "secret-source-text"}}]}))
    (tmp_path / "units.json").write_text("[]")
    out = run("export", "--snapshot", tmp_path / "snapshot.json", "--units", tmp_path / "units.json", "--output", tmp_path / "export")
    assert out.returncode != 0
    assert "secret-source-text" not in out.stdout + out.stderr
