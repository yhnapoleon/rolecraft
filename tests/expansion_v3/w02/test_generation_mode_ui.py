"""The v4 host shows each saved answer's own mode; generation keeps freshness warnings."""

import json
from contextlib import contextmanager
from json import dumps, loads
from pathlib import Path
from secrets import token_hex

import httpx
import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.evidence.v2.ports import DEFAULT_POLICIES
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.jobs.worker import Worker
from career_lab.scenarios.v2.localization import text as localized_text

QUESTION = {"zh": "住宿报销上限是多少？", "en": "What is the hotel reimbursement limit?"}
# The fact producer's hotel-limit question; it retrieves the limit paragraph in both languages.
RETEST = {"zh": "住宿报销上限是多少？", "en": "What is the hotel reimbursement limit per night?"}
MISS = {"zh": "公司年会在哪个城市举办？", "en": "Which city hosts the annual company party?"}
GENERATED = {"zh": "生成：住宿上限见政策。", "en": "Generated: see the hotel policy."}


class FakeProvider:
    """Loopback-free transport double; records each request body and never retries."""

    def __init__(self, language: str):
        self.language = language
        self.calls: list[dict] = []
        self.behavior = "ok"

    def __call__(self, url, *, headers, json, timeout):
        self.calls.append(json)
        if self.behavior == "error":
            return httpx.Response(500, json={"error": "controlled failure"})
        candidates = loads(json["messages"][1]["content"])["candidates"]
        content = {"answer": GENERATED[self.language], "citation_ids": [candidates[0]["id"]]}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": dumps(content)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            },
        )


@pytest.fixture(params=["zh", "en"])
def language(request) -> str:
    return request.param


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str):
    root = Path(__file__).resolve().parents[3]
    catalog = json.loads((root / "tests/regression/published-catalog.json").read_text())
    for entry in catalog["scenarios"]:
        entry["root"] = str(root / entry["root"])
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    key_file = tmp_path / "provider.key"
    key_file.write_text("sk-" + token_hex(24))
    monkeypatch.setenv("CAREER_LAB_KEY_FILE", str(key_file))
    monkeypatch.setenv("CAREER_LAB_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CAREER_LAB_MODEL", "controlled-mode-model")
    fake = FakeProvider(language)
    monkeypatch.setattr(httpx, "post", fake)
    return tmp_path / "mode.db", fake


@contextmanager
def deployment(database: Path, provider: str):
    app = create_runtime_app("sqlite:///" + str(database), provider=provider)
    try:
        with TestClient(app) as client:
            yield app, client
    finally:
        app.state.store.close()


