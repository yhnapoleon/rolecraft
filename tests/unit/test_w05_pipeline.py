"""W05 evaluator tests and explicit historical persistence fixtures.

Fixture SQLite/router/worker results do not prove shared Gateway integration.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
from uuid import uuid4
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    String,
    Text,
    Table,
    MetaData,
    create_engine,
    insert,
    select,
    update,
    func,
)

from career_lab.contracts.v2.core import (
    AuthContext,
    Executor,
    ObjectRef,
    EvidenceRefV2,
    VersionPoint,
    FileRef,
    Command,
    ProtocolError,
    digest,
    canonical,
)
from career_lab.contracts.v2.world import (
    WorldStateV2,
    SessionBindings,
    AssistantConfig,
    EffectiveConfig,
    TestExecutionMetadata as ExecutionMetadata,
    TestResultV2 as AssistantTestResult,
)
from career_lab.contracts.v2.evaluation import FeedbackItem
from career_lab.contracts.v2.workspace import (
    RevisionCycle,
    WorkProductVersion,
    OptionsPayload,
    Option,
)
from career_lab.evidence.v2.ports import (
    SourceRecord,
    VerifiedFact,
    RuleSnapshot,
    DEFAULT_POLICIES,
    CriterionPolicy,
    ResponsibilityFact,
)
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, model_input, product_text
from career_lab.rubrics.v4.rules import run_rules
from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.rubrics.v4.feedback import FeedbackEngine, score_bounds
from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
from test_w05_legacy_service_fixture import create_service, create_router, point, ref
from test_w05_legacy_repository_fixture import register_tables, records, requests, jobs, attempts

test_meta = MetaData()
test_states = Table(
    "w05_test_world", test_meta, Column("id", String, primary_key=True), Column("state", Text)
)
INITIAL = VersionPoint(business_seq=5, workspace_revision=0, storage_revision=5)


class UpstreamDouble:
    """No actual W02/W03/W04 or production credentials are implied."""

    def __init__(self):
        self.sources = {}
        self.revoked = False
        self.protocol_value = "v2"
        self.failure = False
        self.capacity = 30
        self.participants = 20
        self.logs_complete = True
        self.tests = ()
        self.test_refs = ()
        self.technical = ()
        self.denied = set()
        self.revoked_ids = set()
        self.selected_policies = DEFAULT_POLICIES
        self.incurred = set()
        self.responsibility_known = True
        self.bundle = SessionBindings(
            scenario=FileRef(path="scenario.json", sha256="1" * 64),
            runtime=FileRef(path="runtime.json", sha256="2" * 64),
            evaluation=FileRef(path="evaluation.json", sha256="3" * 64),
        )
        self.add(
            "product",
            "p1",
            1,
            "先比较稳定域开放与人工处理；缺少真实需求前，可有依据地暂缓并继续访谈。",
        )
        self.add("event", "ledger", 1, "当时有效容量30；资源3人日；期限7天。完整测试账本。")
        self.add("config", "config", 1, "配置c0：20人，2人日，第7天。", config_version=0)

    def add(self, kind, oid, version, text, created=INITIAL, **kw):
        evidence = EvidenceRefV2(
            session_id="s",
            kind=kind,
            object_id=oid,
            version=version,
            observed_at_seq=created.business_seq,
            **kw,
        )
        self.sources[(kind, oid, version, kw.get("config_version"))] = SourceRecord(
            evidence, text, created
        )
        return evidence

    def validate(self, conn, auth, capability, operation):
        if self.revoked or auth.credential_id in self.revoked_ids:
            raise ProtocolError("credential_revoked", status=401)
        if auth.expires_at and auth.expires_at <= datetime.now(timezone.utc):
            raise ProtocolError("credential_expired", status=401)
        if capability not in auth.capabilities:
            raise ProtocolError("capability_denied", status=403)
        if auth.allowed_actions is not None and operation not in auth.allowed_actions:
            raise ProtocolError("action_denied", status=403)

    def protocol(self, conn, auth):
        return self.protocol_value

    def state(self, conn, auth, *, lock):
        query = select(test_states.c.state).where(test_states.c.id == auth.session_id)
        raw = conn.execute(query.with_for_update() if lock else query).scalar_one_or_none()
        if raw is None:
            raise ProtocolError("not_found", status=404)
        return WorldStateV2.model_validate_json(raw)

    def bindings(self, conn, auth):
        return self.bundle

    def cycle(self, conn, auth, cycle_id):
        if cycle_id != "initial":
            raise ProtocolError("not_found", status=404)
        return RevisionCycle(
            id="initial", session_id="s", opened_at=INITIAL, base_state_ref="fixture-initial-world"
        )

    def can_access(self, conn, auth, obj):
        return obj.session_id == auth.session_id and (
            auth.allowed_objects is None or obj.object_id in auth.allowed_objects
        )

    def reader(self, conn):
        return self

    def read(self, auth, reference, as_of):
        if (
            reference.session_id != auth.session_id
            or reference.object_id in self.denied
            or (
                auth.allowed_objects is not None and reference.object_id not in auth.allowed_objects
            )
        ):
            raise ProtocolError("not_found", status=403)
        return self.sources[
            (reference.kind, reference.object_id, reference.version, reference.config_version)
        ]

    def collect(self, conn, auth, subjects, as_of, decision):
        ledger = self.sources[("event", "ledger", 1, None)].ref
        config = self.sources[("config", "config", 1, 0)].ref
        facts = tuple(
            VerifiedFact(
                k,
                v,
                (
                    config
                    if k in {"participants", "required_dev_days", "requested_launch_day"}
                    else ledger,
                ),
            )
            for k, v in {
                "participants": self.participants,
                "capacity": self.capacity,
                "required_dev_days": 2,
                "available_dev_days": 3,
                "requested_launch_day": 7,
                "deadline_day": 7,
                "test_ledger_complete": True,
            }.items()
        )
        return RuleSnapshot(
            as_of,
            facts,
            self.logs_complete,
            self.tests,
            self.test_refs,
            0,
            self.technical,
            responsibilities=tuple(
                ResponsibilityFact(
                    p.id, "actual_action", INITIAL, INITIAL, (product_ref(),), (ledger,)
                )
                for p in self.selected_policies
                if p.id in self.incurred
            )
            if self.responsibility_known
            else (),
        ), ()

    def policies(self, conn, evaluation):
        return self.selected_policies

    def commit_transition(self, conn, auth, before, after, operation):
        assert (
            before.resources == after.resources
            and before.applied_milestones == after.applied_milestones
        )
        conn.execute(
            update(test_states)
            .where(test_states.c.id == auth.session_id)
            .values(state=after.model_dump_json())
        )
        if self.failure:
            raise RuntimeError("injected transaction failure")


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'w05.db'}", connect_args={"timeout": 30})
    register_tables(engine)
    test_meta.create_all(engine)
    authority = UpstreamDouble()
    auth = AuthContext(
        session_id="s",
        actor_id="learner",
        executor=Executor(id="human-1", kind="human"),
        capabilities=("read", "act", "submit"),
        credential_id="trusted-fixture",
    )
    with engine.begin() as conn:
        state = WorldStateV2(
            session_id="s",
            business_seq=5,
            workspace_revision=0,
            storage_revision=5,
            cycle_id="initial",
            config_version=0,
            resources={"capacity": 30},
            applied_milestones=("initial_plan_applied",),
        )
        conn.execute(insert(test_states).values(id="s", state=state.model_dump_json()))
    service = create_service(engine, authority)
    yield {"engine": engine, "authority": authority, "auth": auth, "service": service}
    engine.dispose()


def command(env, operation, payload, request_id=None):
    with env["engine"].connect() as conn:
        state = env["authority"].state(conn, env["auth"], lock=False)
    return Command(
        schema_version=2,
        request_id=request_id or uuid4().hex,
        expected_version=state.business_seq,
        expected_workspace_revision=state.workspace_revision,
        operation=operation,
        payload=payload,
    )


def execute(env, operation, payload, request_id=None):
    return env["service"].execute(env["auth"], command(env, operation, payload, request_id))


def product_ref(version=1):
    return ObjectRef(session_id="s", kind="product", object_id="p1", version=version)


def package(
    env,
    criterion="R3.capacity",
    purpose="commitment",
    decision="launch",
    budget=16000,
    refs=(),
    snapshot=None,
    expected_refs=(),
):
    policy = next(p for p in DEFAULT_POLICIES if p.id == criterion)
    if snapshot is None:
        snapshot = env["authority"].collect(None, env["auth"], (product_ref(),), INITIAL, decision)[
            0
        ]
    return EvidenceAssemblerV2(env["authority"], budget).assemble(
        auth=env["auth"],
        subject_id="fixed",
        subjects=(product_ref(),),
        evidence_refs=refs,
        purpose=purpose,
        decision=decision,
        as_of=INITIAL,
        policy=policy,
        snapshot=snapshot,
        expected_refs=expected_refs,
    )


def review(env, purpose="exploration", scope=()):
    return execute(
        env,
        "reviews.create",
        {
            "subjects": [product_ref().model_dump(mode="json")],
            "purpose": purpose,
            "scope": list(scope),
            "question": "请说明依据。",
        },
    )


def test_purpose_and_stop_decision_keep_different_responsibilities(env):
    env["authority"].participants = 50
    assert run_rules(package(env, purpose="draft")).label == "NOT_APPLICABLE"
    assert run_rules(package(env, purpose="commitment")).label == "NOT_MET"
    assert run_rules(package(env, purpose="result")).label == "NOT_APPLICABLE"
    assert run_rules(package(env, purpose="没有明确用途")).label == "INSUFFICIENT"
    assert run_rules(package(env, decision="no_go")).label == "NOT_APPLICABLE"
    assert (
        package(env, criterion="decision.rationale", decision="no_go").applicability == "applicable"
    )
    assert (
        package(env, criterion="decision.follow_up", decision="defer_with_conditions").applicability
        == "applicable"
    )


def test_long_text_does_not_remove_verified_rule_facts_or_zero_config(env):
    env["authority"].add("product", "p1", 1, "长证据" * 12000)
    item = package(env, budget=2000)
    assert item.completeness == "text_overflow" and item.dropped_refs
    assert item.rule_context["facts"]["capacity"] == 30 and run_rules(item).label == "MET"
    assert item.rule_context["config_version"] == 0
    assert len(canonical(model_input(item)).encode()) <= 2000


def test_missing_logs_and_technical_failure_do_not_become_user_failure(env):
    env["authority"].logs_complete = False
    assert run_rules(package(env, criterion="R4.functional_tests")).label == "INSUFFICIENT"
    env["authority"].logs_complete = True
    env["authority"].technical = ("worker_timeout",)
    assert run_rules(package(env, criterion="R4.functional_tests")).label == "INSUFFICIENT"
    env["authority"].technical = ()
    assert run_rules(package(env, criterion="R4.functional_tests")).label == "NOT_MET"


def test_declared_categories_and_repeated_faq_do_not_grant_coverage_met(env):
    config = AssistantConfig(id="config", session_id="s", domains=("stable_faq",), participants=20)
    tests = []
    refs = []
    for n, category in enumerate(["normal", "dynamic"]):
        oid = "test" + str(n)
        t = AssistantTestResult(
            id=oid,
            session_id="s",
            query="同一个未命中问题",
            config=EffectiveConfig(requested=config, effective=config),
            config_ref=ObjectRef(
                session_id="s", kind="config", object_id=config.id, version=1, config_version=0
            ),
            execution=ExecutionMetadata(
                executed_at=datetime(2026, 10, 6, 13, tzinfo=timezone.utc),
                executor=env["auth"].executor,
                source_versions={},
                indexed_versions={},
                used_versions={},
                chunks=(),
                projection_actor="learner",
                attempts=(),
                cost_complete=False,
            ),
            status="fallback",
            answer="受控记录：无知识条目命中，转人工。",
            citations=(),
            as_of=INITIAL,
            declared_category=category,
        )
        tests.append(t)
        refs.append(env["authority"].add("test", oid, 1, t.model_dump_json()))
    env["authority"].tests = tuple(tests)
    env["authority"].test_refs = tuple(refs)
    result = run_rules(package(env, criterion="R4.functional_tests"))
    assert result.label == "PARTIAL" and result.rule_bound.upper == "MET"


@pytest.mark.parametrize("case", ["future", "foreign", "denied", "version", "quote"])
def test_references_reject_wrong_identity_time_or_quote(env, case):
    source = env["authority"].sources[("event", "ledger", 1, None)].ref
    if case == "future":
        source = source.model_copy(update={"observed_at_seq": 6})
    if case == "foreign":
        source = source.model_copy(update={"session_id": "other"})
    if case == "denied":
        env["authority"].denied.add("ledger")
    if case == "version":
        env["authority"].sources[("event", "ledger", 2, None)] = env["authority"].sources[
            ("event", "ledger", 1, None)
        ]
        source = source.model_copy(update={"version": 2})
    if case == "quote":
        source = source.model_copy(update={"quote": "未出现的原句", "span_start": 0, "span_end": 6})
    item = package(env, refs=(source,))
    assert item.completeness == "missing" and item.rule_context["source_issues"]
    assert (
        all(c.ref != source for c in item.candidate_evidence)
        if case in {"foreign", "version", "quote", "future"}
        else True
    )


def test_missing_optional_object_is_explicit_and_stale_fact_cannot_tighten_bound(env):
    absent = EvidenceRefV2(
        session_id="s", kind="test", object_id="missing", version=1, observed_at_seq=5
    )
    explicit = package(env, refs=(absent,))
    assert explicit.completeness == "missing" and explicit.missing_refs[0].object_id == "missing"
    item = package(env, expected_refs=(absent,))
    assert item.completeness == "missing" and item.rule_context["source_issues"]
    assert not item.missing_refs  # Internal unavailable-source identifiers are not echoed.
    a = env["authority"]
    old = a.sources[("event", "ledger", 1, None)]
    a.sources[("event", "ledger", 1, None)] = replace(
        old, ref=old.ref.model_copy(update={"valid_until_seq": 5})
    )
    assert run_rules(package(env)).label == "INSUFFICIENT"


def advice(package, label="MET", citation=None):
    candidate_id = (
        package.candidate_evidence[0].id
        if citation is None
        else next(
            (c.id for c in package.candidate_evidence if c.ref == citation), "unknown-candidate"
        )
    )
    return json.dumps(
        {
            "criterion": package.criterion,
            "label": label,
            "applicability": package.applicability,
            "explanation": "有可定位的依据，供复核。",
            "citation_ids": [candidate_id],
        },
        ensure_ascii=False,
    )


def test_judge_invalid_citation_does_not_retry_or_promote_advice(env):
    item = package(env, criterion="R6.comparison")
    foreign = item.candidate_evidence[0].ref.model_copy(update={"session_id": "foreign"})
    model = ScriptedModel(
        [ModelReply(text=advice(item, citation=foreign)), ModelReply(text=advice(item))]
    )
    result = AdvisoryJudge(model, lambda p, a: "supported").evaluate(item)
    assert (
        len(model.calls) == 1 and result.item.source == "pending" and result.item.rule_bound is None
    )
    assert score_bounds([result.item])["lower"] == 0


def test_failed_model_or_unverified_support_stays_pending_and_redacts_error(env):
    item = package(env, criterion="R6.comparison")
    model = ScriptedModel([ModelReply(text="invalid"), ModelReply(text="still invalid")])
    result = AdvisoryJudge(model).evaluate(item)
    assert len(model.calls) == 1 and result.item.label == "INSUFFICIENT"
    unverified = AdvisoryJudge(ScriptedModel([ModelReply(text=advice(item))])).evaluate(item)
    assert (
        unverified.item.source == "pending"
        and unverified.attempts[0]["status"] == "support_pending"
    )

    class Broken:
        revision = "unavailable-test"

        def complete(self, *args):
            raise RuntimeError("PRIVATE_SECRET_NOT_FOR_OUTPUT")

    failed = AdvisoryJudge(Broken()).evaluate(item)
    assert "PRIVATE_SECRET" not in str(failed) and len(failed.attempts) == 1


def test_model_input_excludes_rule_context_and_kind_does_not_determine_comparison(env):
    item = package(env, criterion="R6.comparison")
    assert "rule_context" not in model_input(item)
    assert "facts" not in model_input(item)
    # Equal natural-language content from different product representations has
    # the same semantic payload; no options-kind condition enters the engine.
    first = model_input(item)["candidate_evidence"][0]["text"]
    env["authority"].add("product", "p1", 1, first)
    same = package(env, criterion="R6.comparison")
    assert model_input(same) == model_input(item)


def test_review_is_nonterminal_and_worker_uses_fixed_historical_input(env):
    created = review(env, purpose="commitment", scope=("R3.capacity",))
    with env["engine"].connect() as c:
        state = env["authority"].state(c, env["auth"], lock=False)
    assert state.status == "active" and state.business_seq == 5
    env["authority"].capacity = 1  # Represents later upstream changes; must not be reread.
    assert env["service"].run_once()
    job = env["service"].job(env["auth"], created["job_id"])
    assert job["status"] == "completed"
    report = env["service"].get(env["auth"], "feedback", job["feedback_id"])
    assert report["as_of"]["business_seq"] == 5 and report["items"][0]["label"] == "INSUFFICIENT"
    assert report["mode"] == "advisory" and report["independent_understanding"] == "unobserved"
    with env["service"].repository.transaction() as conn:
        frozen = env["service"].repository.get(conn, "s", "review", created["review"]["id"])[
            "frozen"
        ]
    assert frozen["packages"][0]["rule_context"]["facts"]["capacity"] == 30


def test_submit_feedback_revision_resubmit_keeps_old_snapshots_and_replays(env):
    first = execute(
        env,
        "submissions.create",
        {"decision": "no_go", "products": [product_ref().model_dump(mode="json")]},
    )["submission"]
    request = execute(
        env,
        "feedback.request",
        {"subject": ref("s", "submission", first["id"]).model_dump(mode="json")},
    )
    assert env["service"].run_once()
    job = env["service"].job(env["auth"], request["job_id"])
    old_report = env["service"].get(env["auth"], "feedback", job["feedback_id"])
    parent_hash = digest(first)
    feedback_hash = digest(old_report)
    cmd = command(
        env,
        "revision_cycles.begin",
        {
            "parent_submission": ref("s", "submission", first["id"]).model_dump(mode="json"),
            "reason": "补充访谈和替代方案",
        },
    )
    cycle = env["service"].execute(env["auth"], cmd)
    assert env["service"].execute(env["auth"], cmd) == cycle
    with env["engine"].connect() as c:
        current = env["authority"].state(c, env["auth"], lock=False)
    env["authority"].add("product", "p1", 2, "加入访谈依据后的新决定。", point(current))
    second = execute(
        env,
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [product_ref(2).model_dump(mode="json")]},
    )["submission"]
    assert second["cycle"]["object_id"] == cycle["cycle"]["id"] and second["id"] != first["id"]
    assert digest(env["service"].get(env["auth"], "submission", first["id"])) == parent_hash
    assert digest(env["service"].get(env["auth"], "feedback", job["feedback_id"])) == feedback_hash
    assert first["decision"] == "no_go" and all(
        i["label"] != "NOT_MET" for i in old_report["items"] if i["source"] == "verified_rule"
    )


def test_concurrent_revision_and_rollback_leave_no_half_cycle(env):
    first = execute(
        env,
        "submissions.create",
        {"decision": "launch", "products": [product_ref().model_dump(mode="json")]},
    )["submission"]
    payload = {
        "parent_submission": ref("s", "submission", first["id"]).model_dump(mode="json"),
        "reason": "修订",
    }
    cmd = command(env, "revision_cycles.begin", payload)
    env["authority"].failure = True
    with pytest.raises(RuntimeError):
        env["service"].execute(env["auth"], cmd)
    with env["engine"].connect() as c:
        assert env["authority"].state(c, env["auth"], lock=False).status == "submitted"
        assert (
            c.execute(
                select(func.count())
                .select_from(records)
                .where(records.c.kind == "cycle", records.c.id != "initial")
            ).scalar_one()
            == 0
        )
    env["authority"].failure = False
    other = cmd.model_copy(update={"request_id": "concurrent-other"})

    def run(c):
        try:
            return env["service"].execute(env["auth"], c)
        except ProtocolError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(run, [cmd, other]))
    assert sum(isinstance(x, dict) for x in outcomes) == 1 and "version_conflict" in outcomes


def test_v1_terminal_and_bundle_change_cannot_be_reopened(env):
    first = execute(
        env,
        "submissions.create",
        {"decision": "launch", "products": [product_ref().model_dump(mode="json")]},
    )["submission"]
    payload = {
        "parent_submission": ref("s", "submission", first["id"]).model_dump(mode="json"),
        "reason": "修订",
    }
    env["authority"].protocol_value = "v1"
    with pytest.raises(ProtocolError, match="v2 required"):
        execute(env, "revision_cycles.begin", payload)
    env["authority"].protocol_value = "v2"
    env["authority"].bundle = env["authority"].bundle.model_copy(
        update={"evaluation": FileRef(path="new.json", sha256="4" * 64)}
    )
    with pytest.raises(ProtocolError, match="session bundle changed"):
        execute(env, "revision_cycles.begin", payload)


def test_queue_revocation_old_lease_fencing_and_restart(env):
    created = review(env)
    repo = env["service"].repository
    now = [10.0]
    repo.clock = lambda: now[0]
    old = repo.claim(lease_seconds=1)
    now[0] = 12.0
    new = repo.claim(lease_seconds=30)
    assert new["attempt"] == 2
    report, diagnostics = env["service"].evaluate_job(new)
    with pytest.raises(ProtocolError, match="lease lost"):
        repo.finish(old, report, diagnostics)
    repo.finish(new, report, diagnostics)
    restarted = create_service(env["engine"], env["authority"])
    assert restarted.job(env["auth"], created["job_id"])["status"] == "completed"
    assert not restarted.run_once()
    second = review(env)
    env["authority"].revoked = True
    assert env["service"].run_once()
    env["authority"].revoked = False
    failed = env["service"].job(env["auth"], second["job_id"])
    assert failed["status"] == "failed" and failed["error_code"] == "credential_revoked"


def test_router_does_not_accept_client_rule_facts_or_leak_private_errors(env):
    app = FastAPI()
    app.include_router(create_router(env["service"], lambda: env["auth"]))
    client = TestClient(app)
    cmd = command(
        env,
        "reviews.create",
        {
            "subjects": [product_ref().model_dump(mode="json")],
            "purpose": "exploration",
            "scope": ["R6.comparison"],
        },
    )
    created = client.post("/sessions/s/reviews", json=cmd.model_dump(mode="json"))
    assert created.status_code == 200
    assert created.json()["review"]["executor"]["kind"] == "human"
    bad = cmd.model_copy(
        update={
            "request_id": "bad",
            "payload": {**cmd.payload, "rule_context": {"capacity": 1000, "secret": "DO_NOT_ECHO"}},
        }
    )
    response = client.post("/sessions/s/reviews", json=bad.model_dump(mode="json"))
    assert response.status_code == 422 and "DO_NOT_ECHO" not in response.text
    assert (
        client.get("/sessions/other/reviews/" + created.json()["review"]["id"]).status_code == 404
    )


def test_rules_pending_for_system_failure_cannot_be_overwritten_by_model_negative(env):
    env["authority"].logs_complete = False
    item = package(env, criterion="R4.functional_tests")
    model = ScriptedModel([ModelReply(text=advice(item, label="NOT_MET"))])
    report, _ = FeedbackEngine(AdvisoryJudge(model, lambda p, a: "supported")).evaluate(
        "s", ref("s", "review", "r"), env["authority"].bundle.evaluation, INITIAL, (item,)
    )
    assert report.items[0].label == "INSUFFICIENT" and report.items[0].source == "pending"
    assert model.calls == [] and report.verified_coverage == 0


def test_options_and_verbatim_text_have_equal_semantic_projection(env):
    structured = OptionsPayload(
        options=(
            Option(id="a", title="稳定域小试点", rationale="更新负担小"),
            Option(id="b", title="继续人工", rationale="保留核验能力"),
        )
    )
    executor = env["auth"].executor
    common = {
        "product_id": "p1",
        "session_id": "s",
        "version": 1,
        "cycle": ref("s", "cycle", "initial"),
        "author": executor,
        "executor": executor,
        "created_at": datetime(2026, 10, 6, tzinfo=timezone.utc),
    }
    options = WorkProductVersion(
        **common,
        kind="options",
        content="",
        structured_payload=structured,
        content_hash=digest(
            {"content": "", "structured_payload": structured.model_dump(mode="json")}
        ),
    )
    text = product_text(options)
    ordinary = WorkProductVersion(
        **common,
        kind="text",
        content=text,
        content_hash=digest({"content": text, "structured_payload": None}),
    )
    assert product_text(options) == product_text(ordinary)
    env["authority"].add("product", "p1", 1, product_text(options))
    first = package(env, criterion="R6.comparison")
    env["authority"].add("product", "p1", 1, product_text(ordinary))
    second = package(env, criterion="R6.comparison")
    assert model_input(first) == model_input(second) and first.input_hash == second.input_hash


def test_reasoned_no_go_and_uninvestigated_no_go_are_not_enum_rules(env):
    # Controlled advice/support responses test routing only, not real semantic
    # quality. Both cases keep the same no_go decision and applicable duties.
    outputs = []
    for text, label in [
        ("先比较替代方案、核验价值和风险后暂缓；下周补访谈。", "MET"),
        ("未调查，直接放弃。", "NOT_MET"),
    ]:
        env["authority"].add("product", "p1", 1, text)
        item = package(env, criterion="decision.rationale", decision="no_go")
        result = AdvisoryJudge(
            ScriptedModel([ModelReply(text=advice(item, label))]), lambda p, a: "supported"
        ).evaluate(item)
        assert (
            item.applicability == "applicable"
            and result.item.source == "model_advice"
            and result.item.rule_bound is None
        )
        outputs.append(result.item.label)
    assert outputs == ["MET", "NOT_MET"]


def test_overflow_preserves_capacity_but_blocks_semantic_advice(env):
    env["authority"].add("product", "p1", 1, "长正文" * 15000)
    factual = package(env, budget=1800)
    semantic = package(env, criterion="R6.comparison", budget=1800)
    model = ScriptedModel([])
    report, diagnostics = FeedbackEngine(AdvisoryJudge(model)).evaluate(
        "s",
        ref("s", "review", "r"),
        env["authority"].bundle.evaluation,
        INITIAL,
        (factual, semantic),
    )
    assert report.items[0].source == "verified_rule" and report.items[0].label == "MET"
    assert report.items[1].source == "pending" and model.calls == []
    assert diagnostics["score_bounds"]["lower"] is None  # No invented aggregate rubric weights.


def test_review_question_and_provider_revision_are_fixed_at_request(env):
    model = ScriptedModel([])
    env["service"].engine = FeedbackEngine(AdvisoryJudge(model))
    created = review(env, purpose="option", scope=("R6.comparison",))
    with env["engine"].connect() as conn:
        record = env["service"].repository.get(conn, "s", "review", created["review"]["id"])
    assert "请说明依据。" in record["frozen"]["packages"][0]["claim"]
    replacement = ScriptedModel([])
    replacement.revision = "replacement-test-model"
    env["service"].engine = FeedbackEngine(AdvisoryJudge(replacement))
    assert env["service"].run_once()
    job = env["service"].job(env["auth"], created["job_id"])
    report = env["service"].get(env["auth"], "feedback", job["feedback_id"])
    assert report["items"][0]["source"] == "pending" and report["mode"] == "advisory"
    assert replacement.calls == []
    with env["engine"].connect() as conn:
        saved = env["service"].repository.get(conn, "s", "feedback", job["feedback_id"])
    assert (
        saved["diagnostics"]["criterion_attempts"][0]["attempts"][0]["status"]
        == "revision_mismatch"
    )


def test_changed_body_or_permission_scope_cannot_replay_cached_private_response(env):
    cmd = command(
        env,
        "reviews.create",
        {
            "subjects": [product_ref().model_dump(mode="json")],
            "purpose": "exploration",
            "scope": [],
        },
        "fixed",
    )
    first = env["service"].execute(env["auth"], cmd)
    assert env["service"].execute(env["auth"], cmd) == first
    altered = cmd.model_copy(update={"payload": {**cmd.payload, "purpose": "commitment"}})
    with pytest.raises(ProtocolError, match="request id reused"):
        env["service"].execute(env["auth"], altered)
    restricted = env["auth"].model_copy(update={"allowed_objects": ("another-work",)})
    with pytest.raises(ProtocolError, match="request id reused"):
        env["service"].execute(restricted, cmd)


def test_review_creation_failure_rolls_back_review_job_and_request_together(env):
    env["authority"].failure = True
    with pytest.raises(RuntimeError):
        review(env)
    with env["engine"].connect() as conn:
        assert conn.execute(select(func.count()).select_from(records)).scalar_one() == 0
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one() == 0
        assert conn.execute(select(func.count()).select_from(requests)).scalar_one() == 0
        assert env["authority"].state(conn, env["auth"], lock=False).workspace_revision == 0


def test_cycle_close_is_a_new_version_and_feedback_retry_is_bounded_and_recorded(env):
    created = execute(
        env,
        "submissions.create",
        {"decision": "launch_narrow", "products": [product_ref().model_dump(mode="json")]},
    )["submission"]
    assert env["service"].get(env["auth"], "cycle", "initial", version=1)["status"] == "open"
    assert env["service"].get(env["auth"], "cycle", "initial", version=2)["status"] == "submitted"
    request = execute(
        env,
        "feedback.request",
        {"subject": ref("s", "submission", created["id"]).model_dump(mode="json")},
    )
    env["authority"].revoked = True
    assert env["service"].run_once()
    env["authority"].revoked = False
    assert env["service"].job(env["auth"], request["job_id"])["status"] == "failed"
    execute(
        env,
        "feedback.request",
        {"subject": ref("s", "submission", created["id"]).model_dump(mode="json"), "retry": True},
    )
    assert env["service"].run_once()
    assert env["service"].job(env["auth"], request["job_id"])["status"] == "completed"
    with env["engine"].connect() as conn:
        outcomes = (
            conn.execute(select(attempts.c.status).where(attempts.c.job_id == request["job_id"]))
            .scalars()
            .all()
        )
    assert sorted(outcomes) == ["completed", "failed"]


def test_pipeline_does_not_penalize_agent_executor_or_count_prompt_context_as_understanding(env):
    human = review(env, purpose="commitment", scope=("R3.capacity",))
    assert env["service"].run_once()
    hjob = env["service"].job(env["auth"], human["job_id"])
    h = env["service"].get(env["auth"], "feedback", hjob["feedback_id"])
    env["auth"] = env["auth"].model_copy(
        update={
            "executor": Executor(
                id="byo-agent", kind="external_agent", delegation_id="delegation-fixture"
            ),
            "credential_id": "agent-fixture",
        }
    )
    agent = review(env, purpose="commitment", scope=("R3.capacity",))
    assert env["service"].run_once()
    ajob = env["service"].job(env["auth"], agent["job_id"])
    a = env["service"].get(env["auth"], "feedback", ajob["feedback_id"])
    assert h["items"] == a["items"] and h["verified_coverage"] == a["verified_coverage"]
    assert a["independent_understanding"] == h["independent_understanding"] == "unobserved"


def test_declared_submit_and_review_capabilities_cannot_be_bypassed(env):
    body = {"decision": "no_go", "products": [product_ref().model_dump(mode="json")]}
    actor = env["auth"].model_copy(update={"capabilities": ("read", "act")})
    with pytest.raises(ProtocolError, match="capability denied"):
        env["service"].execute(actor, command(env, "submissions.create", body))
    colleague = env["auth"].model_copy(update={"actor_id": "supervisor"})
    with pytest.raises(ProtocolError, match="capability denied"):
        env["service"].execute(colleague, command(env, "submissions.create", body))


def test_oversize_question_header_keeps_rules_and_never_calls_model(env):
    env["service"].model_bytes = 512
    model = ScriptedModel([])
    env["service"].engine = FeedbackEngine(AdvisoryJudge(model))
    created = execute(
        env,
        "reviews.create",
        {
            "subjects": [product_ref().model_dump(mode="json")],
            "purpose": "commitment",
            "scope": ["R3.capacity", "R6.comparison"],
            "question": "问题" * 400,
        },
    )
    assert env["service"].run_once()
    job = env["service"].job(env["auth"], created["job_id"])
    report = env["service"].get(env["auth"], "feedback", job["feedback_id"])
    assert (
        report["items"][0]["label"] == "INSUFFICIENT"
        and report["items"][1]["label"] == "INSUFFICIENT"
    )
    with env["service"].repository.transaction() as conn:
        frozen = env["service"].repository.get(conn, "s", "review", created["review"]["id"])[
            "frozen"
        ]
    assert frozen["packages"][0]["rule_context"]["facts"]["capacity"] == 30
    assert model.calls == []


def test_active_session_cannot_silently_change_evaluation_bundle(env):
    first = review(env)
    env["authority"].bundle = env["authority"].bundle.model_copy(
        update={"evaluation": FileRef(path="other.json", sha256="5" * 64)}
    )
    with pytest.raises(ProtocolError, match="session bundle changed"):
        review(env)
    assert (
        env["service"].get(env["auth"], "review", first["review"]["id"])["evaluation"]["sha256"]
        == "3" * 64
    )


def test_evidence_links_resolve_exact_versions_and_missing_history_does_not_substitute_latest(env):
    submitted = execute(
        env,
        "submissions.create",
        {"decision": "launch", "products": [product_ref().model_dump(mode="json")]},
    )["submission"]
    created = execute(
        env,
        "feedback.request",
        {"subject": ref("s", "submission", submitted["id"]).model_dump(mode="json")},
    )
    env["service"].run_once()
    job = env["service"].job(env["auth"], created["job_id"])
    links = env["service"].evidence_links(env["auth"], job["feedback_id"])
    assert links and any(x["criterion"] == "R3.capacity" for x in links)
    selected = next(
        x for x in links if x["ref"]["object_id"] == "ledger" and x["criterion"] == "R3.capacity"
    )
    result = env["service"].read_evidence(
        env["auth"], job["feedback_id"], selected["criterion"], selected["evidence_id"]
    )
    assert result["ref"]["version"] == 1 and "30" in result["content"]
    env["authority"].sources.pop(("event", "ledger", 1, None))
    env["authority"].add("event", "ledger", 2, "后来容量改为10")
    with pytest.raises(ProtocolError, match="historical evidence missing"):
        env["service"].read_evidence(
            env["auth"], job["feedback_id"], selected["criterion"], selected["evidence_id"]
        )
    with pytest.raises(ProtocolError, match="not found"):
        env["service"].read_evidence(
            env["auth"], job["feedback_id"], "other-criterion", selected["evidence_id"]
        )


def test_engine_rejects_mixed_historical_windows_or_sessions(env):
    item = package(env)
    with pytest.raises(ProtocolError, match="evaluation scope mismatch"):
        FeedbackEngine().evaluate(
            "s",
            ref("s", "review", "r"),
            env["authority"].bundle.evaluation,
            INITIAL.model_copy(update={"business_seq": 6}),
            (item,),
        )
    with pytest.raises(ProtocolError, match="feedback session mismatch"):
        FeedbackEngine().evaluate(
            "other", ref("s", "review", "r"), env["authority"].bundle.evaluation, INITIAL, (item,)
        )


def test_queued_review_recovers_in_a_fresh_python_process(env):
    created = review(env, purpose="commitment", scope=("R3.capacity",))
    script = """import importlib.util,json,sys
