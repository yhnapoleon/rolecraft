"""Real TCP HTTP app and independently launched stdio server; no model calls."""

import importlib.util, json, os, queue, socket, subprocess, sys, threading, time
from pathlib import Path
import pytest, uvicorn
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure
from career_lab.mcp.protocol import MODERN, VERSION, CAPABILITIES

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "w06_gateway_fixture", ROOT / "tests/integration/test_w06_gateway.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture
def live(tmp_path):
    app = fixture.make_app(tmp_path / "live.db")
    client = TestClient(app)
    created = client.post(
        "/sessions", json={"schema_version": 2, "scenario": "controlled-w06"}
    ).json()
    client.headers["Authorization"] = "Bearer " + created["token"]
    owner = app.state.v2_store.authenticate(created["session_id"], created["token"])
    env = dict(
        app=app, client=client, sid=created["session_id"], owner=owner, token=created["token"]
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    created, _ = fixture.grant(env, ("read", "act"))
    config = tmp_path / "delegate.json"
    config.write_text(
        json.dumps(
            {
                "api_url": f"http://127.0.0.1:{sock.getsockname()[1]}",
                "session_id": env["sid"],
                "token": created["token"],
            }
        )
    )
    config.chmod(0o600)
    env.update(config=config, delegate=created, backend=HttpAgentClient(config), tmp=tmp_path)
    yield env
    server.should_exit = True
    thread.join(5)
    client.close()
    app.state.store.close()
    app.state.v2_store.db.engine.dispose()
    sock.close()
    assert not thread.is_alive()


class Pipe:
    def __init__(self, config):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "career_lab.mcp", "--config", str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.queue = queue.Queue()
        self.transcript = []

        def reader():
            for line in self.proc.stdout:
                self.queue.put(line)

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def rpc(self, method, params=None, identifier=1, modern=True):
        self.send(
            {
                "jsonrpc": "2.0",
                "id": identifier,
                "method": method,
                "params": (
                    {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}}
                    if modern
                    else params or {}
                ),
            }
        )
        raw = self.queue.get(timeout=8)
        self.transcript.append(raw)
        value = json.loads(raw)
        assert value["id"] == identifier
        return value

    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(timeout=10) == 0
        self.thread.join(1)
        stderr = self.proc.stderr.read()
        assert not stderr, stderr
        return "".join(self.transcript) + stderr


def test_w06_stdio_modern_legacy_errors_and_live_revocation(live):
    pipe = Pipe(live["config"])
    secret = live["delegate"]["token"]
    try:
        discover = pipe.rpc("server/discover")["result"]
        assert (
            discover["resultType"] == "complete"
            and discover["ttlMs"] == 0
            and MODERN in discover["supportedVersions"]
        )
        result = pipe.rpc("tools/list")["result"]
        names = {t["name"] for t in result["tools"]}
        assert (
            "work_products.create" in names
            and "submit" not in names
            and "delegations.create" not in names
            and "work_products.adopt" not in names
        )
        assert pipe.rpc("tools/list", modern=False)["error"]["code"] == -32602
        assert (
            pipe.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "controlled-client", "version": "1"},
                },
                modern=False,
            )["result"]["protocolVersion"]
            == "2025-11-25"
        )
        pipe.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert "tools" in pipe.rpc("tools/list", modern=False)["result"]
        assert (
            pipe.rpc("tools/call", {"name": "arbitrary_shell", "arguments": {}})["error"]["code"]
            == -32602
        )
        command = fixture.command(
            live, "work_products.create", {"kind": "text", "content": "Via real MCP"}
        )
        args = {
            "name": "work_products.create",
            "arguments": {"session_id": live["sid"], "command": command},
        }
        first = pipe.rpc("tools/call", args)["result"]
        second = pipe.rpc("tools/call", args)["result"]
        assert not first["isError"] and second["structuredContent"]["replayed"]
        assert first["structuredContent"]["executor"]["kind"] == "external_agent"
        revoked = fixture.command(
            live, "delegations.revoke", {"delegation_id": live["delegate"]["delegation"]["id"]}
        )
        assert (
            live["client"]
            .request(
                "DELETE",
                f"/sessions/{live['sid']}/delegations/{live['delegate']['delegation']['id']}",
                json=revoked,
            )
            .status_code
            == 200
        )
        denied = pipe.rpc("tools/call", args)
        assert "error" in denied or denied["result"]["isError"]
        assert secret not in json.dumps(denied)
    finally:
        assert secret not in pipe.close()


