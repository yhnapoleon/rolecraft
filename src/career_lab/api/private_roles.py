"""Trusted private-role integration. Default installation keeps generation closed.

The module-owned RoleService remains responsible for dialogue behavior. This port
only binds it to the common fixed snapshot, actual lease and private persistence.
"""

from pathlib import Path
import hashlib
import re
from sqlalchemy import Column, Integer, String, Table, insert, select
from sqlalchemy.exc import IntegrityError
from career_lab.storage.database import metadata, utc_timestamp
from career_lab.contracts.v2 import *
from career_lab.api.modules import Operation, StoreJobHandler
from career_lab.api.role_snapshot import FixedRoleSnapshotPort, activated_catalog
from career_lab.runtime.context_v2 import ContextPort
from career_lab.runtime.roles_v2 import RoleService, LocalRoleModel
from career_lab.storage.role_memory import RoleTurn, RoleReply, RoleDisplay
from career_lab.storage.v2_store import ObjectWrite, references


# Additive private journal. A claim commits before transport and is never refunded.
role_model_calls = Table(
    "v2_role_model_calls",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("origin_request_id", String, primary_key=True),
    Column("retry_generation", Integer, primary_key=True),
    Column("phase", String, primary_key=True),
    Column("model_revision", String, nullable=False),
    Column("claimed_at", String, nullable=False),
)


