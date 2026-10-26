"""Extension routes against the real Gateway/store; all content is synthetic."""

import importlib.util
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from career_lab.aipm.install import install_aipm
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import point, record_submission
from career_lab.storage.v2_store import Mutation, ObjectWrite

spec = importlib.util.spec_from_file_location(
    "aipm_w06_fixture", Path(__file__).with_name("test_w06_gateway.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
env = fixture.env


@pytest.fixture
def context(env):
    registry = env["app"].state.gateway.registry
    registry.scenarios["controlled-w06"] = replace(
        registry.scenarios["controlled-w06"], work_language="en"
    )
    install_feedback_recovery(registry)
    install_aipm(env["app"])
    return env


def submit(env):
    store = env["app"].state.v2_store
    command = C.Command.model_validate(
        fixture.command(env, "submit", {"decision": "no_go", "products": []})
    )
    result = store.execute(env["owner"], command, record_submission, capability="submit")
    return next(r for r in result.objects if r.kind == "submission")


def feedback(env, subject, identifier=None):
    store = env["app"].state.v2_store
    view = store.view(env["owner"])
    report = C.FeedbackV2(
        id=identifier or uuid4().hex,
        session_id=env["sid"],
        subject=subject,
        as_of=point(view.state),
        evaluation=view.bindings.evaluation,
        items=(),
        business_response="Not verified",
        next_options=(),
        mode="advisory",
        model_coverage=0,
        verified_coverage=0,
    )
    ref = C.ObjectRef(session_id=env["sid"], kind="feedback", object_id=report.id, version=1)
    cmd = C.Command.model_validate(fixture.command(env, "feedback.create", {}))
    store.execute(
        env["owner"],
        cmd,
        lambda *_: Mutation(
            writes=(
                ObjectWrite(
                    ref=ref,
                    expected_head=0,
                    content=report.model_dump(mode="json"),
                    dependencies=(subject,),
                ),
            )
        ),
        derived_subject=subject,
    )
    return ref


def read(env, subject, token=None):
    return env["client"].get(
        f"/sessions/{env['sid']}/aipm/submissions/{subject.object_id}/versions/{subject.version}/feedback",
        headers={"Authorization": "Bearer " + (token or env["token"])},
    )


def test_exact_feedback_ready_and_not_ready_preserve_window(context):
    ref = submit(context)
    store = context["app"].state.v2_store
    before = store.view(context["owner"]).state
    pending = read(context, ref)
    assert pending.status_code == 200, pending.text
    data = pending.json()["result"]["result"]
    assert data["status"] == "not_ready"
    assert data["feedback_ref"] is data["read"] is data["exact_read"] is None
    assert store.view(context["owner"]).state == before
    old = feedback(context, ref)
    latest = feedback(context, ref)
    assert old != latest
    data = read(context, ref).json()["result"]["result"]
    assert data["feedback_ref"] == latest.model_dump(mode="json")
    assert data["record_ready_is_not_quality_verified"] is True
    assert data["status"] == "ready"
    assert read(context, ref.model_copy(update={"version": 2})).status_code == 404


def test_discovery_requires_both_actions_and_omits_ungranted_exact_read(context):
    ref = submit(context)
    feedback(context, ref)
    actor, _ = fixture.grant(context, allowed_actions=("submissions.list", "feedback.records.read"))
    response = read(context, ref, actor["token"])
    assert response.status_code == 200, response.text
    assert response.json()["result"]["result"]["exact_read"] is None
    actor, _ = fixture.grant(context, allowed_actions=("submissions.list",))
    assert read(context, ref, actor["token"]).status_code == 403
    actor, _ = fixture.grant(context, allowed_objects=("invisible",))
    assert read(context, ref, actor["token"]).status_code == 404


def test_mount_is_idempotent_and_outside_openapi(context):
    app = context["app"]
    count = len(app.routes)
    install_aipm(app)
    assert len(app.routes) == count
    assert not any("/aipm/" in p for p in app.openapi()["paths"])


def test_mcp_feedback_resource_and_tool_use_real_http_projection(context):
    from fastapi.testclient import TestClient

    from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION
    from career_lab.mcp.streamable_http import mount_mcp_http

    mount_mcp_http(context["app"])
    ref = submit(context)
    feedback(context, ref)
    actor, _ = fixture.grant(context, allowed_actions=("submissions.list", "feedback.records.read"))
    client = TestClient(context["app"], base_url="http://127.0.0.1")
    uri = f"rolecraft://sessions/{context['sid']}/submissions/{ref.object_id}/v/1/feedback"

    def call(method, params, name):
        return client.post(
            f"/sessions/{context['sid']}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {**params, "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
            },
            headers={
                "Authorization": "Bearer " + actor["token"],
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MODERN,
                "Mcp-Method": method,
                "Mcp-Name": name,
            },
        )

    resource = call("resources/read", {"uri": uri}, uri)
    assert resource.status_code == 200, resource.text
    import json

    value = json.loads(resource.json()["result"]["contents"][0]["text"])
    assert value == read(context, ref, actor["token"]).json()["result"]["result"]
    # Old-binding session: discovery stays available as a resource; the tool is absent.
    tool = call(
        "tools/call",
        {
            "name": "aipm.context.read",
            "arguments": {
                "kind": "submission_feedback",
                "submission_id": ref.object_id,
                "version": 1,
            },
        },
        "aipm.context.read",
    )
    assert "result" not in tool.json()
    client.close()


def test_persisted_shared_models_register_in_real_store(env):
    from career_lab.aipm import types as T

    store = env["app"].state.v2_store
    for model in (
        T.AipmProfile,
        T.AipmFocus,
        T.AipmStepLink,
        T.AipmDesign,
        T.AipmBatch,
        T.AipmAssessment,
        T.ProcessFeedbackRecord,
    ):
        store.register_object(f"fixture_{model.__name__.lower()}", model)
