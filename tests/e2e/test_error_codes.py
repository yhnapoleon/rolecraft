import pytest
from fastapi.testclient import TestClient

from career_lab.api.app import create_app


PLAN = {
    "participants": 20,
    "knowledge_domains": ["stable_faq"],
    "launch_day": 7,
    "update_strategy": "daily",
    "fallback": "human",
    "work_items": ["scope_filter", "human_fallback"],
}


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'errors.db'}")
    with TestClient(app) as client:
        created = client.post("/sessions", json={}).json()
        sid = created["session_id"]
        headers = {"Authorization": "Bearer " + created["token"]}
        yield app, client, sid, headers
    app.state.store.close()


def post(api, suffix, body):
    _, client, sid, headers = api
    return client.post(f"/sessions/{sid}/{suffix}", headers=headers, json=body)


def action(api, tool, arguments=None, request_id="action", expected_version=None):
    version = (
        api[0].state.store.get_state(api[2]).version
        if expected_version is None
        else expected_version
    )
    return post(
        api,
        "actions",
        {
            "tool": tool,
            "arguments": arguments or {},
            "request_id": request_id,
            "expected_version": version,
        },
    )


def configure(api, **updates):
    response = action(api, "update_pilot", {"plan": {**PLAN, **updates}}, "config")
    assert response.status_code == 200, response.text


def save_artifact(api):
    response = post(api, "artifacts", {"request_id": "artifact", "content": {"goal": "test goal"}})
    assert response.status_code == 200, response.text
    return response.json()


def assert_error(response, code, message, status=422, field="error"):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert response.json()[field] == message


@pytest.mark.parametrize(
    "code,tool,arguments,message",
    [
        (
            "material_unavailable",
            "read_material",
            {"material_id": "tech_private"},
            "material unavailable",
        ),
        (
            "reason_required",
            "request_capacity",
            {"reason": " "},
            "learner request requires a reason",
        ),
        ("invalid_pause_resume", "resume", {}, "invalid pause/resume"),
        (
            "unknown_domain_or_work_item",
            "update_pilot",
            {"plan": {**PLAN, "knowledge_domains": ["unknown"]}},
            "unknown domain or work item",
        ),
        ("invalid_request", "approve_request", {}, "not a public learner action"),
    ],
)
def test_action_error_codes_preserve_messages(api, code, tool, arguments, message):
    assert_error(action(api, tool, arguments), code, message)


def test_version_conflict(api):
    assert_error(
        action(api, "read_material", {"material_id": "brief"}, expected_version=1),
        "version_conflict",
        "expected 1; current 0",
        409,
    )


def test_paused_and_submitted_error_codes(api):
    assert action(api, "pause").status_code == 200
    assert_error(
        action(api, "read_material", {"material_id": "brief"}, "paused"),
        "session_paused",
        "session is paused",
    )
    assert action(api, "resume", request_id="resume").status_code == 200
    configure(api)
    artifact = save_artifact(api)
    assert (
        post(
            api,
            "submissions",
            {"artifact_id": artifact["id"], "config_version": 1, "request_id": "submit"},
        ).status_code
        == 200
    )
    assert_error(
        action(api, "read_material", {"material_id": "brief"}, "submitted"),
        "session_submitted",
        "session is submitted",
    )


def test_config_not_current(api):
    assert_error(
        post(api, "tests", {"query": "Question", "config_version": 0, "request_id": "test"}),
        "config_not_current",
        "config version is not current",
        409,
    )


def test_artifact_config_mismatch(api):
    artifact = save_artifact(api)
    configure(api)
    assert_error(
        post(
            api,
            "submissions",
            {"artifact_id": artifact["id"], "config_version": 1, "request_id": "submit"},
        ),
        "artifact_config_mismatch",
        "artifact/config version mismatch; save a new artifact",
        409,
    )


def test_config_required(api):
    artifact = save_artifact(api)
    assert_error(
        post(
            api,
            "submissions",
            {"artifact_id": artifact["id"], "config_version": 0, "request_id": "submit"},
        ),
        "config_required",
        "configure pilot before submission",
    )


def test_request_unavailable_after_approval(api):
    configure(api, participants=50)
    assert action(api, "request_capacity", {"reason": "Need 50 participants"}).status_code == 200
    assert (
        post(
            api,
            "approvals/resolve",
            {
                "rule_id": "capacity_approved",
                "request_id": "approve",
                "expected_version": api[0].state.store.get_state(api[2]).version,
            },
        ).status_code
        == 200
    )
    assert_error(
        action(api, "request_capacity", {"reason": "Ask again"}, "again"),
        "request_unavailable",
        "request unavailable",
    )


def test_action_request_reuse_code_keeps_conflict_status(api):
    assert action(api, "read_material", {"material_id": "brief"}, "same", 0).status_code == 200
    assert_error(
        action(api, "read_material", {"material_id": "faq"}, "same", 0),
        "request_id_reused",
        "idempotency key reused with different request",
        409,
    )


def test_object_request_reuse_code_keeps_existing_422_status(api):
    save_artifact(api)
    assert_error(
        post(api, "artifacts", {"request_id": "artifact", "content": {"goal": "changed"}}),
        "request_id_reused",
        "request_id reused with different content",
    )


def test_job_request_reuse_code_keeps_existing_422_status(api):
    body = {"role_id": "supervisor", "text": "First question", "request_id": "turn"}
    assert post(api, "turns", body).status_code == 200
    assert_error(
        post(api, "turns", {**body, "text": "Different question"}),
        "request_id_reused",
        "job key conflict",
    )


def test_query_length_code(api):
    assert_error(
        post(api, "tests", {"query": " ", "config_version": 0, "request_id": "test"}),
        "query_length",
        "query length must be 1..4000",
    )


@pytest.mark.parametrize("query", ["", "x" * 4001])
def test_query_schema_length_errors_keep_detail_and_query_code(api, query):
    response = post(api, "tests", {"query": query, "config_version": 0, "request_id": "test"})
    assert response.status_code == 422
    assert response.json()["code"] == "query_length"
    assert isinstance(response.json()["detail"], list)


def test_unknown_scenario_code(api):
    assert_error(
        api[1].post("/sessions", json={"scenario": "missing"}),
        "unknown_scenario",
        "unknown scenario",
    )


def test_unknown_role_code(api):
    assert_error(
        post(api, "turns", {"role_id": "missing", "text": "Question", "request_id": "turn"}),
        "unknown_role",
        "unknown role",
    )


def test_token_codes_keep_detail_messages(api):
    _, client, sid, _ = api
    assert_error(
        client.get(f"/sessions/{sid}"), "token_required", "session token required", 401, "detail"
    )
    assert_error(
        client.get(f"/sessions/{sid}", headers={"Authorization": "Bearer wrong"}),
        "token_invalid",
        "invalid session token",
        401,
        "detail",
    )


def test_relation_not_configured_code(api):
    assert_error(
        post(api, "relation-checks", {"claim": "test", "request_id": "relation"}),
        "relation_not_configured",
        "frozen relation study is not configured",
        503,
        "detail",
    )


def test_not_found_code(api):
    _, client, sid, headers = api
    assert_error(
        client.get(f"/sessions/{sid}/feedback/missing", headers=headers),
        "not_found",
        "not found",
        404,
    )


def test_framework_validation_has_code_without_replacing_detail(api):
    response = post(api, "turns", {"role_id": "supervisor", "text": "Question"})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert isinstance(response.json()["detail"], list)
    assert response.json()["detail"][0]["loc"] == ["body", "request_id"]
