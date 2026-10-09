"""Assistant jobs use the shared durable queue, worker fence and Mutation commit."""

from typing import TYPE_CHECKING

from career_lab.api.modules import ExtensionRegistry, JobEnvelope, StoreJobHandler
from career_lab.assistant.v2.generation import PROMPT_REVISION, GenerationRecord
from career_lab.assistant.v2.service import Assistant, TestExecution
from career_lab.contracts.v2 import (
    AuthContext,
    Command,
    JsonValue,
    ObjectRef,
    ProtocolError,
    TestRequestV2,
    TestResultV2,
    digest,
)
from career_lab.runtime.provenance import execution_identity
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.storage.v2_store import EventDraft, JobRequest, Mutation, TransactionView, V2Store

if TYPE_CHECKING:
    from career_lab.scenarios.v2.module import ScenarioModule


def test_ref(result: TestResultV2) -> ObjectRef:
    return ObjectRef(
        session_id=result.session_id, kind="test", object_id=result.id, version=result.version
    )


def queue_generation(
    module: "ScenarioModule", snapshot: ScenarioSnapshot, command: Command, auth: AuthContext
) -> Mutation:
    # Run exactly the normal guards and retrieval without a provider; only enqueue afterwards.
    validated = Assistant(module.package).run(
        snapshot,
        TestRequestV2.model_validate(command.payload),
        auth,
        command.request_id,
        operation_name=command.operation,
    )
    effect = command.model_copy(
        update={
            "request_id": "assistant-effect-" + digest([auth.session_id, command.request_id])[:24],
        }
    )
    return Mutation(
        jobs=(
            JobRequest(
                name="v2.assistant",
                command=effect,
                sources=(validated.result.config_ref,),
                head_dependencies=(validated.result.config_ref,),
                state_dependencies=(
                    "config_version",
                    "resources",
                    "applied_milestones",
                    "status",
                    "cycle_id",
                ),
                context_hash=generation_identity(module, command, validated.result.config_ref),
            ),
        ),
        result={
            "status": "queued",
            "request": command.payload,
            "config_ref": validated.result.config_ref.model_dump(mode="json"),
            "provider": getattr(module.assistant.model, "provider", "openai-compatible"),
            "model_revision": module.assistant.model.revision,
            "prompt_revision": PROMPT_REVISION,
            "work_language": module.work_language,
        },
    )


def result_plan(module: "ScenarioModule", run: TestExecution) -> Mutation:
    result = run.result
    ref = test_ref(result)
    writes = [module.write(result, "test", 0)]
    response = {"test": result.model_dump(mode="json")}
    if result.config.requested.generator == "llm":
        model = module.assistant.model
        record = GenerationRecord(
            id=digest([result.id, "assistant-execution"]),
            session_id=result.session_id,
            test=ref,
            mode=run.provenance["mode"],
            error_code=result.error_code,
            provider=getattr(model, "provider", None),
            model_revision=getattr(model, "revision", None),
            prompt_hash=run.provenance.get("prompt_hash"),
            work_language=module.work_language,
            config_ref=result.config_ref,
            indexed_versions=result.execution.indexed_versions,
            candidates=result.execution.chunks,
            citations=result.citations,
            executor=result.execution.executor,
            code=execution_identity(),
            evaluation=module.bindings.evaluation,
        )
        writes.append(module.write(record, "assistant_execution", 0))
        response["generation"] = record.model_dump(mode="json")
    return Mutation(
        writes=tuple(writes),
        events=(
            EventDraft(
                type="test_assistant", visible_to=(result.execution.projection_actor,), refs=(ref,)
            ),
        ),
        result=response,
    )


def listed_generations(view: TransactionView, test_ids: set[str]) -> list[dict[str, JsonValue]]:
    visible = test_ids
    return [
        record.content
        for record in view.objects
        if record.ref.kind == "assistant_execution"
        and record.content["test"]["object_id"] in visible
    ]


def generation_identity(module: "ScenarioModule", command: Command, config_ref: ObjectRef) -> str:
    model = module.assistant.model
    return digest(
        [
            command.payload,
            config_ref.model_dump(mode="json"),
            getattr(model, "provider", None),
            getattr(model, "revision", None),
            getattr(model, "base_url", None),
            PROMPT_REVISION,
            module.work_language,
        ]
    )


def install_generation(registry: ExtensionRegistry, module: "ScenarioModule") -> None:
    registry.register_object_model("assistant_execution", GenerationRecord)

    def run(
        store: V2Store, view: TransactionView, envelope: JobEnvelope, auth: AuthContext
    ) -> Mutation:
        # The shared worker commits its claim before transport and refuses takeover calls.
        if view.worker_claim is None or view.worker_claim.attempt != 1:
            raise ProtocolError("assistant_retry_requires_user_action", status=409)
        config_ref = view.private_scenario_state.current_config
        if envelope.context.context_hash != generation_identity(
            module, envelope.command, config_ref
        ):
            raise ProtocolError("assistant_model_changed", status=409)
        return module.test_result(view, envelope.command, auth, generation_permitted=True)

    registry.register_job("v2.assistant", StoreJobHandler(run, retry_on_error=False))
