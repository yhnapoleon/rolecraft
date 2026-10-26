"""L3 seam test: real store/Gateway/test executor, synthetic enrollment and design.

L4 owns HTTP registration. This test installs only the L3 models into an isolated
store and executes their Mutation handlers; no production whitelist is bypassed.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from career_lab.aipm.evaluation.models import BatchRead
from career_lab.aipm.evaluation.service import OBJECT_MODELS, EvaluationService
from career_lab.aipm.types import AipmDesign, AipmProfile, TriageRow
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import Command, ObjectRef, ProtocolError
from career_lab.storage.v2_store import Mutation, ObjectWrite


@contextmanager
def seeded_batch(tmp_path):
    """Real store and Gateway with a synthetic enrollment, design, plan and one created batch."""
    app = create_runtime_app("sqlite:///" + str(tmp_path / "evaluation.db"))
    store = app.state.v2_store
    gateway = app.state.gateway
    with TestClient(app) as client:
        created = client.post(
            "/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"}
        ).json()
        sid = created["session_id"]
        auth = store.authenticate(sid, created["token"])
        service = EvaluationService(gateway.request_result)
        for kind, model in {
            **OBJECT_MODELS,
            "aipm_profile": AipmProfile,
            "aipm_design": AipmDesign,
        }.items():
            # L4's runtime mount may already register these; install only what is missing.
            if kind not in store.object_models:
                store.register_object(kind, model)

        def make(operation, payload, request_id):
            state = store.view(auth).state
            return Command(
                schema_version=2,
                operation=operation,
                request_id=request_id,
                expected_version=state.business_seq,
                expected_workspace_revision=state.workspace_revision,
                payload=payload,
            )

        def write(obj, kind):
            return ObjectWrite(
                ref=ObjectRef(session_id=sid, kind=kind, object_id=obj.id, version=1),
                expected_head=0,
                content=obj.model_dump(mode="json"),
            )

        profile = AipmProfile(
            session_id=sid,
            content_revision="fixture-v1",
            scenario_hash="fixture",
            work_language="zh",
            enrolled_at=datetime.now(UTC),
        )
        design = AipmDesign(
            id="design",
            session_id=sid,
            revision=1,
            rows=(
                TriageRow(
                    id="r",
                    need_ref="n",
                    user_request="解释差旅政策",
                    target_action="explain",
                    route="retrieval_generation",
                    rationale="查原文",
                    final_authority="named_human_role",
                ),
            ),
        )
        store.execute(
            auth,
            make("fixture.seed", {}, "seed"),
            lambda *_: Mutation(
                writes=(write(profile, "aipm_profile"), write(design, "aipm_design"))
            ),
        )
        plan_cmd = make(
            "work_products.create",
            {
                "kind": "test_plan",
                "title": "评测计划",
                "structured_payload": {
                    "type": "test_plan",
                    "cases": [
                        {
                            "id": "q",
                            "query": "差旅报销标准是什么？",
                            "declared_expected": "引用当前政策，不能批准报销。",
                        },
                    ],
                },
            },
            "plan",
        )
        gateway.dispatch(auth, "work_products.create", plan_cmd.model_dump(mode="json"))
        plan = next(o for o in store.view(auth).objects if o.ref.kind == "product")
        # The plan service assigns stable case identities; selections use the saved id.
        case_id = plan.content["structured_payload"]["cases"][0]["id"]
        create_cmd = make(
            "aipm.batch.create",
            {
                "plan_ref": plan.ref.model_dump(mode="json"),
                "design_ref": ObjectRef(
                    session_id=sid, kind="aipm_design", object_id="design", version=1
                ).model_dump(mode="json"),
                "selections": [
                    {"case_id": case_id, "triage_row_id": "r", "coverage": "assistant_answer"}
                ],
            },
            "batch",
        )
        created_batch = store.execute(auth, create_cmd, service.create)
        batch = created_batch.result["batch"]
        yield SimpleNamespace(
            store=store,
            gateway=gateway,
            auth=auth,
            sid=sid,
            service=service,
            make=make,
            case_id=case_id,
            batch=batch,
            create=create_cmd,
        )
    store.db.engine.dispose()


def test_real_store_preserves_original_request_results_and_assessment_history(tmp_path):
    with seeded_batch(tmp_path) as s:
        store, gateway, auth, sid, service, make, case_id, batch = (
            s.store,
            s.gateway,
            s.auth,
            s.sid,
            s.service,
            s.make,
            s.case_id,
            s.batch,
        )
        assert store.execute(auth, s.create, service.create).replayed
        prepare = make(
            "aipm.batch.update",
            {
                "batch_id": batch["id"],
                "expected_revision": 1,
                "action": "prepare",
                "case_id": case_id,
            },
            "prepare",
        )
        ready = store.execute(auth, prepare, service.update)
        original = ready.result["command"]
        assert original["expected_workspace_revision"] == store.view(auth).state.workspace_revision
        gateway.dispatch(auth, "tests.create", original)
        # Replaying exactly the same original returns its result; there is still one test.
        gateway.dispatch(auth, "tests.create", original)
        assert len([o for o in store.view(auth).objects if o.ref.kind == "test"]) == 1
        reconciled = store.execute(
            auth,
            make(
                "aipm.batch.update",
                {
                    "batch_id": batch["id"],
                    "expected_revision": 2,
                    "action": "reconcile",
                    "case_id": case_id,
                },
                "recover",
            ),
            service.update,
        )
        batch = reconciled.result["batch"]
        assert batch["cases"][0]["status"] == "completed"
        batch_ref = ObjectRef(session_id=sid, kind="aipm_batch", object_id=batch["id"], version=3)
        for result in ("satisfied", "unknown"):
            store.execute(
                auth,
                make(
                    "aipm.assessment.record",
                    {
                        "batch_ref": batch_ref.model_dump(mode="json"),
                        "case_id": case_id,
                        "result": result,
                        "reason": "本人复核记录",
                    },
                    result,
                ),
                service.assess,
            )
        read = store.query(
            auth, lambda view: service.read(view, BatchRead(batch_id=batch["id"]), auth)
        ).result
        assert len(read["assessments"]) == 2
        assert read["summary"]["all"]["satisfaction_rate"] is None
        assert read["summary"]["all"]["unknown"] == 1


def _update(s, action, revision, key):
    payload = {
        "batch_id": s.batch["id"],
        "expected_revision": revision,
        "action": action,
        "case_id": s.case_id,
    }
    return s.store.execute(s.auth, s.make("aipm.batch.update", payload, key), s.service.update)


def _read(s):
    return s.store.query(
        s.auth, lambda view: s.service.read(view, BatchRead(batch_id=s.batch["id"]), s.auth)
    ).result


def test_unreceived_original_is_sent_again_only_while_its_bindings_hold(tmp_path):
    with seeded_batch(tmp_path) as s:
        original = _update(s, "prepare", 1, "prepare").result["command"]
        # The send never reached the server. Reading it back writes nothing.
        before = s.store.view(s.auth).state.workspace_revision
        lost = _update(s, "reconcile", 2, "lost")
        assert lost.result["batch"]["revision"] == 2
        assert s.store.view(s.auth).state.workspace_revision == before
        assert _read(s)["recovery"] == {s.case_id: "send_again"}
        # The person presses Send again: the same original, same request_id.
        s.gateway.dispatch(s.auth, "tests.create", original)
        assert _read(s)["recovery"] == {s.case_id: "in_progress"}
        with pytest.raises(ProtocolError, match="request exists"):
            _update(s, "reprepare", 2, "too-late")
        done = _update(s, "reconcile", 2, "found").result["batch"]["cases"][0]
        assert done["status"] == "completed"
        assert done["request_id"] == original["request_id"]
        assert len([o for o in s.store.view(s.auth).objects if o.ref.kind == "test"]) == 1


def test_moved_bindings_require_a_new_request_and_keep_the_old_one_out_of_counts(tmp_path):
    with seeded_batch(tmp_path) as s:
        original = _update(s, "prepare", 1, "prepare").result["command"]
        # Any later write moves the workspace revision the original was bound to.
        _update(s, "monitoring", 2, "unrelated-write")
        assert _read(s)["recovery"] == {s.case_id: "reprepare"}
        fresh = _update(s, "reprepare", 3, "reprepare").result["batch"]["cases"][0]
        assert fresh["original_command"] is None
        assert fresh["request_id"] != original["request_id"]
        assert [a["request_id"] for a in fresh["abandoned"]] == [original["request_id"]]
        command = _update(s, "prepare", 4, "prepare-again").result["command"]
        s.gateway.dispatch(s.auth, "tests.create", command)
        _update(s, "reconcile", 5, "found")
        summary = _read(s)["summary"]["all"]
        assert (summary["total"], summary["runnable"], summary["completed"]) == (1, 1, 1)
        # The abandoned original was never received and is never sent.
        with pytest.raises(ProtocolError, match="request not found"):
            s.service.request_reader(s.auth, original["request_id"])
