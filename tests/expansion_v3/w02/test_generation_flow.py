"""Generation behavior through the standard HTTP operations and real worker."""

import json
from datetime import UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app


@pytest.fixture(params=["zh", "en"])
def generation_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    root = Path(__file__).resolve().parents[3]
    catalog = json.loads((root / "tests/regression/published-catalog.json").read_text())
    for entry in catalog["scenarios"]:
        entry["root"] = str(root / entry["root"])
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(catalog_path))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    app = create_runtime_app("sqlite:///" + str(tmp_path / "generation.db"))
    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={
                "schema_version": 2,
                "scenario": "pm_pilot_v2",
                "work_language": request.param,
            },
        )
        assert response.status_code == 200, response.text
        session = response.json()
        yield client, session, request.param
    app.state.store.close()


def headers(session: dict) -> dict[str, str]:
    return {"Authorization": "Bearer " + session["token"]}


def post(client: TestClient, session: dict, path: str, key: str, operation: str, payload: dict):
    state = client.get("/sessions/" + session["session_id"], headers=headers(session)).json()[
        "state"
    ]
    return client.post(
        "/sessions/" + session["session_id"] + "/" + path,
        headers=headers(session),
        json={
            "schema_version": 2,
            "request_id": key,
            "operation": operation,
            "payload": payload,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        },
    )


