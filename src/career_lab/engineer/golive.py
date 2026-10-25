"""The scenario's pilot go-live, run once by the system when a seeded ticket needs it.

A seeded ticket targets an answer that misses the newer policy. That world only exists after
the first ``configuration.apply``: the pilot goes live, the newer policy notice is published
and the daily index still holds the older version. When the engineer card is opened before
the product manager applied anything, the server applies the session's current settings
unchanged, through the ordinary ``configuration.apply`` handler, as a system executor:

- the executor is ``engineer-ticket-golive`` (kind ``system``), so the configuration record
  and both events name the system, never the learner or an Agent;
- both events carry ``origin: engineer_ticket_setup`` and a localized note saying it is not
  the learner's action;
- it is not PM work: the settings are identical (so it is no configuration adjustment), its
  ``config_applied`` event precedes the policy-change event it triggers, and it creates no
  test, work product or submission; the PM evidence ledger counts only tests, questions,
  replies and material reads.

The credential exists only for this one transaction and is revoked right after it.
"""

import secrets
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import update

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule, ref_for
from career_lab.storage.v2_store import TransactionView, V2Store
from career_lab.storage.v2_tables import v2_credentials

from .candidate import EDITABLE_FIELDS

GOLIVE_EXECUTOR = C.Executor(id="engineer-ticket-golive", kind="system")
GOLIVE_OPERATION = "configuration.apply"
GOLIVE_REQUEST = "engineer-ticket-golive"
GOLIVE_ORIGIN = "engineer_ticket_setup"
# The milestone the first configuration.apply records (scenario engine).
LIVE_MILESTONE = "initial_plan_applied"
GOLIVE_NOTE = {
    "zh": "试点配置已上线（系统为工程委托准备起始状态，不是学员的操作）",
    "en": "Pilot configuration went live (set up by the system for the engineering ticket; "
    "not the learner's action)",
}


def is_live(view: TransactionView) -> bool:
    return LIVE_MILESTONE in view.state.applied_milestones


def labelled(handler: Any, language: str) -> Any:
    """The ordinary apply handler, with both resulting events labelled as system setup."""

    def run(view: TransactionView, command: C.Command, auth: C.AuthContext):
        mutation = handler(view, command, auth)
        note = {"origin": GOLIVE_ORIGIN, "note": GOLIVE_NOTE[language]}
        events = tuple(
            event.model_copy(update={"data": {**event.data, **note}}) for event in mutation.events
        )
        return replace(mutation, events=events)

    return run


def system_context(store: V2Store, owner: C.AuthContext) -> C.AuthContext:
    """A one-transaction system credential for configuration.apply only.

    The apply handler reads the current configuration through the operation view, which
    projects records only for a reader, so the credential carries ``read`` beside ``act``.
    """
    context = C.AuthContext(
        session_id=owner.session_id,
        actor_id="learner",
        executor=GOLIVE_EXECUTOR,
        capabilities=("read", "act"),
        # The route's name and the scenario action it runs as (v4_config.install_settings).
        allowed_actions=(GOLIVE_OPERATION, "apply_config"),
        credential_id=uuid4().hex,
    )
    with store.db.transaction() as connection:
        store._credential(connection, context, secrets.token_urlsafe(32))
    return context


def revoke(store: V2Store, context: C.AuthContext) -> None:
    with store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials)
            .where(
                v2_credentials.c.id == context.credential_id,
                v2_credentials.c.session_id == context.session_id,
            )
            .values(revoked=1)
        )


def go_live(
    store: V2Store,
    module: ScenarioModule,
    apply_handler: Any,
    owner: C.AuthContext,
    operation: str,
) -> dict[str, Any] | None:
    """Put the pilot live once; None when the world already went live (nothing is run)."""

    def current(view: TransactionView):
        return is_live(view), view.state, module.snapshot(view).config

    live, state, config = store.query(owner, current, operation=operation)
    if live:
        return None
    settings = config.model_dump(mode="json")
    command = C.Command(
        schema_version=2,
        request_id=GOLIVE_REQUEST,
        operation=GOLIVE_OPERATION,
        payload={
            "base": ref_for("config", config).model_dump(mode="json"),
            "settings": {name: settings[name] for name in EDITABLE_FIELDS},
        },
        expected_version=state.business_seq,
        expected_workspace_revision=state.workspace_revision,
    )
    context = system_context(store, owner)
    try:
        store.execute(
            context, command, labelled(apply_handler, module.work_language), capability="act"
        )
    finally:
        revoke(store, context)
    return {
        "executor": {"id": GOLIVE_EXECUTOR.id, "kind": GOLIVE_EXECUTOR.kind},
        "note": GOLIVE_NOTE[module.work_language],
        "config_version": config.config_version + 1,
    }