class RuleReplyVerifier:
    """Mechanical script/binding check only; consistent never means semantic quality.

    Mixed or indeterminate language is withheld. No provider call, score, stance
    change, or claim that the reply follows the role's position is made here.
    """

    retries = 0
    revision = "role-reply-mechanical-v1"

    def check(self, snapshot, auth, request, text, *, record_attempt, begin_call=None):
        from career_lab.storage.role_memory import ReplyVerification, stance_digest

        if begin_call is None:
            raise ProtocolError("role_attempt_guard_unavailable", status=409)
        begin_call("role_reply_review", self.revision)
        han = len(re.findall(r"[\u3400-\u9fff]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        # This is a conservative script check, not natural-language understanding.
        match = (
            (han > 0 and han >= latin)
            if snapshot.work_language == "zh"
            else (latin > 0 and han == 0)
            if snapshot.work_language == "en"
            else False
        )
        identity = (
            request.session_id == auth.session_id == snapshot.context.session_id
            and request.input.role_id == snapshot.context.role_id
            and request.executor == auth.executor
        )
        source = Path(__file__)
        return ReplyVerification(
            "consistent" if match and identity else "undetermined",
            True if match and identity else None,
            stance_digest(snapshot.stance_state),
            digest(text),
            snapshot.context.as_of,
            FileRef(
                path="src/career_lab/api/private_roles.py",
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            ),
        )


class PrivateRoleGenerationPort:
    def __init__(self, store, catalog, view, envelope, auth, *, max_context_chars=24000):
        self.store, self.catalog, self.view, self.envelope, self.auth = (
            store,
            catalog,
            view,
            envelope,
            auth,
        )
        self.max_context_chars = max_context_chars
        self.permit = None
        self.snapshot = None
        self.attempts = []
        self.prepared = None

    def require_available(self):
        if self.permit is None:
            if self.view.worker_claim is None:
                raise ProtocolError("worker_claim_required", status=409)
            self.permit, self.snapshot = self.store.begin_role_execution(
                self.view,
                self.envelope,
                self.auth,
                self.view.worker_claim,
                self.catalog,
                max_context_chars=self.max_context_chars,
            )

    def claim_model_call(self, envelope, auth, phase, model_revision):
        self.require_available()
        if envelope != self.envelope or auth != self.auth:
            raise ProtocolError("role_attempt_identity_invalid", status=403)
        if not phase or not model_revision:
            raise ProtocolError("role_attempt_identity_invalid", status=403)
        key = dict(
            session_id=auth.session_id,
            origin_request_id=envelope.origin_request_id,
            retry_generation=envelope.context.refresh_count,
            phase=phase,
        )
        condition = [role_model_calls.c[name] == value for name, value in key.items()]
        with self.store.db.transaction() as conn:
            # Recheck the actual lease and caller before each stage. A new lease
            # or provider revision never creates a new call identity.
            self.store._role_lease(conn, self.permit)
            self.store._validate_job_commit(
                conn,
                auth,
                envelope.command,
                envelope.context,
                self.view.worker_claim,
                envelope.capability,
            )
            if conn.execute(select(role_model_calls.c.phase).where(*condition)).first():
                return False
            try:
                with conn.begin_nested():
                    conn.execute(
                        insert(role_model_calls).values(
                            **key, model_revision=model_revision, claimed_at=utc_timestamp()
                        )
                    )
            except IntegrityError:
                if conn.execute(select(role_model_calls.c.phase).where(*condition)).first():
                    return False
                raise
        return True

    def _audit(self, *, phase, context, received, memories, used, attempts, reply=None, error=None):
        permit = self.permit
        messages, _ = self.snapshot.messages(self.auth, max_chars=self.max_context_chars)
        scope = RoleAuditScope(
            **{
                key: getattr(self.auth, key)
                for key in RoleAuditScope.model_fields
                if key != "schema_version"
            }
        )
        return RoleGenerationAudit(
            phase=phase,
            job_id=permit.claim.job_id,
            job_attempt=permit.claim.attempt,
            worker_id=permit.claim.worker_id,
            lease_token_hash=digest(permit.claim.lease_token),
            request=ObjectRef.model_validate(self.envelope.command.payload["subject"]),
            reply=reply,
            scope=scope,
            prompt_messages=tuple(ProviderMessage.model_validate(m) for m in messages),
            prompt_hash=permit.prompt_hash,
            history_revision=permit.history_revision,
            refresh_count=self.envelope.context.refresh_count,
            attempts=tuple(attempts),
            error_code=error,
            received_shares=tuple(
                RoleAuditReceivedShare(
                    share=r.share,
                    product=r.product,
                    role_id=r.role_id,
                    received_at=r.received_at,
                    fragment=r.fragment,
                )
                for r in received
            ),
            memories=tuple(
                RoleAuditMemory(
                    fragment=m.fragment,
                    role_id=m.role_id,
                    learner_refs=m.learner_refs,
                    provenance=m.provenance,
                )
                for m in memories
            ),
            used_sources=tuple(used),
        )

    def record_attempt(self, envelope, auth, attempt, error_code):
        self.require_available()
        if envelope != self.envelope or auth != self.auth or self.attempts:
            raise ProtocolError("role_attempt_identity_invalid", status=403)
        if (error_code is None) != (attempt.status == "success"):
            raise ProtocolError("role_attempt_status_invalid", status=403)
        selected, _ = self.snapshot.select_sources(auth, self.max_context_chars)
        audit = self._audit(
            phase="attempt",
            context=self.snapshot.context,
            received=self.snapshot.received_shares,
            memories=self.snapshot.memories,
            used=selected,
            attempts=(attempt,),
            error=error_code,
        )
        context = self.snapshot.context.model_copy(update={"generation_audit": audit})
        self.store.record_role_attempt(self.permit, context)
        self.attempts.append(attempt)

    def prepare(self, view, envelope, auth, generation):
        self.require_available()
        if (
            view is not self.view
            or envelope != self.envelope
            or auth != self.auth
            or tuple(self.attempts) != generation.attempts
        ):
            raise ProtocolError("role_private_identity_invalid", status=403)
        if (
            generation.prompt_hash != self.permit.prompt_hash
            or generation.history_revision != self.permit.history_revision
            or generation.role_id != self.permit.role_id
        ):
            raise ProtocolError("role_private_context_mismatch", status=409)
        audit = self._audit(
            phase="completed",
            context=generation.context,
            received=generation.received_shares,
            memories=generation.memories,
            used=generation.used_sources,
            attempts=generation.attempts,
            reply=generation.reply_ref,
        )
        context = RoleContext.model_validate(
            generation.context.model_dump(mode="json")
            | {"generation_audit": audit.model_dump(mode="json")}
        )
        ref = ObjectRef(
            session_id=auth.session_id,
            kind="role_context",
            object_id="generation-"
            + digest([envelope.job_id, envelope.context.refresh_count])[:24],
            version=1,
        )
        self.prepared = ObjectWrite(
            ref=ref,
            expected_head=0,
            content=context.model_dump(mode="json"),
            visible_to=("system", generation.role_id),
            dependencies=references(context.model_dump(mode="json")),
        )
        return (self.prepared,)

    def authorize(self, plan):
        if self.prepared is None or [w for w in plan.writes if w.ref.kind == "role_context"] != [
            self.prepared
        ]:
            raise ProtocolError("role_private_plan_changed", status=403)
        return self.store.authorize_role_plan(self.permit, plan)


def install_private_role_runtime(
    registry,
    catalog,
    model,
    *,
    enable_generation=False,
    max_context_chars=24000,
    reply_verifier=None,
):
    """Same registry for API/worker. Real business activation remains opt-in.

    Keep enable_generation false until the coordinator-fixed repaired W04 input
    and cumulative acceptance are installed. Tests use labelled controlled models.
    """
    for kind, model_type in (
        ("role_turn", RoleTurn),
        ("role_reply", RoleReply),
        ("role_display", RoleDisplay),
    ):
        registry.register_object_model(kind, model_type)
    enqueue = RoleService(ContextPort(catalog), model, max_context_chars=max_context_chars)
    registry.register(
        Operation(
            "turns.create",
            "act",
            TurnInput,
            enqueue.enqueue,
            ready=enable_generation,
            unavailable_code=None if enable_generation else "role_integration_not_accepted",
        )
    )

    def generate(store, view, envelope, auth):
        if not enable_generation:
            raise ProtocolError("role_integration_not_accepted", status=409)
        current_catalog = activated_catalog(catalog, view.private_scenario_state)
        port = PrivateRoleGenerationPort(
            store, current_catalog, view, envelope, auth, max_context_chars=max_context_chars
        )
        service = RoleService(
            ContextPort(current_catalog, FixedRoleSnapshotPort(store, current_catalog)),
            model,
            max_context_chars=max_context_chars,
            private_port=port,
            reply_verifier=reply_verifier
            if reply_verifier is not None
            else (None if type(model) is LocalRoleModel else RuleReplyVerifier()),
        )
        return port.authorize(service.generate(view, envelope, auth))

    registry.register_job("v2.role_turn", StoreJobHandler(generate, retry_on_error=False))
    return registry