def set_generator(client: TestClient, session: dict, mode: str = "llm") -> dict:
    response = client.get(
        "/sessions/" + session["session_id"] + "/workbench", headers=headers(session)
    )
    assert response.status_code == 200, response.text
    config = response.json()["result"]["result"]["timeline"]["workspace"]["config"]
    base = {
        "session_id": session["session_id"],
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    response = post(
        client,
        session,
        "configuration",
        "config-" + str(config["version"]),
        "configuration.apply",
        {"base": base, "settings": {"generator": mode}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_gen_01_unconfigured_generation_is_saved_without_extractive_success(generation_api):
    client, session, language = generation_api
    set_generator(client, session)
    response = post(
        client,
        session,
        "tests",
        "unconfigured",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]["test"]
    assert result["status"] == "failed"
    assert result["error_code"] == "assistant_model_unavailable"
    assert result["execution"]["attempts"] == []
    assert result["citations"] == []
    assert result["config"]["requested"]["generator"] == "llm"
    assert ("等待模型接入" if language == "zh" else "Awaiting model connection") in result["answer"]
    saved = client.get("/sessions/" + session["session_id"] + "/tests", headers=headers(session))
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["result"]["tests"] == [result]


@pytest.fixture(params=["zh", "en"])
def configured_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    import json as jsonlib
    from secrets import token_hex

    import httpx

    from career_lab.api.app import create_app
    from career_lab.api.modules import ExtensionRegistry
    from career_lab.api.v4_config import install_settings
    from career_lab.api.vertical_runtime import configured_models, default_installed_scenario
    from career_lab.scenarios.v2.module import ScenarioModule

    calls = []

    def transport(url, *, headers, json, timeout):
        calls.append(json)
        prompt = jsonlib.loads(json["messages"][1]["content"])
        citation_id = prompt["candidates"][0]["id"]
        answer = "住宿上限为 500 元。" if request.param == "zh" else "The hotel limit is 500 yuan."
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": jsonlib.dumps(
                                {
                                    "answer": answer,
                                    "citation_ids": [citation_id],
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 32, "completion_tokens": 12},
            },
        )

    monkeypatch.setattr(httpx, "post", transport)
    key_file = tmp_path / "provider.key"
    key_file.write_text("sk-" + token_hex(24))
    monkeypatch.setenv("CAREER_LAB_KEY_FILE", str(key_file))
    monkeypatch.setenv("CAREER_LAB_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CAREER_LAB_MODEL", "controlled-mechanism")
    model, _ = configured_models("openai")
    module = ScenarioModule(default_installed_scenario(), work_language=request.param, model=model)
    registry = module.install(ExtensionRegistry())
    install_settings(registry, module)
    app = create_app(
        "sqlite:///" + str(tmp_path / "configured.db"), model=model, extensions=registry
    )
    with TestClient(app) as client:
        response = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        assert response.status_code == 200, response.text
        session = response.json()
        config = module.package.baseline(session["session_id"]).model_dump(mode="json")
        response = post(
            client,
            session,
            "actions",
            "config",
            "apply_config",
            {
                "tool": "apply_config",
                "config": config | {"generator": "llm", "version": 2, "config_version": 1},
            },
        )
        assert response.status_code == 200, response.text
        yield app, client, session, request.param, calls
    app.state.store.close()


def test_gen_02_candidate_citations_are_openable(configured_api):
    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api
    response = post(
        client,
        session,
        "tests",
        "generated",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "queued"
    assert calls == []
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    response = client.get("/sessions/" + session["session_id"] + "/tests", headers=headers(session))
    assert response.status_code == 200, response.text
    data = response.json()["result"]["result"]
    assert len(data["tests"]) == 1, data
    result = data["tests"][0]
    assert result["status"] == "answered"
    assert len(calls) == 1
    assert result["execution"]["attempts"][0]["provider"] == "openai"
    assert result["execution"]["attempts"][0]["model_revision"] == "controlled-mechanism"
    assert result["citations"][0]["object_id"] == "policy"
    assert result["citations"][0]["version"] == 1
    metadata = data["generations"][0]
    assert metadata["mode"] == "llm"
    assert metadata["work_language"] == language
    assert metadata["prompt_revision"] == "assistant-generation-v1"
    assert metadata["config_ref"] == result["config_ref"]
    cited = result["citations"][0]
    read = post(
        client,
        session,
        "actions",
        "open-citation",
        "read_material",
        {
            "tool": "read_material",
            "material": {
                key: cited[key]
                for key in ("session_id", "kind", "object_id", "version", "config_version")
            },
        },
    )
    assert read.status_code == 200, read.text
    assert cited["quote"] in "".join(
        fragment["text"] for fragment in read.json()["result"]["fragments"]
    )


def test_gen_04_failed_generation_is_immutable_on_reads_and_worker_takeover(
    configured_api, monkeypatch
):
    import httpx

    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api

    def timeout(url, **kwargs):
        calls.append(kwargs["json"])
        raise httpx.ReadTimeout("controlled transport timeout")

    monkeypatch.setattr(httpx, "post", timeout)
    response = post(
        client,
        session,
        "tests",
        "timeout",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    worker = Worker(app.state.jobs, app.state.handlers)
    assert worker.run_once()
    result = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]["tests"][0]
    assert result["status"] == "failed"
    assert result["error_code"] == "assistant_generation_failed"
    for _ in range(2):
        read = client.get(
            "/sessions/" + session["session_id"] + "/requests/timeout", headers=headers(session)
        )
        assert read.status_code == 200, read.text
        assert not Worker(app.state.jobs, app.state.handlers).run_once()
        assert client.get(
            "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
        ).json()["result"]["result"]["tests"] == [result]
    assert len(calls) == 1
    retry = post(
        client,
        session,
        "tests",
        "explicit-new-attempt",
        "tests.create",
        {
            "query": result["query"],
            "config_version": 1,
        },
    )
    assert retry.status_code == 200, retry.text
    assert worker.run_once()
    results = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]["tests"]
    assert len(results) == 2
    assert results[0] == result
    assert len(calls) == 2


@pytest.mark.parametrize("citation", ["unknown-candidate", "policy:2", "tech_private:1"])
def test_gen_02_rejects_whole_answer_with_any_non_candidate_reference(
    configured_api, monkeypatch, citation
):
    import httpx

    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api

    def invalid(url, **kwargs):
        payload = kwargs["json"]
        calls.append(payload)
        candidate = json.loads(payload["messages"][1]["content"])["candidates"][0]["id"]
        content = json.dumps(
            {
                "answer": "malicious answer must never be saved",
                "citation_ids": [candidate, citation],
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(httpx, "post", invalid)
    response = post(
        client,
        session,
        "tests",
        "invalid-reference",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
            "declared_expected": "DO_NOT_SEND_EXPECTED_ANSWER",
        },
    )
    assert response.status_code == 200, response.text
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    data = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]
    result = data["tests"][0]
    assert result["status"] == "failed"
    assert result["citations"] == []
    assert "malicious answer" not in result["answer"]
    assert data["generations"][0]["mode"] == "failed"
    assert len(calls) == 1
    sent = json.dumps(calls)
    assert "DO_NOT_SEND_EXPECTED_ANSWER" not in sent
    assert "tech_private" not in sent
    assert "gold" not in sent


def test_gen_03_unapproved_realtime_uses_effective_index(configured_api):
    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api
    root = app.state.extensions.scenarios["pm_pilot_v2"].baseline_config
    config = root.model_dump(mode="json") | {
        "session_id": session["session_id"],
        "version": 3,
        "config_version": 2,
        "generator": "llm",
        "update_strategy": "realtime",
        "work_items": ["realtime_sync", "human_fallback"],
        "launch_day": 10,
    }
    applied = post(
        client,
        session,
        "actions",
        "request-realtime-config",
        "apply_config",
        {
            "tool": "apply_config",
            "config": config,
        },
    )
    assert applied.status_code == 200, applied.text
    requested = post(
        client,
        session,
        "actions",
        "request-resource",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"dev_days": 6, "deadline_day": 10},
            "reason": "Verify the required resources before enabling realtime updates.",
        },
    )
    assert requested.status_code == 200, requested.text
    response = post(
        client,
        session,
        "tests",
        "before-approval",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 2,
        },
    )
    assert response.status_code == 200, response.text
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    before = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]["tests"][0]
    assert before["config"]["requested"]["update_strategy"] == "realtime"
    assert before["config"]["effective"]["update_strategy"] == "daily"
    assert before["execution"]["source_versions"]["policy"] == 2
    assert before["citations"][0]["version"] == 1
    assert "500" in calls[0]["messages"][1]["content"]
    assert "400" not in calls[0]["messages"][1]["content"]