from sqlalchemy import create_engine
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[2]).parent))
from test_w05_legacy_service_fixture import create_service
spec=importlib.util.spec_from_file_location('w05_process_fixture',sys.argv[2])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
authority=module.UpstreamDouble();authority.capacity=1
engine=create_engine(sys.argv[1]);service=create_service(engine,authority)
print(json.dumps({'processed':service.run_once()}));engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(env["engine"].url), str(Path(__file__).resolve())],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["processed"] is True
    job = env["service"].job(env["auth"], created["job_id"])
    assert job["status"] == "completed"
    report = env["service"].get(env["auth"], "feedback", job["feedback_id"])
    assert report["items"][0]["label"] == "INSUFFICIENT"
    with env["service"].repository.transaction() as conn:
        frozen = env["service"].repository.get(conn, "s", "review", created["review"]["id"])[
            "frozen"
        ]
    assert frozen["packages"][0]["rule_context"]["facts"]["capacity"] == 30
    assert not env["service"].run_once()


def test_feedback_save_and_workflow_metadata_roll_back_together(env):
    created = review(env, purpose="commitment", scope=("R3.capacity",))
    repo = env["service"].repository
    job = repo.claim()
    report, diagnostics = env["service"].evaluate_job(job)
    with env["engine"].connect() as conn:
        before = env["authority"].state(conn, env["auth"], lock=False)
    env["authority"].failure = True
    with pytest.raises(RuntimeError):
        repo.finish(job, report, diagnostics)
    with env["engine"].connect() as conn:
        assert env["authority"].state(conn, env["auth"], lock=False) == before
        assert (
            conn.execute(
                select(func.count()).select_from(records).where(records.c.kind == "feedback")
            ).scalar_one()
            == 0
        )
    env["authority"].failure = False
    repo.finish(job, report, diagnostics)
    assert env["service"].job(env["auth"], created["job_id"])["status"] == "completed"