def test_w06_reference_example_human_agent_human_actual_api(live):
    ref = C.ObjectRef(
        session_id=live["sid"], kind="material", object_id="public-material", version=1
    )
    read = live["client"].post(
        f"/sessions/{live['sid']}/actions",
        json=fixture.command(
            live,
            "read_material",
            {"tool": "read_material", "material": ref.model_dump(mode="json")},
        ),
    )
    assert read.status_code == 200, read.text
    journal = live["tmp"] / "journal.json"
    cmd = [
        sys.executable,
        "examples/byo_agent_minimal.py",
        "--config",
        str(live["config"]),
        "--journal",
        str(journal),
        "--config-version",
        "0",
    ]
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert first.returncode == 0, first.stderr
    record = json.loads(journal.read_text())
    assert record["model"] is None and len(record["steps"]) == 2
    before = live["app"].state.v2_store.view(live["owner"]).state
    # Simulate a lost response after the server committed and before journal confirmation.
    record["steps"][0]["status"] = "unconfirmed"
    record["steps"][0].pop("result")
    journal.write_text(json.dumps(record))
    again = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert again.returncode == 0
    record = json.loads(journal.read_text())
    assert live["app"].state.v2_store.view(live["owner"]).state == before
    product = record["steps"][0]["result"]["result"]["object"]
    test_ref = C.ObjectRef.model_validate(record["steps"][1]["result"]["result"]["test"])
    assert (
        product["executor"]["kind"] == "external_agent"
        and product["adoption"]["status"] == "unadopted"
    )
    assert (
        live["app"]
        .state.v2_store.read(live["owner"], test_ref)
        .content["execution"]["executor"]["kind"]
        == "external_agent"
    )
    adopt = live["client"].post(
        f"/sessions/{live['sid']}/work-products/{product['product_id']}/adoption",
        json=fixture.command(
            live,
            "work_products.adopt",
            {
                "product_id": product["product_id"],
                "product_version": 1,
                "expected_head": 1,
                "status": "adopted",
            },
        ),
    )
    assert adopt.status_code == 200, adopt.text
    pref = adopt.json()["result"]["ref"]
    submit = live["client"].post(
        f"/sessions/{live['sid']}/submissions",
        json=fixture.command(
            live, "submit", {"decision": "defer_with_conditions", "products": [pref]}
        ),
    )
    assert submit.status_code == 200, submit.text
    assert (
        submit.json()["executor"]["kind"] == "human"
        and submit.json()["state"]["status"] == "submitted"
    )
    assert live["delegate"]["token"] not in journal.read_text() + first.stdout + first.stderr


def test_w06_http_cross_session_scope_and_expired_credentials(live):
    args = {"session_id": "another-session", "query": {}}
    with pytest.raises(RemoteFailure, match="session_route_mismatch"):
        live["backend"].call("work_products.list", args)
    # Expiration is checked on the existing credential by the public store.
    from sqlalchemy import update
    from career_lab.storage.v2_tables import v2_credentials
    from datetime import datetime, timedelta, timezone

    store = live["app"].state.v2_store
    with store.db.transaction() as conn:
        row = (
            conn.execute(
                __import__("sqlalchemy")
                .select(v2_credentials)
                .where(
                    v2_credentials.c.id
                    == store.authenticate(live["sid"], live["delegate"]["token"]).credential_id
                )
            )
            .mappings()
            .one()
        )
        ctx = json.loads(row["context"])
        ctx["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        conn.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == row["id"])
            .values(context=json.dumps(ctx))
        )
    with pytest.raises(RemoteFailure):
        live["backend"].tools()
    pipe = Pipe(live["config"])
    try:
        assert "error" in pipe.rpc("tools/list")
    finally:
        assert live["delegate"]["token"] not in pipe.close()


