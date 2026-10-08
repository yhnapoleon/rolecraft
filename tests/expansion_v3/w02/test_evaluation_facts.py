"""Actual FastAPI/Gateway/SQLite producers; history reader captures their exact windows.

This harness supplies the trusted public-history seam pending W14 installation.
It does not manufacture rule facts, perform model calls or pretend to test worker/UI.
"""

from copy import deepcopy
from dataclasses import replace, asdict
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Operation
from career_lab.contracts.v2 import (
    ObjectRef,
    EvidenceRefV2,
    PublicEvent,
    ProtocolError,
    SubmissionV2,
    SubmitInput,
)
from career_lab.scenarios.v2.module import ScenarioModule, point
from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter, ScenarioEvidenceWindow
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_lifecycle import record_submission

ROOT = Path(__file__).resolve().parents[3]


class History:
    def __init__(self, app, client, module, session):
        self.store = app.state.v2_store
        self.gateway = app.state.gateway
        self.client = client
        self.module = module
        self.sid = session["session_id"]
        self.headers = {"Authorization": "Bearer " + session["token"]}
        self.auth = self.store.authenticate(self.sid, session["token"])
        self.windows = {}
        self.events = []
        self.seq = 0
        self.capture()
        self.adapter = ScenarioFactAdapter(
            module,
            authorize=lambda auth: self.store.authorize(auth, "read"),
            window_reader=self.window,
            record_reader=lambda auth, ref, at: self.store.read(
                auth, ref, storage_revision=at.storage_revision if at else None
            ),
            reference_resolver=lambda auth, ref, at: self.store.resolve_reference(
                auth, ref, storage_revision=at.storage_revision
            ),
        )

    def scenario_view(self):
        return self.store.query(self.auth, lambda view: view, operation="actions")

    def capture(self, result=None):
        view = self.store.view(self.auth)
        at = point(view.state)
        self.windows[at.storage_revision] = (
            deepcopy(self.module.snapshot(self.scenario_view())),
            view.bindings,
            at,
        )
        if result:
            for event in result.get("events", []):
                self.events.append((PublicEvent.model_validate(event), at))
        return at

    def window(self, auth, at):
        self.store.authorize(auth, "read")
        if auth.credential_id != self.auth.credential_id:
            raise ProtocolError("history_scope_unavailable")
        snapshot, bindings, actual = self.windows[at.storage_revision]
        assert at == actual
        rows = tuple(
            r
            for r in self.store.view(auth).objects
            if r.created_storage_revision <= at.storage_revision
        )
        return ScenarioEvidenceWindow(
            snapshot,
            bindings,
            rows,
            tuple((e, p) for e, p in self.events if p.storage_revision <= at.storage_revision),
            tuple(v[2] for k, v in sorted(self.windows.items()) if k <= at.storage_revision),
            True,
            True,
        )

    def command(self, operation, payload):
        s = self.store.view(self.auth).state
        self.seq += 1
        return {
            "schema_version": 2,
            "request_id": "cmd-" + str(self.seq),
            "operation": operation,
            "payload": payload,
            "expected_version": s.business_seq,
            "expected_workspace_revision": s.workspace_revision,
        }

    def post(self, path, operation, payload):
        response = self.client.post(
            f"/sessions/{self.sid}/" + path,
            headers=self.headers,
            json=self.command(operation, payload),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        self.capture(result)
        return result

    def run(self, query):
        s = self.store.view(self.auth).state
        return self.post(
            "tests", "tests.create", {"query": query, "config_version": s.config_version}
        )["result"]["test"]

    def apply(self, **changes):
        current = self.module.snapshot(self.scenario_view()).config
        config = (
            current.model_dump(mode="json")
            | changes
            | {"version": current.version + 1, "config_version": current.config_version + 1}
        )
        return self.post("actions", "apply_config", {"tool": "apply_config", "config": config})

    def product(self, text):
        body = self.command(
            "work_products.create",
            {"kind": "text", "purpose": "plan", "content": text, "title": "Working note"},
        )
        result = self.gateway.dispatch(self.auth, "work_products.create", body)
        self.capture(result)
        return max(
            (r.ref for r in self.store.view(self.auth).objects if r.ref.kind == "product"),
            key=lambda ref: self.store.read(self.auth, ref).created_storage_revision,
        )

    def submit(self, products, decision="launch"):
        cfg = self.scenario_view().private_scenario_state.current_config
        result = self.post(
            "submissions",
            "submissions.create",
            {
                "decision": decision,
                "products": [p.model_dump(mode="json") for p in products],
                "config": cfg.model_dump(mode="json"),
            },
        )
        ref = ObjectRef.model_validate(result["result"]["submission"])
        return SubmissionV2.model_validate(self.store.read(self.auth, ref).content)


@pytest.fixture(params=["zh", "en"])
def history(request, tmp_path):
    sid, lang = request.param if isinstance(request.param, tuple) else ("pm_pilot", request.param)
    root = ROOT / "scenarios/pm_pilot/v2"
    if sid != "pm_pilot":
        root = root / "variants" / sid
    module = ScenarioModule(root, work_language=lang)
    registry = module.install(ExtensionRegistry())
    install_workspace_operations(
        registry, roles=tuple(r.id for r in module.package.bundle.role_specs)
    )
    registry.register(Operation("submissions.create", "submit", SubmitInput, record_submission))
    app = create_app("sqlite:///" + str(tmp_path / "facts.db"), extensions=registry)
    with TestClient(app) as client:
        created = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        assert created.status_code == 200
        yield History(app, client, module, created.json())
    app.state.store.close()


def question(h):
    return (
        "住宿报销上限是多少？"
        if h.module.work_language == "zh"
        else "What is the hotel reimbursement limit per night?"
    )


def facts(snapshot):
    return {f.name: f.value for f in snapshot.facts}


def save(snapshot, path):
    def serial(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "__dataclass_fields__"):
            return {k: serial(v) for k, v in value.__dict__.items()}
        if isinstance(value, (tuple, list)):
            return [serial(v) for v in value]
        if isinstance(value, dict):
            return {k: serial(v) for k, v in value.items()}
        return value

    path.write_text(json.dumps(serial(snapshot), ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("branch", ["ignored", "stale", "fresh", "manual", "good_then_failed"])
def test_actual_multiwork_submission_facts_and_latest_retest(history, tmp_path, branch):
    h = history
    initial = h.capture()
    old = h.run(question(h))
    h.apply(
        freshness_guard="warn",
        **({"update_strategy": "manual_policy"} if branch == "manual" else {}),
    )
    if branch != "ignored":
        h.run(question(h))
    if branch in {"fresh", "good_then_failed"}:
        h.post("actions", "refresh_index", {"tool": "refresh_index"})
        h.run(question(h))
    if branch == "good_then_failed":
        # Real failed execution on a new fixed configuration; old success cannot
        # stand in for this version. No injected test-result payload.
        h.apply(fallback="none", domains=["stable_faq"])
        h.run(question(h))
    products = (
        h.product("This note sets the audience."),
        h.product("This note discusses options and remaining questions."),
    )
    sub = h.submit(products)
    snap = h.adapter.submission_rule_provider(h.auth, sub)
    f = facts(snap)
    save(snap, tmp_path / f"{h.module.work_language}-{branch}-rule-snapshot.json")
    assert f["policy_changed"] is True and f["policy_change_seq"] > old["as_of"]["business_seq"]
    assert f["affected_material_versions"] == {"policy": 2}
    assert snap.config_version == sub.config.config_version
    assert (
        not {"content_review_complete", "metrics_count", "alternatives_count", "target_present"}
        & f.keys()
    )
    assert len(sub.products) == 2 and all(t.config_ref == sub.config for t in snap.tests)
    assert f["test_ledger_complete"] and snap.logs_complete
    if branch == "ignored":
        assert f["dynamic_test_ids"] == [] and f["adjustment_action_count"] == 0
    elif branch == "stale":
        assert (
            f["dynamic_test_ids"]
            and f["passing_dynamic_test_ids"] == []
            and not f["adjustment_appropriate_verified"]
        )
    elif branch == "fresh":
        assert (
            f["passing_dynamic_test_ids"] == f["dynamic_test_ids"][-1:]
            and f["adjustment_appropriate_verified"]
        )
    elif branch == "manual":
        assert not f["dynamic_classification_complete"] and "passing_dynamic_test_ids" not in f
    else:
        assert all(t.status == "failed" for t in snap.tests) and f["passing_dynamic_test_ids"] == []
    future = ObjectRef(session_id=h.sid, kind="material", object_id="policy", version=2)
    with pytest.raises(ProtocolError):
        h.adapter.source_reader(h.auth, future, initial)
    assert "500" in old["answer"]


def test_source_reader_exact_english_or_chinese_spans_and_denies_hidden(history):
    h = history
    test = h.run(question(h))
    at = h.capture()
    citation = EvidenceRefV2.model_validate(test["citations"][0])
    source = h.adapter.source_reader(h.auth, citation, at)
    assert source.text[citation.span_start : citation.span_end] == citation.quote
    assert source.created_at.business_seq == 0
    with pytest.raises(ProtocolError):
        h.adapter.source_reader(h.auth, citation.model_copy(update={"quote": "invented"}), at)
    for mid in ["tech_private", "world_private"]:
        with pytest.raises(ProtocolError):
            h.adapter.source_reader(
                h.auth, ObjectRef(session_id=h.sid, kind="material", object_id=mid, version=1), at
            )


@pytest.mark.parametrize("decision", ["no_go", "defer_with_conditions"])
def test_no_go_and_missing_history_do_not_invent_obligation_or_content(history, decision):
    h = history
    h.apply()
    work = h.product("We should defer while the evidence is incomplete.")
    sub = h.submit((work,), decision)
    snap = h.adapter.submission_rule_provider(h.auth, sub)
    assert facts(snap)["current_obligation_verified"] is False
    original = h.adapter.window_reader
    h.adapter.window_reader = lambda auth, at: replace(
        original(auth, at), tests_complete=False, events_complete=False
    )
    partial = h.adapter.submission_rule_provider(h.auth, sub)
    assert not partial.logs_complete and "policy_changed" not in facts(partial)
    assert not facts(partial)["test_ledger_complete"]


def test_frozen_w05_change_rules_consume_actual_adapter_facts(history, tmp_path):
    # Optional external fixed input, never the 040 active worktree.
    import os, tarfile, hashlib, types

    archive = os.environ.get("W02_W05_R10_ARCHIVE")
    if not archive:
        pytest.skip("requires exact W05 r10 owned-source archive")
    raw = Path(archive).read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "99297d18c80e69248624b7ad2177729c5ac2f3ccb19afeedb138f3d799030bf3"
    )
    with tarfile.open(archive) as tar:
        source = tar.extractfile("src/career_lab/rubrics/v4/rules_v2.py").read()
    candidate = types.ModuleType("w05_r10_fixed_change_rules")
    exec(compile(source, "w05-r10-fixed/rules_v2.py", "exec"), candidate.__dict__)
    h = history
    h.apply(freshness_guard="warn")
    product = h.product("Decision evidence is split across ordinary working notes.")

    def evaluate(at):
        window = h.adapter.window(h.auth, at)
        cfg = window.snapshot.config
        from career_lab.scenarios.v2.module import ref_for

        snap = h.adapter._snapshot(h.auth, at, (product,), ref_for("config", cfg), True)
        # All facts are re-resolved through the actual W02 adapter; no fake facts.
        context = {
            "facts": facts(snap),
            "fact_refs": {
                f.name: [
                    h.adapter.source_reader(h.auth, r, at).ref.model_dump(mode="json")
                    for r in f.sources
                ]
                for f in snap.facts
            },
            "logs_complete": snap.logs_complete,
            "test_sources_complete": True,
            "config_version": snap.config_version,
            "tests": [
                {"record": t.model_dump(mode="json"), "ref": r.model_dump(mode="json")}
                for t, r in zip(snap.tests, snap.test_refs)
            ],
            "technical_failures": list(snap.technical_failures),
            "decision": "launch",
        }
        results = {}
        for criterion in ("R4.staleness_test", "R5.adjustment"):
            context["mechanism"] = "v2." + criterion.split(".", 1)[1]
            item = types.SimpleNamespace(
                rule_context=context, purpose="commitment", as_of=at, criterion=criterion
            )
            results[criterion] = candidate.run_rules_v2(
                item, work_language=h.module.work_language
            ).model_dump(mode="json")
        return results

    ignored = evaluate(h.capture())
    h.run(question(h))
    stale = evaluate(h.capture())
    h.post("actions", "refresh_index", {"tool": "refresh_index"})
    h.run(question(h))
    fresh = evaluate(h.capture())
    assert ignored["R4.staleness_test"]["label"] == ignored["R5.adjustment"]["label"] == "NOT_MET"
    assert stale["R4.staleness_test"]["label"] == "PARTIAL"
    # r10 does not fix an adjustment grade without a verified appropriate fix.
    assert stale["R5.adjustment"]["label"] == "INSUFFICIENT"
    assert fresh["R4.staleness_test"]["label"] == fresh["R5.adjustment"]["label"] == "MET"
    (tmp_path / "actual-w02-to-frozen-w05-change-rules.json").write_text(
        json.dumps(
            {
                "language": h.module.work_language,
                "scope": "two actual W05 r10 change-rule functions; factory, shared worker and UI not installed",
                "r10_archive_sha256": hashlib.sha256(raw).hexdigest(),
                "ignored": ignored,
                "stale": stale,
                "fresh": fresh,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def test_current_authorization_and_exact_submission_identity_are_required(history):
    h = history
    work = h.product("A freely written plan.")
    sub = h.submit((work,))
    ref = ObjectRef(session_id=h.sid, kind="material", object_id="brief", version=1)
    with pytest.raises(ProtocolError):
        h.adapter.source_reader(
            h.auth.model_copy(update={"credential_id": "forged"}), ref, sub.as_of
        )
    with pytest.raises(ProtocolError):
        h.adapter.submission_rule_provider(h.auth, sub.model_copy(update={"decision": "no_go"}))
