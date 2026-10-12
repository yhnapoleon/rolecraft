"""SPLIT-01 and REG-01: moved projections and advice keep their bytes; one registration config.

SPLIT-01 oracles were recorded on the pre-move tree (main d163747) from one real HTTP
review per language; see fixtures/model_assembly/split01-main-d163747.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.modules import JobEnvelope
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.models.v3 import registry
from career_lab.models.v3.consumer import AdviceSource
from career_lab.models.v3.projection import criterion_input, relation_input
from career_lab.models.v3.registry import register_bundle
from scripts.regression.published import write_catalog
from tests.regression.conftest import PublishedSession
from tests.support.model_assembly import fixed_linear_bundle

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads(
    (
        ROOT / "tests/contracts/expansion_v3/fixtures/model_assembly/split01-main-d163747.json"
    ).read_text()
)
CASES = {case["language"]: case for case in GOLDEN["cases"]}
KINDS = [("external", False, "external_candidate"), ("synthetic", True, "synthetic_fixture")]


def recorded(language: str) -> tuple[list[C.EvidencePackageV2], JobEnvelope]:
    case = CASES[language]
    packages = [C.EvidencePackageV2.model_validate(raw) for raw in case["packages"]]
    return packages, JobEnvelope.model_validate(case["envelope"])


def normalized(advice: C.RegisteredModelAdvice) -> str:
    data = advice.model_dump(mode="json")
    if data.get("registration"):
        data["registration"] = dict(
            data["registration"], id="<registration-id>", model_revision="<model-revision>"
        )
    return C.canonical(data)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_split_01_projections_keep_pre_move_input_hashes(language: str) -> None:
    packages, _ = recorded(language)
    supports = [package for package in packages if package.criterion == "R2.support"]
    assert len(supports) == 2 and len(packages) == 28
    assert [C.digest(relation_input(p)) for p in supports] == CASES[language][
        "relation_input_hashes"
    ]
    assert [C.digest(criterion_input(p)) for p in packages] == CASES[language]["export_inputs"]
    projected = criterion_input(supports[0]).evidence
    assert projected.rule_context == {} and projected.rule_bound is None


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize(("name", "fixture", "scope"), KINDS)
def test_split_01_registered_advice_keeps_pre_move_bytes(
    tmp_path: Path, language: str, name: str, fixture: bool, scope: str
) -> None:
    packages, envelope = recorded(language)
    bundle_root, bundle_ref = fixed_linear_bundle(tmp_path, fixture=fixture)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, bundle_root, bundle_ref, scope=scope)
    source = AdviceSource.from_registration(registry, registration, tmp_path / "journal")
    supports = [package for package in packages if package.criterion == "R2.support"]
    produced = [source.relation_advice(p, envelope, language) for p in supports]
    # 148 judges R2.support sentence by sentence (143 §3.5) and lets synthetic
    # registrations show their labels (§5.1 item 2). Only those fields may differ from the
    # pre-move recording: units and aggregation always, label/evidence/citations only for
    # synthetic registrations. Everything else, status and error code included, keeps its
    # bytes; the whole-work input hash stays the read-trace key.
    changed = {"units", "aggregation"}
    if fixture:
        changed |= {"label", "evidence_ids", "citations"}
    assert [
        {k: v for k, v in json.loads(normalized(advice)).items() if k not in changed}
        for advice in produced
    ] == [
        {k: v for k, v in json.loads(oracle).items() if k not in changed}
        for oracle in CASES[language]["advice"][name]
    ]
    # Criterion inference is not part of the move; it stays absent until it is implemented.
    assert all(source.criterion_advice(p, envelope, language) is None for p in packages)
    again = [source.relation_advice(p, envelope, language) for p in supports]
    assert again == produced
    sentences = sum(len(advice.units or ()) for advice in produced)
    assert sentences >= len(supports)
    assert len(list((tmp_path / "journal").glob("*/outcome.json"))) == sentences


# REG-01 ------------------------------------------------------------------------------


@pytest.fixture
def two_registrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    bundle_root, bundle_ref = fixed_linear_bundle(tmp_path / "model", fixture=True)
    registry = tmp_path / "registry"
    ref = register_bundle(registry, bundle_root, bundle_ref, scope="synthetic_fixture")
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(registry))
    monkeypatch.setenv("CAREER_LAB_MODEL_JOURNAL", str(tmp_path / "journal"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    return {
        "CAREER_LAB_MODEL_REGISTRATION": ref.model_dump_json(),
        "CAREER_LAB_MODEL_REGISTRATIONS": json.dumps({"relation": ref.model_dump(mode="json")}),
    }


def test_reg_01_both_registration_variables_refuse_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_registrations: dict[str, str]
) -> None:
    for name, value in two_registrations.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(tmp_path / "refused.db"), provider="local")
    assert refused.value.code == "model_registration_config_ambiguous"
    worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.cli",
            "worker",
            "--once",
            "--database-url",
            "sqlite:///" + str(tmp_path / "cli.db"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert worker.returncode != 0
    assert "model_registration_config_ambiguous" in worker.stderr
    assert not (tmp_path / "journal").exists()


@pytest.mark.parametrize(
    "value",
    ["not-json", json.dumps(["relation"]), json.dumps({"relation": {}, "unknown": {}})],
)
def test_reg_01_malformed_registration_object_refuses_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_registrations: dict[str, str], value: str
) -> None:
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATIONS", value)
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(tmp_path / "refused.db"), provider="local")
    assert refused.value.code == "model_registration_config_invalid"


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize(
    "variable", ["CAREER_LAB_MODEL_REGISTRATION", "CAREER_LAB_MODEL_REGISTRATIONS"]
)
def test_reg_01_relation_registration_reaches_feedback_through_either_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    two_registrations: dict[str, str],
    language: str,
    variable: str,
) -> None:
    monkeypatch.setenv(variable, two_registrations[variable])
    app = create_runtime_app("sqlite:///" + str(tmp_path / "session.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            made = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            ).json()
            session = PublishedSession(
                app,
                client,
                made["session_id"],
                {"Authorization": "Bearer " + made["token"]},
                language,
            )
            transaction = session.send(
                "reviews",
                "review-model",
                "reviews.create",
                {
                    "subjects": [session.work()],
                    "scope": [],
                    "purpose": "commitment",
                    "decision": "defer_with_conditions",
                },
            )
            session.run_job()
            report = session.get("feedback/" + transaction["result"]["review"]["object_id"]).json()[
                "result"
            ]["result"]["items"][0]
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
    (advice,) = report["model_advice"]
    assert advice["status"] == "synthetic_mechanism_only"
    assert advice["registration"]["scope"] == "synthetic_fixture"
    assert set(advice["registration"]) == {"id", "model_revision", "scope", "quality_validated"}
    assert report["provenance"]["registered_model"] == advice["registration"]
    assert "registered_models" not in report["provenance"]


# REG-02 ------------------------------------------------------------------------------


def feedback_report(tmp_path: Path, language: str) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    app = create_runtime_app("sqlite:///" + str(tmp_path / "session.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            made = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            ).json()
            session = PublishedSession(
                app,
                client,
                made["session_id"],
                {"Authorization": "Bearer " + made["token"]},
                language,
            )
            transaction = session.send(
                "reviews",
                "review-model",
                "reviews.create",
                {
                    "subjects": [session.work()],
                    "scope": [],
                    "purpose": "commitment",
                    "decision": "defer_with_conditions",
                },
            )
            session.run_job()
            return session.get("feedback/" + transaction["result"]["review"]["object_id"]).json()[
                "result"
            ]["result"]["items"][0]
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def missing_criterion() -> dict:
    return {"path": "missing/registration.json", "sha256": "c" * 64}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_reg_02_a_criterion_registration_alone_is_parsed_and_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    two_registrations: dict[str, str],
    language: str,
) -> None:
    registry_root = os.environ["CAREER_LAB_MODEL_REGISTRY"]
    monkeypatch.delenv("CAREER_LAB_MODEL_REGISTRY")
    unconfigured = feedback_report(tmp_path / "none", language)
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", registry_root)
    monkeypatch.setenv(
        "CAREER_LAB_MODEL_REGISTRATIONS", json.dumps({"criterion": missing_criterion()})
    )
    criterion_only = feedback_report(tmp_path / "criterion", language)
    assert "model_advice" not in unconfigured and "model_advice" not in criterion_only
    assert set(criterion_only) == set(unconfigured)
    assert criterion_only["provenance"] == unconfigured["provenance"]
    assert not (tmp_path / "journal").exists()


def test_reg_02_a_criterion_key_beside_relation_loads_nothing_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_registrations: dict[str, str]
) -> None:
    real = registry.load_bundle
    loads: list[str] = []

    def counted(*args, **kwargs):
        loads.append("load")
        return real(*args, **kwargs)

    monkeypatch.setattr(registry, "load_bundle", counted)
    relation = json.loads(two_registrations["CAREER_LAB_MODEL_REGISTRATIONS"])
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATIONS", json.dumps(relation))
    single = feedback_report(tmp_path / "single", "en")
    single_loads = len(loads)
    loads.clear()
    both = relation | {"criterion": relation["relation"]}
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATIONS", json.dumps(both))
    paired = feedback_report(tmp_path / "paired", "en")
    assert single_loads > 0 and len(loads) == single_loads
    assert "registered_models" not in paired["provenance"]
    assert [advice["status"] for advice in paired["model_advice"]] == [
        advice["status"] for advice in single["model_advice"]
    ]
    assert paired["provenance"]["registered_model"] == single["provenance"]["registered_model"]
    for broken in ({"criterion": {"path": "x"}}, {"criterion": "not-a-ref"}):
        monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATIONS", json.dumps(relation | broken))
        with pytest.raises(C.ProtocolError) as refused:
            create_runtime_app("sqlite:///" + str(tmp_path / "refused.db"), provider="local")
        assert refused.value.code == "model_registration_config_invalid"