def seed_role_history(env):
    """A real safe dialogue plus raw historical r1 data deliberately restored."""
    from career_lab.storage.role_memory import (
        RoleTurn,
        RoleReply,
        object_write,
        install_role_storage,
    )
    from career_lab.storage.v2_store import Mutation, EventDraft
    from career_lab.storage.v2_tables import v2_objects, v2_heads, v2_transactions, v2_request_meta
    from sqlalchemy import insert, update

    store = env["app"].state.v2_store
    install_role_storage(store)
    at = fixture.point(store.view(env["owner"]).state)
    turn = RoleTurn(
        id="safe-turn",
        session_id=env["sid"],
        input=C.TurnInput(role_id="tech_lead", text="Explain the public limitation"),
        as_of=at,
        executor=env["owner"].executor,
    )
    tw = object_write("role_turn", turn)
    reply = RoleReply(
        id="safe-reply",
        session_id=env["sid"],
        role_id="tech_lead",
        request=tw.ref,
        question=turn.input.text,
        text="Public words only.",
        status="completed",
        as_of=at,
        executor=env["owner"].executor,
    )
    rw = object_write("role_reply", reply, visible_to=("learner", "tech_lead"))
    cmd = C.Command.model_validate(
        fixture.command(env, "read_material", {}, key="safe-reply-request")
    )
    txn = store.execute(
        env["owner"],
        cmd,
        lambda *_: Mutation(
            writes=(tw, rw),
            events=(
                EventDraft(type="dialogue_displayed", visible_to=("learner",), refs=(rw.ref,)),
            ),
            result={"reply": rw.ref.model_dump(mode="json")},
        ),
    )
    oldref = rw.ref.model_copy(update={"object_id": "legacy-reply"})
    old = reply.model_dump(mode="json") | {
        "id": oldref.object_id,
        "prompt_messages": [{"role": "system", "content": fixture.PRIVATE}],
        "context_hash": "0" * 64,
        "spoken_source": {"private_id": "HIDDEN_SOURCE"},
    }
    record = C.StoredObject(
        ref=oldref,
        content=old,
        visible_to=("learner", "tech_lead"),
        dependencies=(tw.ref,),
        created_storage_revision=txn.state.storage_revision,
    )
    legacy_cmd = C.Command.model_validate(
        fixture.command(env, "read_material", {}, key="legacy-request")
    )
    legacy_tx = store.execute(env["owner"], legacy_cmd, lambda *_: Mutation(result={}))
    unsafe = legacy_tx.model_copy(update={"objects": (oldref,), "result": {"nested": [old]}})
    with store.db.transaction() as conn:
        conn.execute(
            insert(v2_objects).values(
                session_id=env["sid"],
                kind=oldref.kind,
                id=oldref.object_id,
                version=1,
                record=C.canonical(record),
                created_revision=record.created_storage_revision,
            )
        )
        conn.execute(
            insert(v2_heads).values(
                session_id=env["sid"], kind=oldref.kind, id=oldref.object_id, version=1
            )
        )
        conn.execute(
            update(v2_transactions)
            .where(
                v2_transactions.c.session_id == env["sid"],
                v2_transactions.c.request_id == legacy_cmd.request_id,
            )
            .values(result=C.canonical(unsafe))
        )
        conn.execute(
            update(v2_request_meta)
            .where(
                v2_request_meta.c.session_id == env["sid"],
                v2_request_meta.c.request_id == legacy_cmd.request_id,
            )
            .values(scope_refs="[]")
        )
    return rw.ref, oldref


@pytest.mark.parametrize("mode", ["owner", "read", "restricted_act"])
def test_w06_mounted_privacy_observation_tools_paging_recovery_and_mcp(live, mode):
    safe, old = seed_role_history(live)
    store = live["app"].state.v2_store
    if mode == "owner":
        token = live["token"]
    else:
        opts = (
            {}
            if mode == "read"
            else {
                "allowed_objects": ("safe-turn", "safe-reply", "public-material"),
                "allowed_actions": ("observation", "tools", "materials.list", "read_material"),
            }
        )
        created, _ = fixture.grant(live, ("read",) if mode == "read" else ("read", "act"), **opts)
        token = created["token"]
    header = {"Authorization": "Bearer " + token}
    outputs = []
    for suffix in (
        "/observation?since_seq=0&limit=1",
        "/observation?since_seq=1&limit=1",
        "/tools",
        "/materials?limit=1",
        "/requests/legacy-request",
    ):
        response = live["client"].get("/sessions/" + live["sid"] + suffix, headers=header)
        outputs.append(response.text)
        if "legacy-request" in suffix:
            assert response.status_code in (403, 404)
        else:
            assert response.status_code == 200, response.text
    assert "Public words only." in "".join(outputs)
    for secret in (
        fixture.PRIVATE,
        "prompt_messages",
        "HIDDEN_SOURCE",
        "context_hash",
        "legacy-reply",
    ):
        assert secret not in "".join(outputs)
    # Owner sees public data through HTTP, but MCP requires a delegate identity.
    live["config"].write_text(
        json.dumps({"api_url": load_url(live), "session_id": live["sid"], "token": token})
    )
    live["config"].chmod(0o600)
    pipe = Pipe(live["config"])
    try:
        result = pipe.rpc(
            "tools/call",
            {
                "name": "observation",
                "arguments": {"session_id": live["sid"], "query": {"since_seq": 0, "limit": 1}},
            },
        )
        if mode == "owner":
            assert "error" in result
        else:
            assert not result["result"]["isError"] and "Public words only." in json.dumps(result)
            for name, args in [
                ("materials.list", {"query": {"limit": 1}}),
                ("requests.read", {"query": {"request_id": "legacy-request"}}),
            ]:
                result = pipe.rpc(
                    "tools/call", {"name": name, "arguments": {"session_id": live["sid"], **args}}
                )
                outputs.append(json.dumps(result))
                if name == "materials.list":
                    assert not result["result"]["isError"]
                else:
                    assert result["result"]["isError"]
    finally:
        transcript = pipe.close()
        outputs.append(transcript)
    assert all(
        secret not in "".join(outputs)
        for secret in (fixture.PRIVATE, "prompt_messages", "HIDDEN_SOURCE", token)
    )
    assert (
        fixture.PRIVATE
        in store.read(store.role_reader(live["sid"], "tech_lead"), old).model_dump_json()
    )
    assert fixture.PRIVATE in store.read(store.research_context(live["sid"]), old).model_dump_json()


