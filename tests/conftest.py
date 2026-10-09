from pathlib import Path

import pytest

from career_lab.scenarios.loader import load_scenario


def pytest_configure(config):
    # pytest creates basetemp itself but does not create a missing parent.
    if config.option.basetemp:
        Path(config.option.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def spec():
    return load_scenario(
        Path(__file__).resolve().parents[1] / "scenarios/pm_pilot/v1/scenario.yaml"
    )


@pytest.fixture
def stale_contract_scenario(tmp_path):
    """An intentionally stale contract in an otherwise valid, isolated package.

    Negative binding tests must not depend on the checkout happening to be stale.
    No checked-in/installed package or contract manifest is changed.
    """
    import hashlib
    import json

    from career_lab.scenarios.v2.module import ScenarioModule
    from career_lab.scenarios.v2.seed import build_seed

    root = build_seed(tmp_path / "stale-contract-scenario")
    ScenarioModule(root)  # Prove the positive fixture before making one field stale.
    source = root / "runtime/source-files.json"
    data = json.loads(source.read_text())
    data["foundation_contract_sha256"] = "0" * 64
    source.write_text(json.dumps(data))
    runtime = root / "runtime/bundle.json"
    data = json.loads(runtime.read_text())
    data["source"]["overlay"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    runtime.write_text(json.dumps(data))
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text())
    for ref in data["files"]:
        if ref["path"] in ("runtime/source-files.json", "runtime/bundle.json"):
            ref["sha256"] = hashlib.sha256((root / ref["path"]).read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    return root


@pytest.fixture(autouse=True)
def local_credential_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests explicitly provision a fake deployment key; production has no default."""
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    monkeypatch.setenv(
        "CAREER_LAB_CREDENTIAL_KEY", "isolated-credential-test-key-not-for-deployment-074"
    )
