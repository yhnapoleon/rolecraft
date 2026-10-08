"""Configuration submission through real HTTP sources and the installed source CLI."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_w13_pack import Session
from test_w13_pack import session as session

from career_lab.contracts.v2.engineer import EngineerSubmissionRecord
from career_lab.engineer.files import encode, file_ref


def prepare(session: Session, changes: dict[str, Any] | None = None) -> tuple[Path, Path]:
    _, _, _, _, _, trial, cli, root, _ = session
    pack = root / "pack"
    result = cli("pack", "--test", trial["id"], "--output", str(pack))
    assert result.returncode == 0, result.stdout + result.stderr
    source = root / "input"
    source.mkdir(exist_ok=True)
    candidate = json.loads((pack / "config.json").read_bytes())
    candidate.update(changes or {})
    raw = encode(candidate)
    (source / "candidate.json").write_bytes(raw)
    (source / "pack.json").write_bytes((pack / "pack.json").read_bytes())
    record = EngineerSubmissionRecord(
        contract_version="engineer-review-v1",
        id="repair-1",
        pack=file_ref("pack.json", (pack / "pack.json").read_bytes()),
        config=file_ref("candidate.json", raw),
        base_config_hash=file_ref("config.json", (pack / "config.json").read_bytes()).sha256,
        regression_report=None,
        unresolved=(),
        explanation="调整配置 / Adjust configuration",
        executor=trial["execution"]["executor"],
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
        work_language="en" if "Mars" in trial["query"] else "zh",
    )
    path = source / "submission.json"
    path.write_bytes(encode(record))
    return pack, path


def submit(session: Session, pack: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return session[6](
        "submit",
        "--pack",
        str(pack),
        "--input",
        str(source),
        "--output",
        str(session[7] / "submissions"),
    )


def test_submission_roundtrip(session: Session) -> None:
    _, client, sid, headers, _, _, _, root, _ = session
    pack, source = prepare(session, {"freshness_guard": "warn"})
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = submit(session, pack, source)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = root / "submissions" / json.loads(result.stdout)["directory"]
    record = EngineerSubmissionRecord.model_validate_json((folder / "submission.json").read_bytes())
    assert record == EngineerSubmissionRecord.model_validate_json(source.read_bytes())
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert submit(session, pack, source).returncode == 0
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"command": "touch /tmp/forbidden"},
        {"code": "print(1)"},
        {"path": "/tmp/file"},
        {"url": "https://example.invalid"},
        {"domains": ["https://example.invalid"]},
        {"work_items": ["shell"]},
        {"retrieval_limit": 21},
        {"min_score": float("inf")},
        {"scope_filter": "false"},
        {"session_id": "someone-else"},
        {"min_score_calibration": {"path": "payload.json", "sha256": "0" * 64}},
    ],
)
def test_submission_rejects_invalid(session: Session, changes: dict[str, Any]) -> None:
    pack, source = prepare(session)
    candidate = json.loads((source.parent / "candidate.json").read_bytes())
    candidate.update(changes)
    raw = json.dumps(candidate).encode()
    (source.parent / "candidate.json").write_bytes(raw)
    record = json.loads(source.read_bytes())
    record["config"] = file_ref("candidate.json", raw).model_dump(mode="json")
    source.write_text(json.dumps(record))
    result = submit(session, pack, source)
    assert result.returncode == 1 and not result.stderr
    assert not (session[7] / "submissions").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_config_hash", "0" * 64),
        ("executor", {"id": "forged", "kind": "human"}),
        ("work_language", "other"),
        ("unresolved", None),
        ("created_at", "2026-10-09T00:00:00"),
    ],
)
def test_submission_rejects_wrong_metadata(session: Session, field: str, value: Any) -> None:
    pack, source = prepare(session)
    record = json.loads(source.read_bytes())
    record[field] = value
    source.write_text(json.dumps(record))
    result = submit(session, pack, source)
    assert result.returncode == 1 and not result.stderr
    assert not (session[7] / "submissions").exists()


def test_submission_conflicts(session: Session) -> None:
    pack, source = prepare(session)
    result = submit(session, pack, source)
    assert result.returncode == 0
    folder = session[7] / "submissions" / json.loads(result.stdout)["directory"]
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    record = json.loads(source.read_bytes())
    record["explanation"] = "Different claim"
    source.write_text(json.dumps(record))
    result = submit(session, pack, source)
    assert result.returncode == 1 and "engineer_submission_conflict" in result.stdout
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original


def test_submission_rejects_changed_references(session: Session) -> None:
    pack, source = prepare(session)
    (source.parent / "candidate.json").write_text("{}")
    result = submit(session, pack, source)
    assert result.returncode == 1 and "file_hash_mismatch" in result.stdout
    assert not (session[7] / "submissions").exists()


def test_submission_current_authorization(session: Session) -> None:
    from datetime import timedelta

    _, _, _, _, send, _, _, _, credentials = session
    pack, source = prepare(session)
    assert submit(session, pack, source).returncode == 0
    grant = send(
        "delegations",
        "limited",
        "delegations.create",
        {
            "agent_label": "limited",
            "capabilities": ["read"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )["result"]["result"]
    value = json.loads(credentials.read_bytes())
    value["token"] = grant["token"]
    credentials.write_text(json.dumps(value))
    denied = submit(session, pack, source)
    assert denied.returncode == 1 and "capability_forbidden" in denied.stdout
    did = grant["delegation"]["id"]
    send(
        "delegations/" + did,
        "revoke",
        "delegations.revoke",
        {"delegation_id": did},
        method="DELETE",
    )
    assert submit(session, pack, source).returncode == 1
