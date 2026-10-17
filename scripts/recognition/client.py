"""Thin HTTP client for a running ``career-lab serve``: the same calls the workbench makes.

Used by the recognition smoke check and the strategy runner. Every write goes through
the public envelope (``request_id``, ``operation``, ``payload``, expected versions), so a
session driven from here is indistinguishable from one driven from the browser.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

DEFAULT_API = "http://127.0.0.1:18562"


class Session:
    def __init__(self, api: str, language: str, scenario: str = "pm_pilot_v2") -> None:
        self.http = httpx.Client(base_url=api, timeout=120.0, trust_env=False)
        response = self.http.post(
            "/sessions",
            json={"schema_version": 2, "scenario": scenario, "work_language": language},
        )
        response.raise_for_status()
        body = response.json()
        self.language = language
        self.session_id: str = body["session_id"]
        self.headers = {"Authorization": "Bearer " + body["token"]}
        self.request_ids: list[str] = []

    def path(self, suffix: str) -> str:
        return "/sessions/" + self.session_id + ("/" + suffix if suffix else "")

    def get(self, suffix: str, **params: Any) -> dict[str, Any]:
        response = self.http.get(self.path(suffix), headers=self.headers, params=params or None)
        response.raise_for_status()
        return response.json()

    def state(self) -> dict[str, Any]:
        return self.get("")["state"]

    def send(
        self, suffix: str, operation: str, payload: dict[str, Any], request: str | None = None
    ) -> dict[str, Any]:
        state = self.state()
        request = request or operation.replace(".", "-") + "-" + uuid.uuid4().hex[:10]
        response = self.http.post(
            self.path(suffix),
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": request,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"{operation} {response.status_code}: {response.text[:800]}")
        self.request_ids.append(request)
        body = response.json()
        body["_request_id"] = request
        return body

    # ---- workbench verbs -------------------------------------------------------------

    def materials(self) -> list[dict[str, Any]]:
        return self.get("materials")["materials"]

    def read(self, material_id: str, version: int = 1) -> dict[str, Any]:
        return self.send(
            "actions",
            "read_material",
            {
                "tool": "read_material",
                "material": {
                    "schema_version": 2,
                    "session_id": self.session_id,
                    "kind": "material",
                    "object_id": material_id,
                    "version": version,
                },
            },
        )

    def draft(self, content: str, evidence_refs: list[dict[str, Any]], title: str = "Decision"):
        made = self.send(
            "work-products",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": title,
                "content": content,
                "evidence_refs": evidence_refs,
            },
        )
        return next(ref for ref in made["objects"] if ref["kind"] == "product")

    def test(self, query: str, config_version: int = 0) -> dict[str, Any]:
        return self.send(
            "tests", "tests.create", {"query": query, "config_version": config_version}
        )

    def ask(self, role_id: str, text: str) -> dict[str, Any]:
        return self.send("turns", "turns.create", {"role_id": role_id, "text": text})

    def objects(self, kind: str) -> list[dict[str, Any]]:
        rows = self.get("timeline")
        # The envelope nests twice: {"result": {"result": {...}}}.
        while "objects" not in rows and isinstance(rows.get("result"), dict):
            rows = rows["result"]
        return [o for o in rows.get("objects", []) if o["ref"]["kind"] == kind]

    def submit(self, products: list[dict[str, Any]], decision: str = "defer_with_conditions"):
        return self.send(
            "submissions", "submissions.create", {"decision": decision, "products": products}
        )

    def wait_request(self, request_id: str, timeout: float = 300.0) -> dict[str, Any]:
        """Poll a request until every job it queued has finished."""
        deadline = time.monotonic() + timeout
        while True:
            restored = self.get("requests/" + request_id)
            jobs = restored.get("jobs") or []
            if jobs and all(job["status"] in {"completed", "failed", "dead"} for job in jobs):
                return restored
            if time.monotonic() > deadline:
                raise TimeoutError(f"request {request_id} still running: {jobs}")
            time.sleep(1.0)

    def feedback(self, submission_id: str) -> dict[str, Any]:
        return self.get("feedback/" + submission_id)

    def close(self) -> None:
        self.http.close()
