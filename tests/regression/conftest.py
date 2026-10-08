"""Actual shipped six-package runtime with isolated databases and no model calls."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.jobs.worker import Worker
from scripts.regression.published import write_catalog


@dataclass
class PublishedSession:
    app: FastAPI
    client: TestClient
    session_id: str
    headers: dict[str, str]
    language: str

    def get(self, path: str) -> httpx.Response:
        return self.client.get(self.url(path), headers=self.headers)

    def url(self, path: str) -> str:
        return f"/sessions/{self.session_id}/{path}"

    def command(self, key: str, operation: str, payload: dict[str, object]) -> dict[str, object]:
        state = self.get("").json()["state"]
        return {
            "schema_version": 2,
            "request_id": key,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
            "operation": operation,
            "payload": payload,
        }

    def send(
        self, path: str, key: str, operation: str, payload: dict[str, object]
    ) -> dict[str, object]:
        response = self.client.post(
            self.url(path),
            headers=self.headers,
            json=self.command(key, operation, payload),
        )
        assert response.status_code == 200, response.text
        return response.json()

    def work(self) -> dict[str, object]:
        response = self.send(
            "work-products",
            "fixed-work",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": "Pilot decision" if self.language == "en" else "试点决定",
                "content": (
                    "Defer until the owner and scope are verified. Keep human fallback."
                    if self.language == "en"
                    else "负责人和范围核实前暂缓，保留人工兜底。"
                ),
            },
        )
        return next(ref for ref in response["objects"] if ref["kind"] == "product")

    def run_job(self) -> None:
        assert Worker(self.app.state.jobs, self.app.state.handlers).run_once()


@pytest.fixture(params=["zh", "en"])
def published_session(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PublishedSession]:
    catalog = write_catalog(tmp_path / "catalog.json")
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(catalog))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    app = create_runtime_app("sqlite:///" + str(tmp_path / "session.db"), provider="local")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/sessions",
            json={
                "schema_version": 2,
                "scenario": "pm_pilot_v2",
                "work_language": request.param,
            },
        )
        assert response.status_code == 200, response.text
        created = response.json()
        yield PublishedSession(
            app,
            client,
            created["session_id"],
            {"Authorization": "Bearer " + created["token"]},
            request.param,
        )
    app.state.store.close()
    app.state.v2_store.db.engine.dispose()