class Session:
    def __init__(self, client: TestClient, session: dict):
        self.client, self.id, self.token = client, session["session_id"], session["token"]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.token}

    def on(self, client: TestClient) -> "Session":
        return Session(client, {"session_id": self.id, "token": self.token})

    def post(self, path: str, key: str, operation: str, payload: dict):
        state = self.client.get("/sessions/" + self.id, headers=self.headers).json()["state"]
        return self.client.post(
            "/sessions/" + self.id + "/" + path,
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": key,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )

    def workbench(self) -> dict:
        response = self.client.get("/sessions/" + self.id + "/workbench", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()["result"]["result"]

    def configure(self, key: str, settings: dict):
        config = self.workbench()["timeline"]["workspace"]["config"]
        base = {
            "session_id": self.id,
            "kind": "config",
            "object_id": config["id"],
            "version": config["version"],
            "config_version": config["config_version"],
        }
        return self.post(
            "configuration", key, "configuration.apply", {"base": base, "settings": settings}
        )

    def ask(self, key: str, query: str):
        version = self.workbench()["state"]["config_version"]
        response = self.post(
            "tests", key, "tests.create", {"query": query, "config_version": version}
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    def tests(self) -> dict[str, dict]:
        return {
            row["ref"]["object_id"]: row
            for row in self.workbench()["timeline"]["objects"]
            if row["ref"]["kind"] == "test"
        }


def start(client: TestClient, language: str) -> Session:
    response = client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
    )
    assert response.status_code == 200, response.text
    return Session(client, response.json())


def run_worker(app) -> None:
    assert Worker(app.state.jobs, app.state.handlers).run_once()


def latest(session: Session) -> dict:
    rows = session.tests()
    return max(rows.values(), key=lambda row: row["content"]["as_of"]["business_seq"])


def test_unconfigured_deployment_projects_extractive_records(environment, language):
    database, fake = environment
    with deployment(database, "local") as (_, client):
        session = start(client, language)
        session.ask("extractive", QUESTION[language])
        context = session.workbench()
        assert context["semantic"]["assistant"] == "waiting_model"
        row = latest(session)
        assert row["assistant"] == {
            "mode": "extractive",
            "provider": None,
            "model_revision": None,
            "config_version": row["content"]["config_ref"]["config_version"],
        }
    assert fake.calls == []


def test_configured_deployment_projects_each_saved_mode(environment, language):
    database, fake = environment
    with deployment(database, "openai") as (app, client):
        session = start(client, language)
        session.ask("before-llm", QUESTION[language])
        extractive = latest(session)
        assert session.configure("llm", {"generator": "llm"}).status_code == 200
        assert session.ask("generated", QUESTION[language])["status"] == "queued"
        run_worker(app)
        fake.behavior = "error"
        session.ask("failed", QUESTION[language])
        run_worker(app)
        assert session.ask("rule-guard", MISS[language])["status"] == "queued"
        run_worker(app)
        context = session.workbench()
        rows = session.tests()
    assert context["semantic"]["assistant"] == "model"
    modes = sorted(
        (row["content"]["as_of"]["business_seq"], row["assistant"]["mode"]) for row in rows.values()
    )
    assert [mode for _, mode in modes] == ["extractive", "llm", "failed", "extractive"]
    assert rows[extractive["ref"]["object_id"]]["assistant"]["provider"] is None
    generated = next(row for row in rows.values() if row["assistant"]["mode"] == "llm")
    assert generated["assistant"]["provider"] == "openai"
    assert generated["assistant"]["model_revision"] == "controlled-mode-model"
    assert generated["assistant"]["config_version"] == 1
    assert generated["content"]["answer"] == GENERATED[language]
    # The rule guard kept the extractive path's own answer and never called the provider.
    assert len(fake.calls) == 2


def test_unavailable_generation_is_projected_from_its_record(environment, language):
    database, fake = environment
    with deployment(database, "openai") as (_, client):
        session = start(client, language)
        assert session.configure("llm", {"generator": "llm"}).status_code == 200
    with deployment(database, "local") as (_, client):
        local = session.on(client)
        assert local.ask("unavailable", QUESTION[language])["test"]["status"] == "failed"
        context = local.workbench()
        row = latest(local)
    assert context["semantic"]["assistant"] == "waiting_model"
    assert row["assistant"]["mode"] == "unavailable"
    assert fake.calls == []


def test_learner_resets_generator_to_extractive_without_provider(environment, language):
    database, fake = environment
    with deployment(database, "openai") as (_, client):
        session = start(client, language)
        assert session.configure("llm", {"generator": "llm"}).status_code == 200
    with deployment(database, "local") as (_, client):
        local = session.on(client)
        before = local.workbench()["timeline"]["workspace"]["config"]
        response = local.configure("reset", {"generator": "extractive"})
        assert response.status_code == 200, response.text
        after = local.workbench()["timeline"]["workspace"]["config"]
        assert "generator" not in after
        assert after["version"] == before["version"] + 1
        assert after["config_version"] == before["config_version"] + 1
        result = local.ask("after-reset", QUESTION[language])["test"]
        row = latest(local)
    assert result["status"] in {"answered", "answered_with_warning"}
    assert result["execution"]["attempts"] == []
    assert row["assistant"]["mode"] == "extractive"
    assert fake.calls == []


def test_generated_answer_keeps_stale_source_warning(environment, language):
    database, fake = environment
    with deployment(database, "openai") as (app, client):
        session = start(client, language)
        session.ask("initial", QUESTION[language])
        response = session.configure("warn", {"freshness_guard": "warn", "generator": "llm"})
        assert response.status_code == 200, response.text
        workspace = session.workbench()["timeline"]["workspace"]
        assert workspace["source_versions"]["policy"] > workspace["indexed_versions"]["policy"]
        session.ask("stale", QUESTION[language])
        run_worker(app)
        row = latest(session)
    result = row["content"]
    warning = localized_text(language, "stale_warning")
    assert row["assistant"]["mode"] == "llm"
    assert result["status"] == "answered_with_warning"
    assert result["answer"] == warning + GENERATED[language]
    cited = result["citations"][0]
    # The interface marks "cites an older version" from these exact recorded versions.
    assert cited["object_id"] == "policy"
    assert cited["version"] < result["execution"]["source_versions"]["policy"]
    assert len(fake.calls) == 1


def test_evidence_reader_marks_generated_answer_text(environment, language):
    database, _ = environment
    with deployment(database, "openai") as (app, client):
        session = start(client, language)
        session.ask("extractive", QUESTION[language])
        assert session.configure("llm", {"generator": "llm"}).status_code == 200
        session.ask("generated", QUESTION[language])
        run_worker(app)
        rows = session.tests()
        store = app.state.v2_store
        auth = store.authenticate(session.id, session.token)
        reader = StoreEvidenceReader(store, auth, policies=DEFAULT_POLICIES)
    records = {
        record.ref.object_id: record
        for record in reader.records.values()
        if record.ref.kind == "test"
    }
    generated = next(key for key, row in rows.items() if row["assistant"]["mode"] == "llm")
    extractive = next(key for key, row in rows.items() if row["assistant"]["mode"] == "extractive")
    marked = records[generated]
    assert marked.origin == "model_generated"
    assert marked.text.startswith(QUESTION[language])
    assert marked.text.endswith(GENERATED[language])
    marker = marked.text[len(QUESTION[language]) : -len(GENERATED[language])]
    assert ("模型生成" if language == "zh" else "Model-generated") in marker
    plain = records[extractive]
    assert plain.origin == "record"
    assert plain.text == QUESTION[language] + "\n" + rows[extractive]["content"]["answer"]


def submitted_feedback(app, session: Session, language: str) -> dict:
    """Commit one saved work on the current configuration and read its stored feedback."""
    made = session.post(
        "work-products",
        "commit-work",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "commitment",
            "title": "试点决定" if language == "zh" else "Pilot decision",
            "content": "复测后上线。" if language == "zh" else "Launch after the retest.",
        },
    )
    assert made.status_code == 200, made.text
    product = next(ref for ref in made.json()["objects"] if ref["kind"] == "product")
    config = session.workbench()["timeline"]["workspace"]["config"]
    base = {
        "session_id": session.id,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    saved = session.post(
        "submissions",
        "submit",
        "submissions.create",
        {"decision": "launch", "products": [product], "config": base},
    )
    assert saved.status_code == 200, saved.text
    run_worker(app)
    subject = saved.json()["result"]["submission"]["object_id"]
    response = session.client.get(
        "/sessions/" + session.id + "/feedback/" + subject, headers=session.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["result"]["items"][0]


def test_feedback_keeps_a_generated_retest_pending(environment, language):
    database, fake = environment
    adjustment = {}
    for generator in ("llm", "extractive"):
        with deployment(database, "openai") as (app, client):
            session = start(client, language)
            session.ask("initial", RETEST[language])
            assert session.configure("warn", {"freshness_guard": "warn"}).status_code == 200
            refreshed = session.post(
                "actions", "refresh", "refresh_index", {"tool": "refresh_index"}
            )
            assert refreshed.status_code == 200, refreshed.text
            if generator == "llm":
                assert session.configure("llm", {"generator": "llm"}).status_code == 200
                assert session.ask("retest", RETEST[language])["status"] == "queued"
                run_worker(app)
            else:
                session.ask("retest", RETEST[language])
            retest = latest(session)
        assert retest["assistant"]["mode"] == generator
        # The feedback runs on a deployment without a model, so only rules evaluate.
        with deployment(database, "local") as (app, client):
            report = submitted_feedback(app, session.on(client), language)
        items = {item["criterion"]: item for item in report["items"]}
        adjustment[generator] = items["R5.adjustment"]
        assert "R5.adjustment" in {item["criterion"] for item in report["rule_items"]}
    generated, extractive = adjustment["llm"], adjustment["extractive"]
    assert (generated["label"], generated["source"]) == ("INSUFFICIENT", "pending")
    assert ("模型生成" if language == "zh" else "Model-generated") in generated["explanation"]
    assert GENERATED[language] not in json.dumps(generated["citations"], ensure_ascii=False)
    assert (extractive["label"], extractive["source"]) == ("MET", "verified_rule")
    assert len(fake.calls) == 1
