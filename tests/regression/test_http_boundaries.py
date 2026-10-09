"""Approved HTTP error differences and exact compatibility at production boundaries."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from career_lab.api.feedback import feedback_id
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import ProtocolError
from career_lab.errors import CodedValueError

from .conftest import PublishedSession
from .http_samples import CASES, INTERNAL_CASES, internal_sample, sample

BASELINE = Path(__file__).with_name("http-error-baseline.json")


def response_contract(response: httpx.Response) -> dict[str, object]:
    return {
        "status": response.status_code,
        "body": response.json(),
        "headers": {
            name: response.headers[name]
            for name in ("content-type", "allow", "www-authenticate", "retry-after")
            if name in response.headers
        },
    }


def compatibility_responses(directory: Path) -> dict[str, object]:
    app = create_runtime_app("sqlite:///" + str(directory / "compatibility.db"), provider="local")

    @app.get("/compatibility/protocol")
    def protocol_failure() -> None:
        raise ProtocolError("capability_forbidden", "capability forbidden", 403)

    @app.get("/compatibility/coded")
    def coded_failure() -> None:
        raise CodedValueError(
            "learner request requires a reason", code="reason_required", details={"field": "reason"}
        )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            legacy = client.post("/sessions", json={}).json()
            sid = legacy["session_id"]
            headers = {"Authorization": "Bearer " + legacy["token"]}
            current = client.post(
                "/sessions",
                json={
                    "schema_version": 2,
                    "scenario": "pm_pilot_v2",
                    "work_language": "zh",
                },
            ).json()
            v2_headers = {"Authorization": "Bearer " + current["token"]}
            results = {
                "HTTP-01": client.get("/compatibility/protocol"),
                "HTTP-02": client.get("/compatibility/coded"),
                "HTTP-03": client.post("/sessions", json={"scenario": 7}),
                "HTTP-04": client.post(
                    f"/sessions/{current['session_id']}/work-products",
                    headers=v2_headers,
                    json={
                        "schema_version": 2,
                        "request_id": "invalid-product",
                        "operation": "work_products.create",
                        "expected_version": 0,
                        "expected_workspace_revision": 0,
                        "payload": {},
                    },
                ),
                "HTTP-06": client.get(f"/sessions/{sid}/jobs/missing", headers=headers),
                "HTTP-08-route": client.get("/missing-route"),
                "HTTP-08-method": client.get("/sessions"),
                "HTTP-08-auth": client.get(f"/sessions/{sid}"),
            }
            for key, sources, criterion, evidence in (
                ("HTTP-05", {"known": {"future": {"observed_at_seq": 1}}}, "known", "future"),
                ("HTTP-07-criterion", {"known": {}}, "missing", "evidence"),
                ("HTTP-07-evidence", {"known": {}}, "known", "missing"),
            ):
                app.state.store.save_derived(sid, key, "submission", {"model_revision": "fixture"})
                app.state.store.save_derived(
                    sid,
                    feedback_id(app.state.store, sid, key),
                    "feedback",
                    {"sources": sources, "as_of_seq": 0},
                )
                results[key] = client.get(
                    f"/sessions/{sid}/evidence/{key}/{criterion}/{evidence}", headers=headers
                )
            return {key: response_contract(response) for key, response in results.items()}
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


@pytest.fixture(scope="module")
def observed_compatibility(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return compatibility_responses(tmp_path_factory.mktemp("http-compatibility"))


@pytest.mark.parametrize("case", tuple(json.loads(BASELINE.read_text())))
def test_known_http_error_contracts_are_preserved(
    observed_compatibility: dict[str, object], case: str
) -> None:
    assert observed_compatibility[case] == json.loads(BASELINE.read_text())[case]


def internal_failure_response(directory: Path, error: Exception) -> httpx.Response:
    app = create_runtime_app("sqlite:///" + str(directory / "internal.db"), provider="local")

    @app.get("/internal-failure")
    def broken() -> None:
        raise error

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.get("/internal-failure")
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def test_unclassified_value_error_preserves_parent_422(tmp_path: Path) -> None:
    response = internal_failure_response(tmp_path, ValueError("PRIVATE-EXCEPTION-CONTENT"))
    assert response.status_code == 422
    assert response.json() == {"error": "PRIVATE-EXCEPTION-CONTENT", "code": "invalid_request"}


def test_unclassified_key_error_preserves_parent_404(tmp_path: Path) -> None:
    response = internal_failure_response(tmp_path, KeyError("PRIVATE-INTERNAL-KEY"))
    assert response.status_code == 404
    assert response.json() == {"error": "not found", "code": "not_found"}


def test_unclassified_exception_is_generic_json_500(tmp_path: Path) -> None:
    response = internal_failure_response(tmp_path, RuntimeError("PRIVATE-INTERNAL-DETAIL"))
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"error": "internal server error", "code": "internal_error"}


@pytest.mark.parametrize("failure", [ValueError, KeyError, RuntimeError])
def test_request_logs_contain_only_safe_summary_fields(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: type[Exception]
) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="career_lab.http")
    app = create_runtime_app("sqlite:///" + str(tmp_path / "logs.db"), provider="local")
    status = {ValueError: 422, KeyError: 404, RuntimeError: 500}[failure]
    sentinel = "PRIVATE-TOKEN-PATH-QUERY-BODY-EXCEPTION"

    @app.post("/diagnostic/{private_id}")
    def broken(private_id: str) -> None:
        raise failure(sentinel)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/diagnostic/" + sentinel + "?query=" + sentinel,
                headers={"Authorization": "Bearer " + sentinel, "X-Request-ID": sentinel},
                json={"private_work": sentinel},
            )
            assert response.status_code == status
            if failure is not ValueError:
                assert sentinel not in response.text
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
    records = [record for record in caplog.records if record.name == "career_lab.http"]
    assert len(records) == 2
    messages = [json.loads(record.getMessage()) for record in records]
    assert {message["event"] for message in messages} == {
        "request_completed",
        "internal_failure" if status == 500 else "request_rejected",
    }
    assert len({message["request_id"] for message in messages}) == 1
    allowed = {
        "event",
        "request_id",
        "method",
        "route",
        "status",
        "code",
        "duration_ms",
        "error_type",
        "code_version",
    }
    for record, message in zip(records, messages, strict=True):
        assert set(message) <= allowed
        assert sentinel not in record.getMessage()
        assert record.exc_info is None and record.exc_text is None
        assert message["route"] == "/diagnostic/{private_id}"
        assert message["status"] == status


def test_input_error_logs_classification_without_private_input(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="career_lab.http")
    app = create_runtime_app("sqlite:///" + str(tmp_path / "input-log.db"), provider="local")
    sentinel = "PRIVATE-VALIDATION-INPUT"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/sessions", json={"scenario": {"private": sentinel}})
            assert response.status_code == 422
            assert (
                sentinel in response.text
            )  # The approved request-validation response is unchanged.
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
    records = [record for record in caplog.records if record.name == "career_lab.http"]
    assert len(records) == 2
    messages = [json.loads(record.getMessage()) for record in records]
    assert {message["event"] for message in messages} == {"request_rejected", "request_completed"}
    for record in records:
        assert sentinel not in record.getMessage()
        assert record.exc_info is None and record.exc_text is None


@pytest.mark.parametrize(
    "report",
    [
        {"as_of_seq": 0},
        {"as_of_seq": 0, "sources": []},
        {"as_of_seq": 0, "sources": {"known": {"evidence": {}}}},
    ],
)
def test_corrupt_persisted_evidence_is_internal_error(
    tmp_path: Path, report: dict[str, object]
) -> None:
    app = create_runtime_app("sqlite:///" + str(tmp_path / "corrupt.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post("/sessions", json={}).json()
            sid = created["session_id"]
            app.state.store.save_derived(
                sid, "submission", "submission", {"model_revision": "fixture"}
            )
            app.state.store.save_derived(
                sid, feedback_id(app.state.store, sid, "submission"), "feedback", report
            )
            response = client.get(
                f"/sessions/{sid}/evidence/submission/known/evidence",
                headers={"Authorization": "Bearer " + created["token"]},
            )
            assert response.status_code == 500
            assert response.json() == {"error": "internal server error", "code": "internal_error"}
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def test_internal_model_validation_is_not_a_client_input_error(tmp_path: Path) -> None:
    response = internal_sample(tmp_path, "persisted_state_invalid")
    assert response["status"] == 500
    assert response["body"] == {"error": "internal server error", "code": "internal_error"}


def test_internal_database_failure_rolls_back_without_retry(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import event
    from sqlalchemy.engine import Connection

    session = published_session
    before = session.get("").json()
    products = session.get("work-products").json()
    command = session.command(
        "failed-write",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "exploration",
            "title": "Rollback check",
            "content": "Draft",
        },
    )
    calls = []

    def fail_write(
        conn: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().lower().startswith("insert into v2_objects"):
            calls.append(1)
            raise OSError("PRIVATE-DATABASE-DETAIL")

    engine = session.app.state.v2_store.db.engine
    event.listen(engine, "before_cursor_execute", fail_write)
    try:
        response = session.client.post(
            session.url("work-products"), headers=session.headers, json=command
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail_write)
    assert response.status_code == 500
    assert response.json() == {"error": "internal server error", "code": "internal_error"}
    assert calls == [1]
    assert session.get("").json() == before
    assert session.get("work-products").json() == products
    # Explicitly retry the same request after the failed I/O is repaired.
    retry = session.client.post(session.url("work-products"), headers=session.headers, json=command)
    assert retry.status_code == 200, retry.text


@pytest.mark.parametrize(
    "case",
    [
        "empty_pilot_plan",
        "invalid_object_version",
        "negative_configuration_participants",
    ],
)
def test_nested_client_inputs_keep_original_422(tmp_path: Path, case: str) -> None:
    baseline = json.loads(Path(__file__).with_name("http-input-baseline.json").read_text())
    response = sample(tmp_path, case)
    assert {"status": response["status"], "body": response["body"]} == baseline[case]


@pytest.mark.parametrize(
    "entry",
    ["career_lab.cli", "career_lab.delegations.__main__", "career_lab.scenarios.v2.__main__"],
)
def test_formal_serve_entries_only_emit_whitelisted_logs(tmp_path: Path, entry: str) -> None:
    import subprocess
    import sys

    from scripts.regression.published import write_catalog

    package = json.loads(write_catalog(tmp_path / "catalog.json").read_text())["scenarios"][0][
        "root"
    ]
    program = r"""
