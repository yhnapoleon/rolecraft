"""A local HTTP server, real store and worker inputs for reference-runner tests."""

import json
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI
from test_bundle_registry_flow import write_json

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.core import FileRef
from career_lab.contracts.v2.research import RunManifest, RuntimeBundle
from career_lab.registry.v3.store import BundleRegistry
from career_lab.scenarios.v2.module import ScenarioModule


@dataclass
class LiveRun:
    app: FastAPI
    arguments: dict[str, object]
    token: str = field(repr=False)


@contextmanager
def live_run(
    tmp_path: Path, operation: Literal["reviews.create", "tests.create"] = "reviews.create"
) -> Iterator[LiveRun]:
    root = Path(__file__).resolve().parents[2]
    index = json.loads((root / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    scenario = root / index["main"]["zh"]["root"]
    module = ScenarioModule(scenario)
    database = tmp_path / "http.db"
    app = create_runtime_app("sqlite:///" + str(database), scenario_root=scenario)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("test server failed to start")
            time.sleep(0.01)
        with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
            created = client.post(
                "/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"}
            )
            assert created.status_code == 200
            session = created.json()
            sid = session["session_id"]
            owner = app.state.v2_store.authenticate(sid, session["token"])
            token = app.state.v2_store.reference_agent_token(owner)
            auth = app.state.v2_store.authenticate(sid, token)
            headers = {"Authorization": "Bearer " + token}
            response = client.post(
                "/sessions/" + sid + "/work-products",
                headers=headers,
                json={
                    "schema_version": 2,
                    "operation": "work_products.create",
                    "request_id": "source",
                    "expected_version": 0,
                    "expected_workspace_revision": 0,
                    "payload": {"kind": "text", "purpose": "exploration", "content": "先核对来源"},
                },
            )
            assert response.status_code == 200, response.text
            subject = response.json()["result"]["ref"]
        source = tmp_path / "source"
        shutil.copytree(scenario, source)
        policy = write_json(
            source,
            "reference/checklist.json",
            {
                "schema_version": 2,
                "actions": [
                    {
                        "schema_version": 2,
                        "id": "review",
                        "tool": operation,
                        "purpose": "Review evidence",
                        "arguments": {
                            "subjects": [subject],
                            "purpose": "exploration",
                            "scope": [],
                            "question": "还缺什么依据？",
                        }
                        if operation == "reviews.create"
                        else {"query": "住宿报销上限是多少？", "config_version": 0},
                    }
                ],
            },
        )
        original = RuntimeBundle.model_validate_json(
            (scenario / "runtime/bundle.json").read_bytes()
        )
        runtime = original.model_copy(
            update={"id": "reference-checklist", "tools": policy, "skills": None}
        )
        runtime_ref = write_json(source, "reference/runtime.json", runtime)
        registry_path = tmp_path / "registry"
        registry = BundleRegistry(registry_path)
        runtime_id = registry.register("runtime", source, runtime_ref)
        evaluation_id = registry.register("evaluation", source, module.bindings.evaluation)
        manifest = RunManifest(
            id="http-checklist",
            session_id=sid,
            executor=auth.executor,
            scenario=FileRef(path="manifest.json", sha256=module.package.content_hash),
            runtime=runtime_ref,
            evaluation=module.bindings.evaluation,
            policy=policy,
            seed=1,
            split="regression",
            budget={"actions": 1, "model_calls": 0, "wall_seconds": 60},
            provider="local-checklist",
            model_revision="none",
            source=runtime.source,
            lineage={
                "structure_id": "index_scope_resource_dependency",
                "component_id": "reference-test",
                "session_id": sid,
                "run_id": "http-checklist",
            },
        )
        manifest_path = tmp_path / "run.json"
        manifest_path.write_text(manifest.model_dump_json())
        credentials = tmp_path / "credentials.json"
        credentials.write_text(json.dumps({"api_url": url, "session_id": sid, "token": token}))
        credentials.chmod(0o600)
        yield LiveRun(
            app,
            {
                "manifest_path": manifest_path,
                "registry_path": registry_path,
                "runtime_id": runtime_id,
                "evaluation_id": evaluation_id,
                "database": database,
                "credentials_path": credentials,
                "scenario_root": scenario,
                "output": tmp_path / "run",
            },
            token,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        app.state.store.close()