def load_url(env):
    return json.loads(env["config"].read_text())["api_url"]


def test_w06_bounded_recovery_reads_actual_pending_public_job(live):
    from career_lab.storage.v2_store import Mutation, JobRequest

    store = live["app"].state.v2_store
    auth = store.authenticate(live["sid"], live["delegate"]["token"])
    cmd = C.Command.model_validate(fixture.command(live, "controlled_queue", {}))
    queued = store.execute(
        auth,
        cmd,
        lambda *_: Mutation(
            jobs=(
                JobRequest(
                    name="v2.controlled-w06",
                    command=cmd.model_copy(update={"request_id": "queued-effect"}),
                    context_hash="0" * 64,
                ),
            )
        ),
    )
    started = time.monotonic()
    recovered = live["backend"].wait_request(
        live["sid"], cmd.request_id, seconds=0.15, interval=0.03
    )
    assert time.monotonic() - started < 0.8 and recovered["status"] == "pending"
    assert recovered["jobs"][0]["job_id"] == queued.result["queued_jobs"][0]
    assert not any(r.ref.kind == "product" for r in store.view(live["owner"]).objects)


def test_w06_actual_http_scope_forbids_foreign_object_and_delegate_control(live):
    c = live["client"]
    sid = live["sid"]
    first = c.post(
        f"/sessions/{sid}/work-products",
        json=fixture.command(live, "work_products.create", {"kind": "text", "content": "allowed"}),
    ).json()["result"]["ref"]
    second = c.post(
        f"/sessions/{sid}/work-products",
        json=fixture.command(
            live, "work_products.create", {"kind": "text", "content": "HIDDEN_WORK"}
        ),
    ).json()["result"]["ref"]
    created, _ = fixture.grant(live, allowed_objects=(first["object_id"],))
    header = {"Authorization": "Bearer " + created["token"]}
    good = c.get(f"/sessions/{sid}/work-products/{first['object_id']}/versions", headers=header)
    assert good.status_code == 200 and "allowed" in good.text
    bad = c.get(f"/sessions/{sid}/work-products/{second['object_id']}/versions", headers=header)
    absent = c.get(f"/sessions/{sid}/work-products/absent/versions", headers=header)
    assert bad.status_code == absent.status_code == 200 and bad.json() == absent.json()
    assert bad.json()["result"]["result"]["items"] == [] and "HIDDEN_WORK" not in bad.text
    bad = c.post(
        f"/sessions/{sid}/work-products",
        headers=header,
        json=fixture.command(
            live, "work_products.create", {"kind": "text", "content": "forbidden"}
        ),
    )
    assert bad.status_code == 403
    _, cmd = fixture.grant(live)
    bad = c.post(f"/sessions/{sid}/delegations", headers=header, json=cmd)
    assert bad.status_code == 403 and "token" not in bad.text
    another = c.post("/sessions", json={"schema_version": 2, "scenario": "controlled-w06"}).json()
    bad = c.get(f"/sessions/{another['session_id']}/observation", headers=header)
    assert bad.status_code in (401, 403, 404)