import importlib, json, logging, sys
import httpx, uvicorn
from fastapi.testclient import TestClient
entry, database, package = sys.argv[1:]
def run(app, **options):
    sentinel = "PRIVATE-URL-QUERY-CREDENTIAL"
    @app.get("/check/{private_id}")
    def fail(private_id: str):
        raise RuntimeError(sentinel)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/check/" + sentinel + "?token=" + sentinel).status_code == 500
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        client.get("https://example.invalid/" + sentinel + "?token=" + sentinel)
    logging.getLogger("dependency").warning(sentinel)
    print(json.dumps({
        "access_log": options.get("access_log"),
        "log_config": options.get("log_config", "default"),
    }))
    app.state.store.close()
uvicorn.run = run
args = ["--database-url", database]
if entry == "career_lab.cli":
    args = ["serve", *args]
elif entry == "career_lab.delegations.__main__":
    args += ["--scenario-package", package]
else:
    args = ["serve", package, *args]
assert importlib.import_module(entry).main(args) == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", program, entry, "sqlite:///" + str(tmp_path / "serve.db"), package],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PRIVATE-URL-QUERY-CREDENTIAL" not in result.stdout + result.stderr
    options = json.loads(result.stdout.strip())
    assert options == {"access_log": False, "log_config": None}
    records = [json.loads(line) for line in result.stderr.splitlines()]
    assert {record["event"] for record in records} == {"request_completed", "internal_failure"}
    assert all(record["route"] == "/check/{private_id}" for record in records)


@pytest.mark.parametrize("case", (*CASES, *INTERNAL_CASES))
def test_http_matches_fixed_parent_response(tmp_path: Path, case: str) -> None:
    expected = json.loads(Path(__file__).with_name("http-parent-responses.json").read_text())
    if case in INTERNAL_CASES:
        assert expected[case]["status"] in {404, 422}
        assert internal_sample(tmp_path, case) == {
            "status": 500,
            "body": {"error": "internal server error", "code": "internal_error"},
            "headers": {"content-length": "57", "content-type": "application/json"},
        }
    else:
        assert sample(tmp_path, case) == expected[case]
