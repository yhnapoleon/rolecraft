"""Standard assembly and fixed submission jobs, with no online provider."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.jobs.worker import Worker
from career_lab.contracts.v2 import ProtocolError


def connect(tmp_path, handler=None):
    app = create_runtime_app("sqlite:///" + str(tmp_path / "vertical.db"), feedback_handler=handler)
    client = TestClient(app)
    r = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
    assert r.status_code == 200, r.text
    session = r.json()
    sid = session["session_id"]
    headers = {"Authorization": "Bearer " + session["token"]}

    def send(path, key, operation, payload):
        state = client.get("/sessions/" + sid, headers=headers).json()["state"]
        body = {
            "schema_version": 2,
            "request_id": key,
            "operation": operation,
            "payload": payload,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        }
        r = client.post("/sessions/" + sid + "/" + path, json=body, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    return app, client, sid, headers, send


def test_standard_registry_scenario_workspace_submission_and_revision(tmp_path):
    app, c, sid, h, send = connect(tmp_path)
    try:
        materials = c.get("/sessions/" + sid + "/materials", headers=h)
        assert materials.status_code == 200, materials.text
        assert materials.json()["result"]["result"]["materials"]
        trial = send(
            "tests", "trial", "tests.create", {"query": "住宿报销上限是多少？", "config_version": 0}
        )
        assert trial["result"]["test"]["citations"][0]["version"] == 1
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {"kind": "text", "title": "调查结论", "content": "先调查，再决定是否试点。"},
        )
        product = next(r for r in made["objects"] if r["kind"] == "product")
        sub = send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [product]},
        )
        saved = sub["result"]["submission"]
        assert sub["result"]["feedback_status"] == "queued"
        listed = c.get("/sessions/" + sid + "/submissions", headers=h).json()["result"]["result"][
            "items"
        ]
        assert listed[0]["products"] == [product]
        revised = send(
            "revision-cycles",
            "revision",
            "begin_revision",
            {"parent_submission": saved, "reason": "补充调查和试用记录"},
        )
        assert revised["state"]["status"] == "active"
        assert (
            c.get("/sessions/" + sid + "/submissions", headers=h).json()["result"]["result"][
                "items"
            ]
            == listed
        )
    finally:
        app.state.store.close()


def test_failed_model_job_never_requeues_automatically(tmp_path):
    calls = []

    def unavailable(store, view, envelope, auth):
        calls.append(envelope.job_id)
        raise ProtocolError("model_transport_failed", status=503)

    app, c, sid, h, send = connect(tmp_path, unavailable)
    try:
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {"kind": "text", "content": "需要核实"},
        )
        product = next(r for r in made["objects"] if r["kind"] == "product")
        submitted = send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "no_go", "products": [product]},
        )
        assert submitted["result"]["feedback_status"] == "queued"
        worker = Worker(app.state.jobs, app.state.handlers)
        assert worker.run_once()
        assert not worker.run_once()
        result = c.get("/sessions/" + sid + "/requests/submit", headers=h)
        assert result.status_code == 200, result.text
        assert result.json()["jobs"][0]["status"] == "failed"
        assert len(calls) == 1
        job_id = result.json()["jobs"][0]["job_id"]
        send("jobs/" + job_id + "/refresh", "retry", "jobs.refresh", {"job_id": job_id})
        assert worker.run_once()
        assert len(calls) == 2
        assert not worker.run_once()
        # Original immutable submission survives a provider failure.
        listed = c.get("/sessions/" + sid + "/submissions", headers=h).json()["result"]["result"][
            "items"
        ]
        assert listed[0]["decision"] == "no_go" and listed[0]["products"] == [product]
    finally:
        app.state.store.close()


def test_runtime_mismatch_is_not_repaired_at_server_start(tmp_path):
    import shutil, json

    root = tmp_path / "scenario"
    shutil.copytree("scenarios/pm_pilot/v2", root)
    path = root / "runtime/source-files.json"
    path.write_text("{}")
    with pytest.raises((ProtocolError, ValueError)):
        create_runtime_app("sqlite:///" + str(tmp_path / "bad.db"), scenario_root=root)
    assert path.read_text() == "{}"


def test_model_lease_recovery_requires_an_explicit_user_retry(tmp_path):
    calls = []

    def handler(store, view, envelope, auth):
        calls.append(envelope.job_id)
        raise ProtocolError("model_transport_failed", status=503)

    app, c, sid, h, send = connect(tmp_path, handler)
    try:
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {"kind": "text", "content": "核实来源"},
        )
        product = next(r for r in made["objects"] if r["kind"] == "product")
        send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "no_go", "products": [product]},
        )
        # Simulate an expired worker claim after a process exit. No second
        # provider call may be started merely because its lease expired.
        crashed = app.state.jobs.claim_job("crashed-worker", lease_seconds=0)
        assert crashed
        worker = Worker(app.state.jobs, app.state.handlers)
        assert worker.run_once()
        assert not calls
        assert app.state.jobs.get(crashed["id"])["error"] == "model_retry_requires_user_action"
        send(
            "jobs/" + crashed["id"] + "/refresh", "retry", "jobs.refresh", {"job_id": crashed["id"]}
        )
        assert worker.run_once() and len(calls) == 1
    finally:
        app.state.store.close()


def test_old_material_and_display_receipts_remain_available_after_submission(tmp_path, monkeypatch):
    from career_lab.api import vertical_runtime
    from career_lab.runtime.model_adapter import LocalModel
    from career_lab.runtime.roles_v2 import LocalRoleModel

    monkeypatch.setattr(
        vertical_runtime, "configured_models", lambda provider: (LocalModel(), LocalRoleModel())
    )
    monkeypatch.setattr(vertical_runtime, "ROLE_RUNTIME_READY", True)
    app, c, sid, h, send = connect(tmp_path)
    try:
        turn = send(
            "turns",
            "question",
            "turns.create",
            {"role_id": "supervisor", "text": "请说明试点约束。"},
        )
        assert Worker(app.state.jobs, app.state.handlers).run_once()
        result = c.get("/sessions/" + sid + "/requests/question", headers=h)
        assert result.status_code == 200, result.text
        assert result.json()["jobs"][0]["status"] == "completed", result.text
        reply = result.json()["jobs"][0]["effect"]["result"]["reply"]
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {"kind": "text", "content": "先核实支持台数据"},
        )
        product = next(r for r in made["objects"] if r["kind"] == "product")
        send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [product]},
        )
        before = c.get("/sessions/" + sid, headers=h).json()["state"]
        material = c.get("/sessions/" + sid + "/objects/material/policy/1", headers=h)
        assert material.status_code == 200, material.text
        assert "500" in str(material.json()["content"])
        assert c.get("/sessions/" + sid, headers=h).json()["state"] == before
        display = send("turns/display", "shown", "turns.display", {"ref": reply})
        assert display["state"]["status"] == "submitted"
        assert display["result"]["display"]["kind"] == "role_display"
        for kind in ["role_context", "scenario_state", "job_context"]:
            assert (
                c.get("/sessions/" + sid + "/objects/" + kind + "/private/1", headers=h).status_code
                == 404
            )
        history = c.get("/sessions/" + sid + "/timeline", headers=h)
        assert history.status_code == 200, history.text
        assert all(
            r["ref"]["kind"] not in {"role_context", "job_context", "scenario_state"}
            for r in history.json()["result"]["result"]["objects"]
        )
    finally:
        app.state.store.close()


def test_w02_evidence_port_uses_actual_historical_config_and_public_sources(tmp_path):
    from career_lab.api.evaluation_runtime import ScenarioEvidencePort
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_lifecycle import point

    app, c, sid, h, send = connect(tmp_path)
    try:
        store = app.state.v2_store
        auth = store.authenticate(sid, h["Authorization"].split(" ", 1)[1])
        port = ScenarioEvidencePort(store, app.state.scenario_v2)
        cfg = app.state.scenario_v2.package.baseline(sid)
        declared = C.EvidenceRefV2(
            session_id=sid,
            kind="config",
            object_id=cfg.id,
            version=cfg.version,
            config_version=cfg.config_version,
            observed_at_seq=0,
        )
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {
                "kind": "text",
                "content": "先核实容量",
                "evidence_refs": [declared.model_dump(mode="json")],
            },
        )
        product = C.ObjectRef.model_validate(
            next(r for r in made["objects"] if r["kind"] == "product")
        )
        formation = point(store.view(auth).state)
        original = port.rules(auth, product, formation)
        values = {f.name: f.value for f in original.facts}
        assert (
            values["participants"] == 20
            and values["capacity"] == 30
            and values["required_dev_days"] == 2
        )
        # The adapter returns actual file text, so absolute source spans remain
        # exact; private material cannot be treated as public evidence.
        capacity = next(
            ref
            for f in original.facts
            if f.name == "capacity"
            for ref in f.sources
            if ref.kind == "material"
        )
        source = port.source(auth, capacity, formation)
        assert source.text and source.ref.object_id == capacity.object_id
        if capacity.quote is not None:
            assert source.text[capacity.span_start : capacity.span_end] == capacity.quote
        with pytest.raises(C.ProtocolError):
            port.source(
                auth,
                C.ObjectRef(session_id=sid, kind="material", object_id="world_private", version=1),
                formation,
            )
        cfg = app.state.scenario_v2.package.baseline(sid).model_dump(mode="json") | {
            "participants": 50,
            "version": 2,
            "config_version": 1,
        }
        send("actions", "apply", "apply_config", {"tool": "apply_config", "config": cfg})
        request = send(
            "actions",
            "ask",
            "request_business",
            {"tool": "request_business", "terms": {"capacity": 60}, "reason": "方案需要50人容量"},
        )
        send(
            "approvals/resolve",
            "approve",
            "resolve_approval",
            {"request": request["result"]["request"], "expected_request_revision": 1},
        )
        now = port.rules(auth, product, point(store.view(auth).state))
        assert {f.name: f.value for f in now.facts}["capacity"] == 60
        assert any(
            ref.kind == "business_decision"
            for ref in next(f for f in now.facts if f.name == "capacity").sources
        )
        still = port.rules(auth, product, formation)
        assert {f.name: f.value for f in still.facts} == values
    finally:
        app.state.store.close()


def test_local_role_followup_after_material_activation_survives_reopen(tmp_path):
    app, c, sid, h, send = connect(tmp_path)
    try:
        cfg = app.state.scenario_v2.package.baseline(sid).model_dump(mode="json") | {
            "participants": 50,
            "version": 2,
            "config_version": 1,
        }
        send("actions", "apply", "apply_config", {"tool": "apply_config", "config": cfg})
        request = send(
            "actions",
            "ask",
            "request_business",
            {"tool": "request_business", "terms": {"capacity": 60}, "reason": "方案需要50人容量"},
        )
        send(
            "approvals/resolve",
            "approve",
            "resolve_approval",
            {"request": request["result"]["request"], "expected_request_revision": 1},
        )
        send(
            "turns",
            "first",
            "turns.create",
            {"role_id": "supervisor", "text": "35-45人、M1-M3与success_metric需要怎样核对？"},
        )
        assert Worker(app.state.jobs, app.state.handlers).run_once()
        first = c.get("/sessions/" + sid + "/requests/first", headers=h).json()
        assert first["jobs"][0]["status"] == "completed", first
        app.state.store.close()
        # Fresh registry/store/runtime reads the first generation from real DB.
        app = create_runtime_app("sqlite:///" + str(tmp_path / "vertical.db"))
        c = TestClient(app)
        state = c.get("/sessions/" + sid, headers=h).json()["state"]
        second = c.post(
            "/sessions/" + sid + "/turns",
            headers=h,
            json={
                "schema_version": 2,
                "request_id": "second",
                "operation": "turns.create",
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
                "payload": {
                    "role_id": "supervisor",
                    "text": "接着讨论35-45人、M1-M3和success_metric。",
                },
            },
        )
        assert second.status_code == 200, second.text
        assert Worker(app.state.jobs, app.state.handlers).run_once()
        result = c.get("/sessions/" + sid + "/requests/second", headers=h).json()
        assert result["jobs"][0]["status"] == "completed", result
        text = result["jobs"][0]["effect"]["result"]["text"]
        assert "success_metric" in text and "M1-M3" in text and "35-45" in text
        assert "等待模型接入" in text
    finally:
        app.state.store.close()


def test_public_event_port_records_real_reads_and_respects_scope(tmp_path):
    from datetime import datetime, timezone, timedelta
    from career_lab.contracts import v2 as C
    from career_lab.api.vertical_reads import public_event_history
    from career_lab.storage.v2_lifecycle import point

    app, c, sid, h, send = connect(tmp_path)
    try:
        store = app.state.v2_store
        auth = store.authenticate(sid, h["Authorization"].split(" ", 1)[1])
        assert (
            c.get("/sessions/" + sid + "/timeline", headers=h).json()["result"]["result"]["events"]
            == []
        )
        send(
            "actions",
            "read-brief",
            "read_material",
            {
                "tool": "read_material",
                "material": C.ObjectRef(
                    session_id=sid, kind="material", object_id="brief", version=1
                ).model_dump(mode="json"),
            },
        )
        first = point(store.view(auth).state)
        send(
            "actions",
            "read-demand",
            "read_material",
            {
                "tool": "read_material",
                "material": C.ObjectRef(
                    session_id=sid, kind="material", object_id="demand", version=1
                ).model_dump(mode="json"),
            },
        )
        old = public_event_history(store, app.state.extensions, auth, first)
        assert (
            len(old) == 1
            and old[0].type == "material_read"
            and old[0].data["material_id"] == "brief"
        )
        grant = C.DelegationGrant(
            id="event-scope",
            session_id=sid,
            actor_id=auth.actor_id,
            executor=C.Executor(
                id="agent-event-reader", kind="external_agent", delegation_id="event-scope"
            ),
            capabilities=("read",),
            allowed_objects=("brief",),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        token = store.issue_delegation(auth, grant)
        headers = {"Authorization": "Bearer " + token}
        scoped = c.get("/sessions/" + sid + "/timeline", headers=headers)
        assert scoped.status_code == 200, scoped.text
        data = scoped.json()["result"]["result"]
        assert len(data["events"]) == 1 and data["events"][0]["data"]["material_id"] == "brief"
        assert "demand" not in str(data) and "workspace" not in data
    finally:
        app.state.store.close()


def test_real_w02_w05_submission_feedback_and_revision(tmp_path):
    from career_lab.contracts import v2 as C

    app, c, sid, h, send = connect(tmp_path)
    try:
        read = send(
            "actions",
            "read",
            "read_material",
            {
                "tool": "read_material",
                "material": C.ObjectRef(
                    session_id=sid, kind="material", object_id="brief", version=1
                ).model_dump(mode="json"),
            },
        )
        made = send(
            "work-products",
            "draft",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": "暂缓建议",
                "content": "先核实支持负担，暂缓开放动态政策回答。",
                "evidence_refs": [read["result"]["fragments"][1]["ref"]],
            },
        )
        product = next(r for r in made["objects"] if r["kind"] == "product")
        submit = send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [product]},
        )
        assert Worker(app.state.jobs, app.state.handlers).run_once()
        result = c.get("/sessions/" + sid + "/requests/submit", headers=h).json()
        assert result["jobs"][0]["status"] == "completed", result
        ref = result["jobs"][0]["effect"]["result"]["feedbacks"][0]
        saved = c.get(
            "/sessions/" + sid + "/feedback-records/" + ref["object_id"], headers=h
        ).json()["result"]["result"]["feedback"]
        assert len(saved["items"]) == 14
        assert saved["verified_facts"] and saved["rule_items"]
        assert any(
            r["verified_ref"] is not None
            for facts in saved["verified_facts"]
            for r in facts["references"]
        )
        assert (
            saved["verified_facts"][0]["activity_totals"]["material_read"]["verified_records"] == 1
        )
        assert saved["verified_facts"][0]["activity_totals"]["material_read"]["status"] == "unknown"
        launch_items = [
            i
            for i in saved["rule_items"]
            if i["criterion"] in {"R3.capacity", "R3.resources", "R4.functional_tests"}
        ]
        assert all(i["label"] == "NOT_APPLICABLE" for i in launch_items)
        send(
            "feedback/" + ref["object_id"] + "/responses",
            "objection",
            "feedback.responses.create",
            {
                "feedback_id": ref["object_id"],
                "feedback_version": 1,
                "kind": "supplement",
                "text": "补充阅读的委托原文",
                "evidence": [read["result"]["fragments"][1]["ref"]],
            },
        )
        send(
            "revision-cycles",
            "revision",
            "begin_revision",
            {"parent_submission": submit["result"]["submission"], "reason": "补充调查"},
        )
        second = send(
            "submissions",
            "submit2",
            "submissions.create",
            {"decision": "no_go", "products": [product]},
        )
        assert Worker(app.state.jobs, app.state.handlers).run_once()
        result2 = c.get("/sessions/" + sid + "/requests/submit2", headers=h).json()
        assert result2["jobs"][0]["status"] == "completed", result2
        assert second["result"]["submission"] != submit["result"]["submission"]
        assert (
            c.get("/sessions/" + sid + "/feedback-records/" + ref["object_id"], headers=h).json()[
                "result"
            ]["result"]["feedback"]
            == saved
        )
    finally:
        app.state.store.close()


def test_supported_real_provider_has_no_inner_or_outer_automatic_retry(tmp_path):
    from career_lab.api.app import create_app
    from career_lab.runtime.model_adapter import OpenAICompatibleModel

    with pytest.raises(ValueError, match="disable automatic retries"):
        create_app(
            "sqlite:///" + str(tmp_path / "invalid.db"),
            model=OpenAICompatibleModel(
                "synthetic-key", "http://127.0.0.1:1", "controlled", retries=2
            ),
        )
    app = create_app(
        "sqlite:///" + str(tmp_path / "valid.db"),
        model=OpenAICompatibleModel("synthetic-key", "http://127.0.0.1:1", "controlled", retries=0),
    )
    try:
        assert app.state.handlers["turn"].retry_on_error is False
        assert app.state.handlers["feedback"].retry_on_error is False
    finally:
        app.state.store.close()
