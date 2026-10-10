"""Continuity through installed operations and reconstructed worker/store instances."""

import json
from pathlib import Path
from typing import Literal

import pytest
from test_cooperative_help import Dialogue, assessment

from career_lab.api.modules import Gateway
from career_lab.api.vertical_runtime import build_registry
from career_lab.contracts.v2 import canonical, digest
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import ClaimedHandler, Worker
from career_lab.runtime.model_adapter import ModelAdapter, ModelReply, ScriptedModel
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.storage.role_memory import parse_public_reply
from career_lab.storage.v2_store import V2Store
from tests.support.scenario_packages import installed_locale_root


@pytest.mark.parametrize("language", ["zh", "en"])
def test_mem_01_unshared_new_version_stays_private_until_explicit_share(
    tmp_path: Path, language: str
) -> None:
    title = "容量笔记" if language == "zh" else "Capacity notes"
    old = "容量笔记：仅讨论30人。" if language == "zh" else "Capacity notes: discuss 30 users only."
    new = (
        "容量笔记：私下考虑80人。"
        if language == "zh"
        else "Capacity notes: privately consider 80 users."
    )
    note = "仅按已收到的版本" if language == "zh" else "Only the received versions"
    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    try:
        product = dialogue.command(
            "work_products.create",
            {
                "kind": "text",
                "title": title,
                "content": old,
            },
        )["result"]["ref"]
        share = dialogue.command(
            "work_products.shares.create",
            {
                "product_id": product["object_id"],
                "product_version": 1,
                "recipient_role": "tech_lead",
            },
        )["result"]["ref"]
        first = dialogue.command(
            "turns.create",
            {
                "role_id": "tech_lead",
                "text": title,
                "shares": [share],
            },
        )
        dialogue.worker.run_once()
        assert dialogue.jobs.get(first["result"]["queued_jobs"][0])["status"] == "completed"
        dialogue.command(
            "work_products.versions.create",
            {
                "product_id": product["object_id"],
                "expected_head": 1,
                "kind": "text",
                "title": title,
                "content": new,
            },
        )
        second = dialogue.ask(title)
        assert second["status"] == "completed", second
        shown = json.dumps(dialogue.reply(), ensure_ascii=False)
        assert old in shown and new not in shown and note in shown
        assert dialogue.reply()["result"]["result"]["content"]["received_versions_only"] is True
        share2 = dialogue.command(
            "work_products.shares.create",
            {
                "product_id": product["object_id"],
                "product_version": 2,
                "recipient_role": "tech_lead",
            },
        )["result"]["ref"]
        final = dialogue.command(
            "turns.create",
            {
                "role_id": "tech_lead",
                "text": title,
                "shares": [share2],
            },
        )
        dialogue.worker.run_once()
        assert dialogue.jobs.get(final["result"]["queued_jobs"][0])["status"] == "completed"
        shown = json.dumps(dialogue.reply(), ensure_ascii=False)
        assert new in shown and "v2" in shown
        assert dialogue.reply()["result"]["result"]["content"]["received_versions_only"] is True
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_mem_06_natural_dates_names_and_work_language_survive_review(
    tmp_path: Path, language: str
) -> None:
    from test_cooperative_help import assessment

    from career_lab.runtime.model_adapter import ModelReply, ScriptedModel

    original = "35-45 / 2026-10-31 / M1-M3 / scope_filter / human_fallback / Plan_A2-B2"
    answer = (
        f"你写的是“{original}”；这些仍是待核验条件。"
        if language == "zh"
        else f'You wrote "{original}"; these conditions still need verification.'
    )
    model = ScriptedModel(
        [
            ModelReply(text=answer),
            assessment(kinds=("business_judgment",)),
            ModelReply(text="private-source-999"),
        ]
    )
    dialogue = Dialogue(tmp_path, language, model)
    try:
        good = dialogue.ask(original)
        assert good["status"] == "completed", good
        assert dialogue.reply()["result"]["result"]["content"]["text"] == answer
        prompt = json.loads(model.calls[0][0]["content"].split("\nCONTEXT\n", 1)[1])
        assert prompt["work_language"] == language
        rejected = dialogue.ask("请继续" if language == "zh" else "Please continue")
        assert rejected["status"] == "failed" and rejected["error"] == "role_output_blocked"
        assert "private-source-999" not in json.dumps(dialogue.history(), ensure_ascii=False)
    finally:
        dialogue.close()


