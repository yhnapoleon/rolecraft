"""MODEL-02/03/05/06 through standard HTTP, worker and historical feedback reads."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.registered_models import FeedbackHandler
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.jobs.worker import Worker
from scripts.regression.published import ROOT, write_catalog
from tests.regression.conftest import PublishedSession


@contextmanager
def runtime_session(
    root: Path,
    language: str,
    handler: FeedbackHandler | None = None,
) -> Iterator[PublishedSession]:
    root.mkdir(parents=True, exist_ok=True)
    app = create_runtime_app(
        "sqlite:///" + str(root / "session.db"),
        provider="local",
        feedback_handler=handler,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            made = client.post(
                "/sessions",
                json={
                    "schema_version": 2,
                    "scenario": "pm_pilot_v2",
                    "work_language": language,
                },
            )
            assert made.status_code == 200, made.text
            body = made.json()
            yield PublishedSession(
                app,
                client,
                body["session_id"],
                {"Authorization": "Bearer " + body["token"]},
                language,
            )
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


@pytest.fixture(params=["zh", "en"])
def registered_session(request, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/unit"))
    from test_w08_registration import registered

    model_root = tmp_path / "model"
    model_root.mkdir()
    _, _, ref = registered(model_root)
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(model_root / "registry"))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", ref.model_dump_json())
    monkeypatch.setenv("CAREER_LAB_MODEL_JOURNAL", str(tmp_path / "journal"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    with runtime_session(tmp_path, request.param) as session:
        yield session, ref, tmp_path


def review(session: PublishedSession, request_id: str = "review-model") -> tuple[dict, dict]:
    work = session.work()
    transaction = session.send(
        "reviews",
        request_id,
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    response = session.get("feedback/" + transaction["result"]["review"]["object_id"])
    assert response.status_code == 200, response.text
    return transaction, response.json()["result"]["result"]["items"][0]


def test_model_02_normal_feedback_discloses_synthetic_identity_without_scoring(
    registered_session,
) -> None:
    session, ref, _ = registered_session
    transaction, report = review(session)
    assert report["model_advice"], report
    advice = report["model_advice"][0]
    assert advice["status"] == "synthetic_mechanism_only"
    assert advice["label"] is None and advice["evidence_ids"] == advice["citations"] == []
    assert advice["affects_score"] is False
    assert advice["registration"]["scope"] == "synthetic_fixture"
    assert advice["registration"]["quality_validated"] is False
    assert advice["request_id"] == "review-model"
    recovered = session.get("requests/review-model").json()
    assert advice["job_id"] in {job["job_id"] for job in recovered["jobs"]}
    assert report["provenance"]["registered_model"] == advice["registration"]
    assert all(item["source"] != "model_advice" for item in report["items"])


def test_model_03_read_refresh_and_request_recovery_do_not_repeat_model(registered_session) -> None:
    session, _, root = registered_session
    transaction, report = review(session)
    journals = list((root / "journal").glob("*/outcome.json"))
    assert len(journals) == 1
    before = {path: path.read_bytes() for path in journals}
    for _ in range(3):
        response = session.get("feedback/" + transaction["result"]["review"]["object_id"])
        assert response.json()["result"]["result"]["items"][0] == report
        assert session.get("requests/review-model").status_code == 200
        assert not Worker(session.app.state.jobs, session.app.state.handlers).run_once()
    assert list((root / "journal").glob("*/outcome.json")) == journals
    assert {path: path.read_bytes() for path in journals} == before


def test_model_05_environment_changes_do_not_replace_service_binding(
    registered_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = registered_session
    _, original = review(session)
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", "/unavailable-after-start")
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", "changed-after-start")
    work = original["verified_facts"][0]["subject"]
    transaction = session.send(
        "reviews",
        "next-model",
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    later = session.get("feedback/" + transaction["result"]["review"]["object_id"]).json()[
        "result"
    ]["result"]["items"][0]
    assert later["model_advice"][0]["registration"] == original["model_advice"][0]["registration"]
    assert later["model_advice"][0]["status"] == "synthetic_mechanism_only"
    assert later["model_advice"][0]["request_id"] == "next-model"


def test_model_06_new_feedback_discloses_file_drift_without_erasing_prior_result(
    registered_session,
) -> None:
    session, ref, root = registered_session
    first, original = review(session)
    registration = root / "model/registry" / ref.path
    entry = json.loads(registration.read_text())
    name = next(name for name in entry["files"] if name.endswith(".npz"))
    (registration.parent / "artifact" / name).write_bytes(b"explicit test of file drift")
    work = original["verified_facts"][0]["subject"]
    transaction = session.send(
        "reviews",
        "after-drift",
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    later = session.get("feedback/" + transaction["result"]["review"]["object_id"]).json()[
        "result"
    ]["result"]["items"][0]
    assert later["model_advice"][0]["status"] == "failed"
    assert later["model_advice"][0]["error_code"] == "model_files_changed"
    assert later["rule_items"] == original["rule_items"]
    assert later["verified_coverage"] == original["verified_coverage"]
    assert (
        session.get("feedback/" + first["result"]["review"]["object_id"]).json()["result"][
            "result"
        ]["items"][0]
        == original
    )


def test_explicit_handler_keeps_priority_over_registered_environment(
    registered_session,
    tmp_path: Path,
) -> None:
    from career_lab.contracts import v2 as C

    session, _, _ = registered_session
    calls = []

    def explicit_handler(store, view, envelope, auth):
        calls.append(envelope.origin_request_id)
        raise C.ProtocolError("controlled_feedback_unavailable", status=503)

    with runtime_session(tmp_path / "explicit", session.language, explicit_handler) as explicit:
        work = explicit.work()
        explicit.send(
            "reviews",
            "explicit-review",
            "reviews.create",
            {
                "subjects": [work],
                "scope": [],
                "purpose": "commitment",
                "decision": "defer_with_conditions",
            },
        )
        explicit.run_job()
        assert calls == ["explicit-review"]


def test_model_04_limited_reader_degrades_advice_without_rewriting_saved_feedback(
    registered_session,
) -> None:
    from datetime import UTC, datetime, timedelta

    session, _, root = registered_session
    _, original = review(session)
    traces = original["read_boundaries"]
    model_trace = next(trace for trace in traces if trace["path"] == "/model_advice/0")
    subject_ids = {row["subject"]["object_id"] for row in original["verified_facts"]}
    hidden = next(
        ref["object_id"]
        for ref in model_trace["dependencies"]
        if ref["object_id"] not in subject_ids
    )
    scope = {original["id"], original["subject"]["object_id"], *subject_ids}
    scope.update(ref["object_id"] for trace in traces for ref in trace["dependencies"])
    before = {str(path): path.read_bytes() for path in (root / "journal").glob("*/outcome.json")}
    for key, allowed in (("full-reader", scope), ("limited-reader", scope - {hidden})):
        issued = session.send(
            "delegations",
            key,
            "delegations.create",
            {
                "agent_label": "Controlled model advice reader",
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                "capabilities": ["read"],
                "allowed_objects": sorted(allowed),
            },
        )["result"]["result"]
        response = session.client.get(
            session.url("feedback-records/" + original["id"]),
            headers={"Authorization": "Bearer " + issued["token"]},
        )
        assert response.status_code == 200, response.text
        report = response.json()["result"]["result"]["feedback"]
        advice = report["model_advice"][0]
        if key == "full-reader":
            assert report == original
        else:
            assert advice["status"] == "unavailable"
            assert advice["error_code"] == "evidence_unavailable"
            assert advice["input_hash"] is None
            assert advice["citations"] == advice["evidence_ids"] == []
            assert advice["registration"] == original["model_advice"][0]["registration"]
            assert len(report["rule_items"]) == len(original["rule_items"])
    assert (
        session.get("feedback-records/" + original["id"]).json()["result"]["result"]["feedback"]
        == original
    )
    assert {
        str(path): path.read_bytes() for path in (root / "journal").glob("*/outcome.json")
    } == before


def test_model_06_missing_registration_preserves_normal_rule_feedback(
    registered_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, ref, root = registered_session
    monkeypatch.setenv(
        "CAREER_LAB_MODEL_REGISTRATION",
        ref.model_copy(
            update={"path": "missing/registration.json"},
        ).model_dump_json(),
    )
    with runtime_session(root / "missing-reference", session.language) as current:
        _, report = review(current)
        advice = report["model_advice"][0]
        assert advice["status"] == "failed" and advice["error_code"] == "model_reference_invalid"
        assert advice["registration"] is None and advice["label"] is None
        assert len(report["items"]) == len(report["rule_items"]) == 14
        assert report["mode"] == "advisory" and report["model_coverage"] == 0


def test_model_06_missing_encoder_dependencies_are_explicit_without_fallback(
    registered_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from test_w08_encoder_registration import encoder_return

    from career_lab.models.v3.registry import register_bundle

    session, _, root = registered_session
    bundle = root / "encoder"
    bundle.mkdir()
    ref = encoder_return(bundle)
    registry = root / "encoder-registry"
    registration = register_bundle(registry, bundle, ref, scope="synthetic_fixture")
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(registry))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", registration.model_dump_json())
    real_import = builtins.__import__

    def missing_dependency(name, *args, **kwargs):
        if name in {"torch", "transformers"}:
            raise ImportError("Controlled optional dependency absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_dependency)
    with runtime_session(root / "missing-dependency", session.language) as current:
        _, report = review(current)
        advice = report["model_advice"][0]
        assert advice["status"] == "failed"
        assert advice["error_code"] == "pretrained_encoder_dependencies_unavailable"
        assert advice["registration"]["id"].startswith("encoder-")
        assert report["provenance"]["registered_model"] == advice["registration"]
        assert len(report["items"]) == 14 and report["mode"] == "advisory"


@pytest.mark.parametrize("failure", [None, "timeout", "infrastructure"])
def test_model_03_restarted_worker_recovers_original_receipt_before_loading(
    registered_session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    import os

    from sklearn.feature_extraction.text import TfidfVectorizer

    from career_lab.jobs.worker import WorkerClaim

    session, ref, root = registered_session
    work = session.work()
    transaction = session.send(
        "reviews",
        "recover-recorded",
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    job = session.app.state.jobs.claim_job("controlled-recovering-worker")
    assert job is not None
    claim = WorkerClaim.from_job(job)
    real_replace = os.replace
    real_transform = TfidfVectorizer.transform
    calls = []

    def model_transport(vectorizer, raw_documents):
        calls.append(True)
        if failure == "timeout":
            raise TimeoutError("Controlled model runtime timeout")
        if failure == "infrastructure":
            raise OSError("Controlled model runtime unavailable")
        return real_transform(vectorizer, raw_documents)

    def stop_after_receipt(source, destination):
        real_replace(source, destination)
        if Path(destination).name == "outcome.json":
            raise SystemExit("Controlled process loss before feedback commit")

    with monkeypatch.context() as fault:
        fault.setattr(TfidfVectorizer, "transform", model_transport)
        fault.setattr(os, "replace", stop_after_receipt)
        with pytest.raises(SystemExit, match="before feedback commit"):
            session.app.state.handlers[job["kind"]](job["payload"], claim)
    journal = next((root / "journal").glob("*/outcome.json"))
    before = journal.read_bytes()
    recorded = json.loads(before)
    registration = root / "model/registry" / ref.path
    entry = json.loads(registration.read_text())
    weight = next(name for name in entry["files"] if name.endswith(".npz"))
    (registration.parent / "artifact" / weight).write_bytes(b"drift after original inference")
    reopened = create_runtime_app("sqlite:///" + str(root / "session.db"), provider="local")
    try:
        result = reopened.state.handlers[job["kind"]](job["payload"], claim)
        assert result["result"]["feedbacks"]
        session.app.state.jobs.complete(job["id"], job["lease_token"], result)
        response = session.get("feedback/" + transaction["result"]["review"]["object_id"])
        assert response.status_code == 200
        report = response.json()["result"]["result"]["items"][0]
        advice = report["model_advice"][0]
        assert advice["registration"]["id"] == recorded["registration"]["id"]
        assert report["provenance"]["registered_model"] == advice["registration"]
        if failure:
            assert advice["status"] == "failed"
            assert advice["error_code"] == (
                "model_timeout" if failure == "timeout" else "model_infrastructure_failed"
            )
        else:
            assert advice["status"] == "synthetic_mechanism_only"
        assert journal.read_bytes() == before
        assert len(list((root / "journal").glob("*/outcome.json"))) == 1
    finally:
        reopened.state.store.close()
        reopened.state.v2_store.db.engine.dispose()


def test_model_03_concurrent_same_request_has_one_job_and_one_model_receipt(
    registered_session,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    session, _, root = registered_session
    work = session.work()
    command = session.command(
        "same-review",
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )

    def post() -> dict:
        response = session.client.post(
            session.url("reviews"), headers=session.headers, json=command
        )
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post)
        second = pool.submit(post)
        responses = (first.result(), second.result())
    assert responses[0]["result"]["review"] == responses[1]["result"]["review"]
    assert sorted(row["replayed"] for row in responses) == [False, True]
    session.run_job()
    recovered = session.get("requests/same-review").json()
    assert len(recovered["jobs"]) == 1 and recovered["jobs"][0]["status"] == "completed"
    report = session.get("feedback/" + responses[0]["result"]["review"]["object_id"]).json()[
        "result"
    ]["result"]["items"][0]
    assert report["model_advice"][0]["job_id"] == recovered["jobs"][0]["job_id"]
    assert len(list((root / "journal").glob("*/outcome.json"))) == 1
    assert not Worker(session.app.state.jobs, session.app.state.handlers).run_once()


def test_model_06_recorded_programming_failure_is_not_reported_as_load_failure(
    registered_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer

    session, _, root = registered_session

    def programming_fault(vectorizer, raw_documents):
        raise RuntimeError("Controlled inference failure")

    monkeypatch.setattr(TfidfVectorizer, "transform", programming_fault)
    _, report = review(session)
    advice = report["model_advice"][0]
    assert advice["status"] == "failed" and advice["error_code"] == "model_prediction_invalid"
    recorded = json.loads(next((root / "journal").glob("*/outcome.json")).read_text())
    assert recorded["failure_kind"] == "programming"
    assert advice["registration"]["id"] == recorded["registration"]["id"]
    assert len(report["rule_items"]) == 14