def test_queued_job_uses_granted_public_action_and_explicit_retry_gets_fresh_authorization(env):
    agent = env["auth"].model_copy(
        update={
            "credential_id": "review-agent",
            "allowed_actions": ("reviews.create", "reviews.read"),
            "executor": Executor(id="agent", kind="external_agent", delegation_id="d"),
        }
    )
    cmd = command(
        env,
        "reviews.create",
        {
            "subjects": [product_ref().model_dump(mode="json")],
            "purpose": "commitment",
            "scope": ["R3.capacity"],
        },
    )
    created = env["service"].execute(agent, cmd)
    assert env["service"].run_once()
    assert env["service"].job(agent, created["job_id"])["status"] == "completed"
    # A separate job fails after revocation. A human may explicitly retry it;
    # the old failed attempt's identity must remain in the attempt history.
    other = env["service"].execute(agent, command(env, "reviews.create", cmd.payload))
    env["authority"].revoked_ids.add("review-agent")
    assert env["service"].run_once()
    assert env["service"].job(env["auth"], other["job_id"])["status"] == "failed"
    execute(
        env,
        "feedback.request",
        {
            "subject": ref("s", "review", other["review"]["id"]).model_dump(mode="json"),
            "retry": True,
        },
    )
    assert env["service"].run_once()
    assert env["service"].job(env["auth"], other["job_id"])["status"] == "completed"
    with env["engine"].connect() as conn:
        history = conn.execute(
            select(attempts.c.auth, attempts.c.operation).where(
                attempts.c.job_id == other["job_id"]
            )
        ).all()
    assert {(json.loads(a)["credential_id"], op) for a, op in history} == {
        ("review-agent", "reviews.create"),
        ("trusted-fixture", "feedback.request"),
    }


