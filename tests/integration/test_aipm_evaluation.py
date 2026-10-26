"""L3 seam test: real store/Gateway/test executor, synthetic enrollment and design.

L4 owns HTTP registration. This test installs only the L3 models into an isolated
store and executes their Mutation handlers; no production whitelist is bypassed.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from career_lab.aipm.evaluation.models import BatchRead
from career_lab.aipm.evaluation.service import OBJECT_MODELS, EvaluationService
from career_lab.aipm.types import AipmDesign, AipmProfile, TriageRow
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import Command, ObjectRef
from career_lab.storage.v2_store import Mutation, ObjectWrite


def test_real_store_preserves_original_request_results_and_assessment_history(tmp_path):
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
        assert store.execute(auth, create_cmd, service.create).replayed
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
    store.db.engine.dispose()
