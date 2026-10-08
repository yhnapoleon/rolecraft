"""Actual registry and HTTP/worker seams shared by extension consumers."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.modules import ExtensionRegistry, Operation
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import ResourcePage
from career_lab.jobs.worker import Worker


@pytest.mark.parametrize("handler", [None, "module.function"])
def test_wire_05_ready_operation_requires_an_executable_handler(handler: object) -> None:
    registry = ExtensionRegistry()
    with pytest.raises(ValueError, match="callable handler"):
        registry.register(Operation("reviews.read", "read", ResourcePage, handler, mutates=False))
    assert not registry.availability("reviews.read").installed


@pytest.mark.parametrize("language", ["zh", "en"])
def test_standard_review_worker_and_recovery_share_the_installed_gateway(
    tmp_path: Path, language: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    index = json.loads((root / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "entry.db"),
        scenario_root=root / index["main"][language]["root"],
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert created.status_code == 200, created.text
            sid = created.json()["session_id"]
            headers = {"Authorization": "Bearer " + created.json()["token"]}
            prefix = "/sessions/" + sid

            def send(path: str, operation: str, request_id: str, payload: dict) -> dict:
                state = client.get(prefix, headers=headers).json()["state"]
                result = client.post(
                    prefix + path,
                    headers=headers,
                    json={
                        "schema_version": 2,
                        "request_id": request_id,
                        "operation": operation,
                        "payload": payload,
                        "expected_version": state["business_seq"],
                        "expected_workspace_revision": state["workspace_revision"],
                    },
                )
                assert result.status_code == 200, result.text
                return result.json()

            product = send(
                "/work-products",
                "work_products.create",
                "draft",
                {
                    "kind": "text",
                    "purpose": "exploration",
                    "title": "Question" if language == "en" else "问题",
                    "content": "Investigate before deciding"
                    if language == "en"
                    else "先调查，再决定",
                },
            )["result"]["ref"]
            review = send(
                "/reviews",
                "reviews.create",
                "review",
                {
                    "subjects": [product],
                    "purpose": "exploration",
                    "scope": [],
                    "question": "What remains unknown?" if language == "en" else "还有哪些未知？",
                },
            )
            assert review["result"]["feedback_status"] == "queued"
            worker = Worker(app.state.jobs, app.state.handlers)
            assert worker.run_once()
            assert not worker.run_once()
            recovered = client.get(prefix + "/requests/review", headers=headers)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["status"] == "completed", recovered.text
            subject = review["result"]["review"]["object_id"]
            feedback = client.get(prefix + "/feedback/" + subject, headers=headers)
            assert feedback.status_code == 200, feedback.text
            assert feedback.json()["result"]["result"]["items"]
            original = feedback.content
            assert client.get(prefix + "/feedback/" + subject, headers=headers).content == original
            context = client.get(prefix + "/workbench", headers=headers).json()["result"]["result"]
            assert context["semantic"]["feedback"] == "waiting_model"
            assert context["session"]["workLanguage"] == language
            assert client.get(prefix, headers=headers).json()["state"]["status"] == "active"
            app.state.extensions.operations.pop("reviews.read")
            unavailable = client.get(prefix + "/reviews", headers=headers)
            assert unavailable.status_code == 503
            assert unavailable.json()["code"] == "module_unavailable"
    finally:
        app.state.store.close()