def queue_example_product(live):
    """Controlled async producer using the real shared queue and workspace writer."""
    from dataclasses import replace
    from career_lab.storage.v2_store import Mutation, JobRequest
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import Worker, ClaimedHandler

    gateway = live["app"].state.gateway
    original = gateway.registry.operations["work_products.create"]
    name = "v2.w06-example-product"

    def enqueue(view, command, auth):
        return Mutation(
            jobs=(
                JobRequest(
                    name=name,
                    command=command.model_copy(
                        update={"request_id": command.request_id + "-effect"}
                    ),
                    context_hash="0" * 64,
                ),
            )
        )

    gateway.registry.operations[original.name] = replace(original, handler=enqueue)
    gateway.registry.register_job(
        name, lambda view, envelope, auth: original.handler(view, envelope.command, auth)
    )
    return Worker(
        JobRepository(gateway.store.db),
        {name: ClaimedHandler(lambda payload, claim: gateway.run_job(name, payload, claim=claim))},
    )


def example_invocation(live):
    ref = C.ObjectRef(
        session_id=live["sid"], kind="material", object_id="public-material", version=1
    )
    response = live["client"].post(
        f"/sessions/{live['sid']}/actions",
        json=fixture.command(
            live,
            "read_material",
            {"tool": "read_material", "material": ref.model_dump(mode="json")},
        ),
    )
    assert response.status_code == 200, response.text
    journal = live["tmp"] / "async-journal.json"
    cmd = [
        sys.executable,
        "examples/byo_agent_minimal.py",
        "--config",
        str(live["config"]),
        "--journal",
        str(journal),
        "--config-version",
        "0",
        "--wait-seconds",
        "0",
    ]
    return journal, cmd


def test_w06_example_does_not_advance_queued_work_and_recovers_worker_effect(live):
    worker = queue_example_product(live)
    journal, cmd = example_invocation(live)
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    record = json.loads(journal.read_text())
    assert first.returncode == 2, (first.stdout, first.stderr)
    assert record["status"] == "pending" and len(record["steps"]) == 1
    step = record["steps"][0]
    request_id = step["command"]["request_id"]
    job = step["request_result"]["jobs"][0]
    assert step["status"] == "pending" and job["status"] == "queued"
    assert job["job_id"] in first.stdout and request_id in first.stdout
    assert "Completed" not in first.stdout
    assert not any(
        r.ref.kind in {"product", "test"}
        for r in live["app"].state.v2_store.view(live["owner"]).objects
    )
    assert worker.run_once()
    again = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert again.returncode == 0, (again.stdout, again.stderr)
    record = json.loads(journal.read_text())
    assert record["status"] == "completed"
    assert record["steps"][0]["command"]["request_id"] == request_id
    effect = record["steps"][0]["request_result"]["jobs"][0]
    assert effect["job_id"] == job["job_id"] and effect["status"] == "completed"
    assert effect["effect"]["result"]["object"]["executor"]["kind"] == "external_agent"
    before = live["app"].state.v2_store.view(live["owner"]).state
    third = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert third.returncode == 0, third.stderr
    assert live["app"].state.v2_store.view(live["owner"]).state == before and not worker.run_once()
    assert (
        live["delegate"]["token"]
        not in journal.read_text() + first.stdout + again.stdout + third.stdout
    )


@pytest.mark.parametrize("outcome", ["needs_context", "failed", "unresolved"])
def test_w06_example_retains_noncompletion_and_only_refreshes_explicitly(live, outcome):
    from career_lab.jobs.worker import Worker, ClaimedHandler

    worker = queue_example_product(live)
    gateway = live["app"].state.gateway
    name = "v2.w06-example-product"
    real_handler = gateway.registry.job_handlers[name]
    journal, cmd = example_invocation(live)
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert first.returncode == 2, first.stderr
    pending = json.loads(journal.read_text())["steps"][0]
    job_id = pending["request_result"]["jobs"][0]["job_id"]
    if outcome == "unresolved":
        # A worker acknowledges completion without committing its business effect.
        worker = Worker(worker.jobs, {name: lambda payload: {}})
    else:

        def stop(*args):
            raise C.ProtocolError(
                "context_stale" if outcome == "needs_context" else "controlled_rejection",
                status=409,
            )

        gateway.registry.job_handlers[name] = stop
    assert worker.run_once()
    before = gateway.store.view(live["owner"]).state
    resumed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    record = json.loads(journal.read_text())
    assert resumed.returncode == (1 if outcome == "failed" else 2), (resumed.stdout, resumed.stderr)
    assert record["status"] == outcome and record["steps"][0]["status"] == outcome
    assert len(record["steps"]) == 1 and record["steps"][0]["command"] == pending["command"]
    assert (
        outcome in resumed.stdout and "Completed" not in resumed.stdout and job_id in resumed.stdout
    )
    assert gateway.store.view(live["owner"]).state == before
    if outcome == "needs_context":
        assert record["steps"][0]["request_result"]["jobs"][0]["error_code"] == "context_stale"
        gateway.registry.job_handlers[name] = real_handler
        refreshed = live["client"].post(
            f"/sessions/{live['sid']}/jobs/{job_id}/refresh",
            json=fixture.command(live, "jobs.refresh", {"job_id": job_id}),
        )
        assert refreshed.status_code == 200, refreshed.text
        assert worker.run_once()
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert completed.returncode == 0, completed.stderr
        result = json.loads(journal.read_text())["steps"][0]["request_result"]
        assert (
            result["request_id"] == pending["command"]["request_id"]
            and result["status"] == "completed"
        )
        assert result["jobs"][0]["job_id"] == job_id and result["jobs"][0]["refresh_count"] == 1
        assert len(result["jobs"][0]["refresh_history"]) == 1
    assert live["delegate"]["token"] not in journal.read_text() + resumed.stdout + resumed.stderr