def test_mem_04_committed_call_survives_worker_reconstruction_until_explicit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from test_cooperative_help import assessment

    from career_lab.api.modules import Command, Gateway
    from career_lab.contracts.v2 import ProtocolError
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import ClaimedHandler, Worker, WorkerClaim
    from career_lab.runtime.model_adapter import ModelReply, ScriptedModel
    from career_lab.storage.v2_store import V2Store

    answer = "[经理委托：内部知识助手试点 · v1] 当前试点容量为30人。"
    model = ScriptedModel(
        [
            ModelReply(text=answer),
            assessment(),
            ModelReply(text=answer),
            assessment(),
        ]
    )
    dialogue = Dialogue(tmp_path, "zh", model)
    original_execute = dialogue.store.execute

    def interrupted_commit(*args: object, **kwargs: object) -> object:
        if kwargs.get("job_context") is not None:

            def fault(stage: str) -> None:
                if stage == "after_objects":
                    raise SystemExit("controlled exit before reply commit")

            kwargs["fault"] = fault
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(dialogue.store, "execute", interrupted_commit)
    rebuilt = None
    try:
        queued = dialogue.command(
            "turns.create", {"role_id": "tech_lead", "text": "当前容量是多少？"}
        )
        job_id = queued["result"]["queued_jobs"][0]
        with pytest.raises(SystemExit):
            dialogue.worker.run_once()
        failed = dialogue.jobs.get(job_id)
        assert failed["status"] == "running" and len(model.calls) == 2
        assert not [
            row for row in dialogue.history()["objects"] if row["ref"]["kind"] == "role_reply"
        ]
        rebuilt = V2Store(str(dialogue.store.db.engine.url))
        gateway = Gateway(rebuilt, dialogue.registry)
        repository = JobRepository(rebuilt.db)
        worker = Worker(
            repository,
            {
                "v2.role_turn": ClaimedHandler(
                    lambda payload, claim: gateway.run_job("v2.role_turn", payload, claim=claim),
                    retry_on_error=False,
                ),
            },
        )
        reclaimed = repository.claim_job("restarted-worker", now=time.time() + 120)
        assert reclaimed["id"] == job_id and reclaimed["attempt"] == 2
        with pytest.raises(ProtocolError) as error:
            gateway.run_job(
                "v2.role_turn", reclaimed["payload"], claim=WorkerClaim.from_job(reclaimed)
            )
        assert error.value.code == "role_model_call_already_claimed" and len(model.calls) == 2
        repository.fail(reclaimed, error.value.code, retry=False)
        current = rebuilt.view(dialogue.auth).state
        refresh = Command(
            schema_version=2,
            request_id="explicit-retry",
            operation="jobs.refresh",
            expected_version=current.business_seq,
            expected_workspace_revision=current.workspace_revision,
            payload={"job_id": failed["id"]},
        )
        rebuilt.refresh_job(dialogue.auth, refresh, failed["id"])
        worker.run_once()
        result = repository.get(failed["id"])
        assert result["status"] == "completed" and len(model.calls) == 4, result
        assert dialogue.reply()["result"]["result"]["content"]["text"] == answer
    finally:
        if rebuilt is not None:
            rebuilt.db.engine.dispose()
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_mem_05_narrower_delegation_cannot_recover_a_previously_shared_draft(
    tmp_path: Path, language: str
) -> None:
    from datetime import UTC, datetime, timedelta

    from career_lab.contracts.v2 import DelegationGrant, Executor

    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    owner = dialogue.auth
    secret = "PRIVATE_CAPACITY_NOTES_NEVER_RECOVER_UNDER_NARROW_SCOPE"
    try:
        product = dialogue.command(
            "work_products.create",
            {
                "kind": "text",
                "title": "Capacity notes",
                "content": secret,
            },
        )["result"]["ref"]
        share = dialogue.command(
            "work_products.shares.create",
            {
                "product_id": product["object_id"],
                "product_version": 1,
                "recipient_role": "tech_lead",
            },
        )["result"]["ref"]
        broad = DelegationGrant(
            id="broad",
            session_id=owner.session_id,
            actor_id="learner",
            executor=Executor(id="helper", kind="external_agent", delegation_id="broad"),
            capabilities=("read", "act"),
            allowed_actions=("turns.create",),
            allowed_objects=(product["object_id"], share["object_id"]),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        token = dialogue.store.issue_delegation(owner, broad)
        dialogue.auth = dialogue.store.authenticate(owner.session_id, token)
        first = dialogue.command(
            "turns.create",
            {
                "role_id": "tech_lead",
                "text": "Capacity notes",
                "shares": [share],
            },
        )
        dialogue.worker.run_once()
        assert dialogue.jobs.get(first["result"]["queued_jobs"][0])["status"] == "completed"
        dialogue.store.revoke_delegation(owner, "broad")
        narrow = broad.model_copy(
            update={
                "id": "narrow",
                "allowed_objects": (),
                "executor": Executor(id="helper", kind="external_agent", delegation_id="narrow"),
            }
        )
        token = dialogue.store.issue_delegation(owner, narrow)
        dialogue.auth = dialogue.store.authenticate(owner.session_id, token)
        job = dialogue.ask("试点容量" if language == "zh" else "pilot capacity")
        assert job["status"] == "completed", job
        dialogue.auth = owner
        shown = json.dumps(dialogue.reply(), ensure_ascii=False)
        assert secret not in shown and "30" in shown
        assert (
            "超出本次授权" if language == "zh" else "outside the current authorization"
        ) in shown
    finally:
        dialogue.auth = owner
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_reply_version_scope_is_explicit_and_legacy_bytes_are_preserved(
    tmp_path: Path, language: str
) -> None:
    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    try:
        job = dialogue.ask("当前容量是多少？" if language == "zh" else "What is the capacity?")
        assert job["status"] == "completed", job
        content = dialogue.reply()["result"]["result"]["content"]
        assert content["received_versions_only"] is False
        for absent in (
            {"generation_mode"},
            {"generation_mode", "received_versions_only"},
        ):
            legacy = {key: value for key, value in content.items() if key not in absent}
            restored = parse_public_reply(legacy)
            assert canonical(restored) == canonical(legacy)
            assert digest(restored) == digest(legacy)
            assert all(key not in restored.model_dump(mode="json") for key in absent)
        assert content == dialogue.reply()["result"]["result"]["content"]
    finally:
        dialogue.close()


def reply_model(mode: Literal["local", "model"], language: str) -> ModelAdapter:
    if mode == "local":
        return LocalRoleModel()
    answer = "这些依据仍需核验。" if language == "zh" else "This evidence still needs checking."
    return ScriptedModel([ModelReply(text=answer), assessment(kinds=("business_judgment",))])


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("original_mode", ["local", "model"])
def test_reply_generation_mode_survives_runtime_configuration_switch(
    tmp_path: Path, language: str, original_mode: Literal["local", "model"]
) -> None:
    dialogue = Dialogue(tmp_path, language, reply_model(original_mode, language))
    try:
        question = "请核对当前依据。" if language == "zh" else "Please check the evidence."
        first = dialogue.ask(question)
        assert first["status"] == "completed", first
        saved = dialogue.reply()["result"]["result"]
        assert saved["content"]["generation_mode"] == original_mode
        next_mode = "model" if original_mode == "local" else "local"
        model = reply_model(next_mode, language)
        registry, _ = build_registry(installed_locale_root("pm_pilot", language), model)
        database_url = str(dialogue.store.db.engine.url)
        dialogue.store.db.engine.dispose()
        dialogue.store = V2Store(database_url)
        dialogue.gateway = Gateway(dialogue.store, registry)
        dialogue.jobs = JobRepository(dialogue.store.db)
        dialogue.worker = Worker(
            dialogue.jobs,
            {
                "v2.role_turn": ClaimedHandler(
                    lambda payload, claim: dialogue.gateway.run_job(
                        "v2.role_turn", payload, claim=claim
                    ),
                    retry_on_error=False,
                )
            },
        )
        second = dialogue.ask(question)
        assert second["status"] == "completed", second
        assert dialogue.reply()["result"]["result"]["content"]["generation_mode"] == next_mode
        restored = dialogue.gateway.dispatch(dialogue.auth, "objects.read", {"ref": saved["ref"]})[
            "result"
        ]["result"]
        assert restored == saved
    finally:
        dialogue.close()