def test_model_cites_neutral_ids_without_reprinting_long_quotes(env):
    body = "一项待核查的判断。" * 300
    env["authority"].add("product", "p1", 1, body)
    item = package(env, criterion="R6.comparison", purpose="option")
    payload = canonical(model_input(item))
    assert item.completeness == "complete" and payload.count(body) == 1
    reply = advice(item)
    assert len(reply.encode()) < 1000 and body not in reply
    model = ScriptedModel([ModelReply(text=reply)])
    result = AdvisoryJudge(model, lambda p, a: "supported").evaluate(item)
    assert result.item.source == "model_advice"
    assert result.item.citations == (item.candidate_evidence[0].ref,)
    assert "quote" not in json.loads(model.calls[0][1]["content"])["candidate_evidence"][0]


def test_semantic_judge_can_choose_within_non_point_rule_interval(env):
    config = AssistantConfig(id="config", session_id="s", domains=("stable_faq",), participants=20)
    run = AssistantTestResult(
        id="controlled-test",
        session_id="s",
        query="未命中问题",
        config=EffectiveConfig(requested=config, effective=config),
        config_ref=ObjectRef(
            session_id="s", kind="config", object_id=config.id, version=1, config_version=0
        ),
        execution=ExecutionMetadata(
            executed_at=datetime(2026, 10, 6, 13, tzinfo=timezone.utc),
            executor=env["auth"].executor,
            source_versions={},
            indexed_versions={},
            used_versions={},
            chunks=(),
            projection_actor="learner",
            attempts=(),
            cost_complete=False,
        ),
        status="fallback",
        answer="受控记录：无知识条目命中，转人工。",
        citations=(),
        as_of=INITIAL,
    )
    env["authority"].tests = (run,)
    env["authority"].test_refs = (env["authority"].add("test", run.id, 1, run.model_dump_json()),)
    item = package(env, criterion="R4.functional_tests")
    model = ScriptedModel([ModelReply(text=advice(item, "MET"))])
    report, diagnostics = FeedbackEngine(AdvisoryJudge(model, lambda p, a: "supported")).evaluate(
        "s", ref("s", "review", "r"), env["authority"].bundle.evaluation, INITIAL, (item,)
    )
    assert (
        len(model.calls) == 1
        and report.items[0].label == "MET"
        and report.items[0].source == "model_advice"
    )
    assert json.loads(model.calls[0][1]["content"])["rule_bound"]["lower"] == "PARTIAL"
    assert diagnostics["rule_items"][0]["label"] == "PARTIAL"
    assert diagnostics["score_bounds"]["lower"] == 0.5 and diagnostics["score_bounds"]["upper"] == 1
    assert (
        report.items[0].rule_bound is None
    )  # Public draft forbids model advice tightening bounds.
    assert "规则已核验区间：PARTIAL—MET" in report.items[0].explanation
    assert {json.dumps(r, sort_keys=True) for r in diagnostics["rule_items"][0]["citations"]} <= {
        json.dumps(r.model_dump(mode="json"), sort_keys=True) for r in report.items[0].citations
    }


def test_production_cannot_start_the_retired_private_store_or_router():
    from career_lab.api.reviews_v2 import (
        create_service as production_service,
        create_router as production_router,
    )
    from career_lab.storage.revisions import (
        register_tables as production_tables,
        RevisionRepository,
    )

    class UntouchableEngine:
        def __getattr__(self, name):
            raise AssertionError("retired path tried to access persistence")

    for factory in (production_service, production_router, production_tables, RevisionRepository):
        with pytest.raises(ProtocolError) as error:
            factory(UntouchableEngine(), authority=None)
        assert error.value.code == "module_unavailable" and error.value.status == 503