def test_w06_example_rechecks_old_completed_acknowledgement(live):
    queue_example_product(live)
    journal, cmd = example_invocation(live)
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert first.returncode == 2, first.stderr
    record = json.loads(journal.read_text())
    step = record["steps"][0]
    command = step["command"]
    record.pop("identity")
    record.pop("status")
    step.pop("request_result")
    step["status"] = "completed"  # The old client incorrectly accepted queued_jobs.
    journal.write_text(json.dumps(record))
    before = live["app"].state.v2_store.view(live["owner"]).state
    resumed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert resumed.returncode == 2, resumed.stderr
    recovered = json.loads(journal.read_text())
    assert recovered["status"] == "pending" and len(recovered["steps"]) == 1
    assert (
        recovered["steps"][0]["command"] == command
        and live["app"].state.v2_store.view(live["owner"]).state == before
    )


def test_w06_example_refuses_replacement_delegate_journal(live):
    journal, cmd = example_invocation(live)
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert first.returncode == 0, first.stderr
    before = live["app"].state.v2_store.view(live["owner"]).state
    saved = journal.read_bytes()
    created, _ = fixture.grant(live, ("read", "act"))
    config = json.loads(live["config"].read_text())
    config["token"] = created["token"]
    live["config"].write_text(json.dumps(config))
    resumed = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert resumed.returncode == 1
    assert "Completed" not in resumed.stdout and journal.read_bytes() == saved
    assert live["app"].state.v2_store.view(live["owner"]).state == before


def test_w06_example_lost_queue_ack_recovers_original_request(live, monkeypatch):
    worker = queue_example_product(live)
    journal, _ = example_invocation(live)
    source = importlib.util.spec_from_file_location(
        "w06_example_recovery", ROOT / "examples/byo_agent_client/workflow.py"
    )
    workflow = importlib.util.module_from_spec(source)
    source.loader.exec_module(workflow)

    class LostAck(HttpAgentClient):
        def call(self, name, arguments, **kwargs):
            result = super().call(name, arguments, **kwargs)
            if name == "work_products.create":
                raise RemoteFailure("response_unconfirmed")
            return result

    monkeypatch.setattr(workflow, "HttpAgentClient", LostAck)
    with pytest.raises(RemoteFailure, match="response_unconfirmed"):
        workflow.run(live["config"], journal, config_version=0, wait_seconds=0)
    lost = json.loads(journal.read_text())
    step = lost["steps"][0]
    assert step["status"] == "unconfirmed" and "result" not in step
    before = live["app"].state.v2_store.view(live["owner"]).state
    monkeypatch.setattr(workflow, "HttpAgentClient", HttpAgentClient)
    pending = workflow.run(live["config"], journal, config_version=0, wait_seconds=0)
    assert pending["status"] == "pending" and len(pending["steps"]) == 1
    assert pending["steps"][0]["command"] == step["command"]
    assert live["app"].state.v2_store.view(live["owner"]).state == before
    assert worker.run_once()
    completed = workflow.run(live["config"], journal, config_version=0, wait_seconds=0)
    assert (
        completed["status"] == "completed" and completed["steps"][0]["command"] == step["command"]
    )
    assert not worker.run_once()