def test_gen_05_configuration_and_ui_language_do_not_rewrite_old_results(configured_api):
    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api
    response = post(
        client,
        session,
        "tests",
        "original",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    path = "/sessions/" + session["session_id"] + "/tests"
    original = client.get(path, headers=headers(session)).json()["result"]["result"]
    config = original["tests"][0]["config"]["requested"] | {
        "version": 3,
        "config_version": 2,
        "generator": "extractive",
    }
    response = post(
        client,
        session,
        "actions",
        "switch-extractive",
        "apply_config",
        {
            "tool": "apply_config",
            "config": config,
        },
    )
    assert response.status_code == 200, response.text
    changed_ui = client.get(
        path, headers=headers(session) | {"Accept-Language": "en" if language == "zh" else "zh"}
    )
    assert changed_ui.json()["result"]["result"] == original
    second = post(
        client,
        session,
        "tests",
        "second",
        "tests.create",
        {
            "query": original["tests"][0]["query"],
            "config_version": 2,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["result"]["test"]["config_ref"]["config_version"] == 2
    assert second.json()["result"]["test"]["execution"]["attempts"] == []
    assert len(calls) == 1
    assert (
        client.get(path, headers=headers(session)).json()["result"]["result"]["tests"][0]
        == original["tests"][0]
    )


def test_wire_03_default_generator_preserves_old_config_bytes():
    from career_lab.contracts.v2 import AssistantConfig, canonical, digest

    raw = {
        "schema_version": 2,
        "id": "configuration",
        "session_id": "session",
        "version": 1,
        "config_version": 0,
        "domains": ["faq"],
        "scope_filter": True,
        "update_strategy": "daily",
        "fallback": "human",
        "chunk_size": 500,
        "retrieval_limit": 3,
        "min_score": 0.35,
        "min_score_calibration": None,
        "freshness_guard": "none",
        "manual_domains": [],
        "prohibited_topics": [],
        "work_items": [],
        "participants": 0,
        "launch_day": 7,
    }
    decoded = AssistantConfig.model_validate(raw)
    assert decoded.generator == "extractive"
    assert canonical(decoded) == canonical(raw)
    assert digest(decoded) == digest(raw)
    explicit = AssistantConfig.model_validate(raw | {"generator": "extractive"})
    assert explicit.model_dump_json() == decoded.model_dump_json()


def test_gen_04_worker_crash_after_transport_never_calls_again(configured_api, monkeypatch):
    import time

    import httpx

    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api

    def interrupted(url, **kwargs):
        calls.append(kwargs["json"])
        raise SystemExit("simulated worker process termination after transport")

    monkeypatch.setattr(httpx, "post", interrupted)
    response = post(
        client,
        session,
        "tests",
        "interrupted",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    with pytest.raises(SystemExit):
        Worker(app.state.jobs, app.state.handlers).run_once()
    assert len(calls) == 1
    future = time.time() + 120
    monkeypatch.setattr(time, "time", lambda: future)
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    assert len(calls) == 1
    response = client.get(
        "/sessions/" + session["session_id"] + "/requests/interrupted", headers=headers(session)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert response.json()["jobs"][0]["error_code"] == "model_retry_requires_user_action"
    assert response.json()["response"]["result"]["request"]["query"]


def test_gen_04_bad_json_is_not_an_extractive_success(configured_api, monkeypatch):
    import httpx

    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api

    def bad_json(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "{broken"}}]})

    monkeypatch.setattr(httpx, "post", bad_json)
    response = post(
        client,
        session,
        "tests",
        "bad-json",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    data = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]
    assert data["tests"][0]["status"] == "failed"
    assert data["tests"][0]["citations"] == []
    assert data["generations"][0]["mode"] == "failed"
    assert len(calls) == 1


def test_gen_05_queued_request_does_not_adopt_a_restarted_provider(configured_api, monkeypatch):
    from career_lab.api.app import create_app
    from career_lab.api.modules import ExtensionRegistry
    from career_lab.api.vertical_runtime import configured_models, default_installed_scenario
    from career_lab.jobs.worker import Worker
    from career_lab.scenarios.v2.module import ScenarioModule

    app, client, session, language, calls = configured_api
    response = post(
        client,
        session,
        "tests",
        "pinned-provider",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    monkeypatch.setenv("CAREER_LAB_MODEL", "different-model-after-restart")
    model, _ = configured_models("openai")
    module = ScenarioModule(default_installed_scenario(), work_language=language, model=model)
    restarted = create_app(
        str(app.state.store.db.engine.url),
        model=model,
        extensions=module.install(ExtensionRegistry()),
    )
    try:
        assert Worker(restarted.state.jobs, restarted.state.handlers).run_once()
        assert calls == []
        saved = client.get(
            "/sessions/" + session["session_id"] + "/requests/pinned-provider",
            headers=headers(session),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "failed"
        assert saved.json()["jobs"][0]["error_code"] == "assistant_model_changed"
    finally:
        restarted.state.store.close()


def test_gen_02_rule_guard_is_not_reported_as_missing_provider(configured_api):
    from career_lab.jobs.worker import Worker

    app, client, session, language, calls = configured_api
    response = post(
        client,
        session,
        "tests",
        "no-candidates",
        "tests.create",
        {
            "query": "火星天气如何？" if language == "zh" else "What is the weather on Mars?",
            "config_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    data = client.get(
        "/sessions/" + session["session_id"] + "/tests", headers=headers(session)
    ).json()["result"]["result"]
    assert calls == []
    assert data["tests"][0]["error_code"] == "no_retrieval_hit"
    assert data["generations"][0]["mode"] == "failed"
    assert data["generations"][0]["error_code"] == "no_retrieval_hit"


def test_gen_02_scoped_generation_stops_before_transport_until_metadata_scope_is_installed(
    configured_api,
):
    from datetime import datetime, timedelta

    from career_lab.contracts.v2 import DelegationGrant, Executor

    app, client, session, language, calls = configured_api
    store = app.state.v2_store
    owner = store.authenticate(session["session_id"], session["token"])
    config_id = app.state.extensions.scenarios["pm_pilot_v2"].baseline_config.id
    token = store.issue_delegation(
        owner,
        DelegationGrant(
            id="scoped-test",
            session_id=session["session_id"],
            actor_id="learner",
            executor=Executor(
                id="scoped-agent", kind="external_agent", delegation_id="scoped-test"
            ),
            capabilities=("read", "act"),
            allowed_objects=(config_id, "policy"),
            allowed_actions=("tests.create",),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    agent = session | {"token": token}
    response = post(
        client,
        agent,
        "tests",
        "scoped-generation",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "assistant_scoped_generation_unavailable"
    assert calls == []
