"""Versioned v4 extensions mounted beside delegation; included in the public contract export.

- ``GET  /sessions/{sid}/delegations``: the person's own agent delegations. No token is ever returned.
  Agent labels are not part of the frozen grant, so the browser keeps the person's own label locally.
- ``GET /sessions/{sid}/practice?submission_id=``: optional reviewed practice for that feedback
  (evaluation rules).
- ``POST /sessions/{sid}/practice/choices``: an explicit decline / continue / choose (a suggestion) /
  choose_other (any reviewed situation the person picks). Both choose paths create the new practice and
  record the source feedback -> new practice link. One choice is one request_id: the new session id and its
  credential are derived from the person's own credential and that request_id, so a lost response or a
  failure between the two writes is completed by retrying the same request, never by a second practice.

Practice identity: the service runs packages prepared from authored scenario sources.
Independent review
covers authored content only (``content-approval-2.9.0.json``). An option is offered only when the running
package's authored manifest hash is one of the approved bundles; the approval is matched by content
identity and never re-signed onto runtime bindings. Without a prepared catalog nothing is offered.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.engine import Connection

from career_lab.contracts import v2 as C
from career_lab.rubrics.v4.practice import ReviewedPractice, selection_plan, suggestions
from career_lab.storage.v2_tables import v2_credentials

if TYPE_CHECKING:
    from career_lab.api.modules import Gateway
    from career_lab.storage.v2_store import V2Store

_META = MetaData()
# A separate integration table; the frozen v2 tables are not altered.
practice_links = Table(
    "v4_practice_links",
    _META,
    Column("id", String, primary_key=True),
    Column("source_session_id", String, index=True),
    Column("feedback_id", String),
    Column("feedback_hash", String),
    Column("choice", String),
    Column("option_id", String, nullable=True),
    Column("target_session_id", String, nullable=True),
    Column("suggestion_hash", String),
    Column("created_at", String),
)

practice_intents = Table(
    "v4_practice_intents",
    _META,
    Column("id", String, primary_key=True),
    Column("source_session_id", String, nullable=False, index=True),
    Column("feedback_id", String, nullable=False),
    Column("choice", String, nullable=False),
    Column("option_id", String, nullable=True),
    Column("fingerprint", String, nullable=False),
    Column("completed", Integer, nullable=False),
)

_VARIANTS = Path(__file__).resolve().parents[3] / "scenarios/pm_pilot/v2/variants"


ShownPractice = C.ShownPractice
PracticeChoiceInput = C.PracticeChoiceInput


def _now():
    return datetime.now(timezone.utc).isoformat()


def _context(store, session_id, credentials):
    if credentials is None:
        raise C.ProtocolError("token_required", "session token required", status=401)
    if not store.contains(session_id):
        raise C.ProtocolError("v2_session_required", status=409)
    return store.authenticate(session_id, credentials.credentials)


def _human(auth):
    if auth.executor.kind != "human" or auth.actor_id != "learner":
        raise C.ProtocolError("human_required", "only the person can do this", status=403)


def list_delegations(store, auth):
    """Current agent delegations of this session, judged by server time. No secrets."""
    _human(auth)
    store.authorize(auth, "delegate")
    now = datetime.now(timezone.utc)
    items = []
    with store.db.engine.connect() as c:
        rows = (
            c.execute(select(v2_credentials).where(v2_credentials.c.session_id == auth.session_id))
            .mappings()
            .all()
        )
    for row in rows:
        ctx = C.AuthContext.model_validate_json(row["context"])
        if ctx.executor.kind != "external_agent":
            continue
        status = (
            "revoked"
            if row["revoked"]
            else "expired"
            if ctx.expires_at and ctx.expires_at <= now
            else "active"
        )
        items.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "executor": ctx.executor.model_dump(mode="json"),
                "capabilities": list(ctx.capabilities),
                "allowed_actions": ctx.allowed_actions,
                "allowed_objects": ctx.allowed_objects,
                "create_under_tasks": list(ctx.create_under_tasks),
                "expires_at": ctx.expires_at.isoformat() if ctx.expires_at else None,
                "revoked": bool(row["revoked"]),
                "effective_status": status,
            }
        )
    items.sort(key=lambda x: x["expires_at"] or "", reverse=True)
    return {
        "schema_version": 2,
        "items": items,
        "next_cursor": None,
        "checked_at": now.isoformat(),
        "complete": True,
    }


class PracticeCatalog:
    """Reviewed practice options bound to the packages this service actually runs."""

    def __init__(self, registry):
        self.registry = registry

    def _running(self):
        path = os.getenv("CAREER_LAB_SCENARIO_CATALOG")
        if not path:
            return {}
        entries = json.loads(Path(path).read_text())["scenarios"]
        authored = {
            e["scenario_hash"]: (
                e.get("reviewed_authored_manifest") or e["authored_manifest"],
                e["work_language"],
            )
            for e in entries
        }
        running = {}
        for (name, language), registration in getattr(
            self.registry, "language_scenarios", {}
        ).items():
            content = authored.get(registration.bindings.scenario.sha256)
            if content and content[1] == language:
                running[(content[0], language)] = (name, registration)
        return running

    def options(self):
        """(ReviewedPractice tuple, {option_id: (scenario_name, language)})."""
        approval_path = _VARIANTS / "reviews/content-approval-2.9.0.json"
        catalog_path = _VARIANTS / "reviewed-options-2.9.0.json"
        if not approval_path.exists() or not catalog_path.exists():
            return (), {}
        approval_raw = approval_path.read_bytes()
        approval = json.loads(approval_raw)
        if (
            approval.get("verdict") != "accepted"
            or approval.get("scope") != "authored_content_only"
        ):
            return (), {}
        approved = {(b["scenario_hash"], b["work_language"]) for b in approval["bundles"]}
        review = C.FileRef(
            path="reviews/content-approval-2.9.0.json",
            sha256=hashlib.sha256(approval_raw).hexdigest(),
        )
        running = self._running()
        result, targets = [], {}
        for row in json.loads(catalog_path.read_text())["entries"]:
            content_hash = row["bindings"]["scenario"]["sha256"]
            key = (content_hash, row["work_language"])
            if key not in approved or key not in running:
                continue
            name, registration = running[key]
            result.append(
                ReviewedPractice(
                    id=row["id"],
                    title_zh=row["title_zh"],
                    title_en=row["title_en"],
                    work_language=row["work_language"],
                    bindings=registration.bindings,
                    criteria=tuple(row["criteria"]),
                    review_status="approved",
                    review=review,
                    component_id=row["component_id"],
                )
            )
            targets[row["id"]] = (name, row["work_language"])
        return tuple(result), targets

    def listing(self, options, suggested_ids):
        """Every reviewed situation the person may pick in this language, suggested or not."""
        return [
            {
                "id": o.id,
                "title": o.title_en if o.work_language == "en" else o.title_zh,
                "work_language": o.work_language,
                "component_id": o.component_id,
                "criteria": list(o.criteria),
                "review_status": o.review_status,
                "review": o.review.model_dump(mode="json"),
                "scenario_hash": o.bindings.scenario.sha256,
                "suggested": o.id in suggested_ids,
            }
            for o in options
        ]

    def language_of(self, bindings):
        for (_, language), registration in getattr(self.registry, "language_scenarios", {}).items():
            if registration.bindings == bindings:
                return language
        for registration in self.registry.scenarios.values():
            if registration.bindings == bindings:
                return registration.work_language
        return None


def _feedback_for(store, auth, submission_id):
    view = store.view(auth)
    for record in view.objects:
        if record.ref.kind != "feedback":
            continue
        feedback = C.FeedbackV2.model_validate(record.content)
        if feedback.subject.object_id == submission_id:
            return record.ref, feedback, view
    raise C.ProtocolError(
        "feedback_not_ready", "feedback for this submission is not ready", status=404
    )


def _links(store, sid, feedback_id):
    with store.db.engine.connect() as c:
        rows = (
            c.execute(
                select(practice_links).where(
                    practice_links.c.source_session_id == sid,
                    practice_links.c.feedback_id == feedback_id,
                )
            )
            .mappings()
            .all()
        )
    return [
        {k: row[k] for k in ("choice", "option_id", "target_session_id", "created_at")}
        for row in rows
    ]


def _require_original_legacy_request(
    connection: Connection,
    source_id: str,
    feedback_id: str,
    choice: str,
    option_id: str | None,
    link_id: str,
) -> None:
    from career_lab.security.credentials import derivations

    prior = connection.execute(
        select(practice_links).where(
            practice_links.c.source_session_id == source_id,
            practice_links.c.feedback_id == feedback_id,
            practice_links.c.choice == choice,
            practice_links.c.option_id == option_id,
            practice_links.c.id != link_id,
            practice_links.c.target_session_id.is_not(None),
        )
    ).mappings()
    for link in prior:
        signed = (
            connection.execute(
                select(
                    v2_credentials.c.token_hash,
                    derivations.c.token_hash.label("derived_hash"),
                )
                .join(derivations, derivations.c.credential_id == v2_credentials.c.id)
                .where(
                    v2_credentials.c.session_id == link["target_session_id"],
                    derivations.c.purpose == "practice-session",
                )
            )
            .mappings()
            .first()
        )
        if signed is None or signed["token_hash"] != signed["derived_hash"]:
            raise C.ProtocolError("practice_request_reused", status=409)


def _check_choice_link(
    existing: Mapping[str, object] | None, selection: dict[str, C.JsonValue]
) -> None:
    if existing and any(existing[key] != selection[key] for key in selection):
        raise C.ProtocolError("practice_request_reused", status=409)


def _reserve_practice_intent(
    connection: Connection,
    link_id: str,
    source_id: str,
    feedback_id: str,
    selection: dict[str, C.JsonValue],
    fingerprint: str,
) -> None:
    previous = (
        connection.execute(select(practice_intents).where(practice_intents.c.id == link_id))
        .mappings()
        .first()
    )
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise C.ProtocolError("practice_request_reused", status=409)
        return
    pending = connection.execute(
        select(practice_intents.c.id).where(
            practice_intents.c.source_session_id == source_id,
            practice_intents.c.feedback_id == feedback_id,
            practice_intents.c.choice == selection["choice"],
            practice_intents.c.option_id == selection["option_id"],
            practice_intents.c.completed == 0,
        )
    ).first()
    if pending:
        raise C.ProtocolError("practice_request_reused", status=409)
    connection.execute(
        insert(practice_intents).values(
            id=link_id,
            source_session_id=source_id,
            feedback_id=feedback_id,
            choice=selection["choice"],
            option_id=selection["option_id"],
            fingerprint=fingerprint,
            completed=0,
        )
    )


def mount_v4_extensions(app: FastAPI) -> None:
    store = app.state.v2_store
    gateway = app.state.gateway
    catalog = PracticeCatalog(gateway.registry)
    _META.create_all(store.db.engine)
    bearer = HTTPBearer(auto_error=False)

    @app.get("/sessions/{session_id}/delegations", response_model=C.DelegationListResponse)
    def delegations(
        session_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
    ):
        # Same envelope as the gateway's list reads.
        return {
            "schema_version": 2,
            "result": {
                "schema_version": 2,
                "result": list_delegations(store, _context(store, session_id, credentials)),
            },
        }

    @app.get("/sessions/{session_id}/practice", response_model=C.PracticeReadResponse)
    def practice(
        session_id: str,
        submission_id: str,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        auth = _context(store, session_id, credentials)
        _human(auth)
        ref, feedback, view = _feedback_for(store, auth, submission_id)
        language = catalog.language_of(view.bindings)
        options, targets = catalog.options()
        if language is None:
            raise C.ProtocolError("practice_language_unavailable", status=409)
        shown = suggestions(auth, ref, feedback, options, work_language=language)
        own = tuple(o for o in options if o.work_language == language)
        return {
            "schema_version": 2,
            "result": {
                **shown,
                "available": bool(targets),
                "catalog": catalog.listing(own, {o["id"] for o in shown["options"]}),
                "links": _links(store, session_id, ref.object_id),
            },
        }

    @app.post("/sessions/{session_id}/practice/choices", response_model=C.PracticeChoiceResponse)
    async def choose(
        session_id: str,
        body: PracticeChoiceInput,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> C.PracticeChoiceResponse:
        auth = _context(store, session_id, credentials)
        _human(auth)
        shown, choice, option_id = body.shown.model_dump(mode="json"), body.choice, body.option_id
        request_id = body.request_id
        view = store.view(auth)
        language = catalog.language_of(view.bindings)
        if language is None or shown["work_language"] != language:
            raise C.ProtocolError("practice_language_mismatch", status=409)
        ref = body.shown.source_feedback
        if ref.kind != "feedback" or ref.session_id != session_id or ref.version != 1:
            raise C.ProtocolError("practice_feedback_scope_mismatch", status=404)
        record = next((r for r in view.objects if r.ref == ref), None)
        if record is None:
            raise C.ProtocolError("practice_feedback_scope_mismatch", status=404)
        feedback = C.FeedbackV2.model_validate(record.content)
        options, targets = catalog.options()
        if choice == "choose_other":
            # Validate self-selected practice against the source feedback and evaluation rules,
            # then check the
            # option against the reviewed catalog of the same language; record it as the person's own pick.
            base = selection_plan(auth, ref, feedback, options, shown, choice="decline")
            target = next(
                (
                    o
                    for o in options
                    if o.id == option_id and o.work_language == shown.get("work_language")
                ),
                None,
            )
            if target is None or option_id not in targets:
                raise C.ProtocolError("reviewed_practice_option_required", status=422)
            identity = {
                "id": target.id,
                "bindings": target.bindings.model_dump(mode="json"),
                "work_language": target.work_language,
                "review": target.review.model_dump(mode="json"),
                "component_id": target.component_id,
            }
            plan = {
                **base,
                "choice": "choose_other",
                "help_source": "self_selected",
                "target": {
                    **identity,
                    "candidate_hash": C.digest(identity),
                    "title": target.title_en if target.work_language == "en" else target.title_zh,
                },
            }
        else:
            plan = selection_plan(
                auth, ref, feedback, options, shown, choice=choice, option_id=option_id
            )
        link_id = C.digest([session_id, ref.object_id, request_id])
        selection = {
            "choice": plan["choice"],
            "option_id": option_id,
            "feedback_hash": plan["source_feedback_hash"],
            "suggestion_hash": plan["suggestion_hash"],
        }
        fingerprint = C.digest(
            {
                "source_session": session_id,
                "feedback": ref.model_dump(mode="json"),
                "request_id": request_id,
                "selection": selection,
            }
        )
        session = None
        with store.db.transaction() as c:
            store._auth(c, auth, "read")
            _require_original_legacy_request(
                c, session_id, ref.object_id, plan["choice"], option_id, link_id
            )
            _reserve_practice_intent(c, link_id, session_id, ref.object_id, selection, fingerprint)
            existing = (
                c.execute(select(practice_links).where(practice_links.c.id == link_id))
                .mappings()
                .first()
            )
            _check_choice_link(existing, selection)
            if plan["choice"] in {"choose", "choose_other"}:
                name, language = targets[option_id]
                session = _practice_session(
                    store,
                    gateway,
                    auth,
                    name,
                    language,
                    session_id,
                    ref.object_id,
                    request_id,
                    selection=selection,
                    _connection=c,
                )
                if (
                    session["binding"]["scenarioHash"]
                    != plan["target"]["bindings"]["scenario"]["sha256"]
                ):
                    raise C.ProtocolError("practice_target_binding_changed", status=409)
        with store.db.transaction() as c:
            store._auth(c, auth, "read")
            existing = (
                c.execute(select(practice_links).where(practice_links.c.id == link_id))
                .mappings()
                .first()
            )
            _check_choice_link(existing, selection)
            if not existing:
                c.execute(
                    insert(practice_links).values(
                        id=link_id,
                        source_session_id=session_id,
                        feedback_id=ref.object_id,
                        feedback_hash=plan["source_feedback_hash"],
                        choice=plan["choice"],
                        option_id=option_id,
                        target_session_id=session["session_id"] if session else None,
                        suggestion_hash=plan["suggestion_hash"],
                        created_at=_now(),
                    )
                )
            c.execute(
                update(practice_intents).where(practice_intents.c.id == link_id).values(completed=1)
            )
        return C.PracticeChoiceResponse.model_validate(
            {
                "schema_version": 2,
                "result": {
                    "plan": {
                        **plan,
                        "creates_session": session is not None,
                        "new_session_id": session["session_id"] if session else None,
                    },
                    "duplicate": bool(existing),
                    "session": session,
                    "scenario": targets[option_id][0] if session else None,
                },
            }
        )


def _practice_session(
    store: V2Store,
    gateway: Gateway,
    owner: C.AuthContext,
    name: str,
    language: str,
    source_session_id: str,
    feedback_id: str,
    request_id: str,
    *,
    selection: dict[str, C.JsonValue] | None = None,
    _connection: Connection | None = None,
) -> dict[str, C.JsonValue]:
    """Persist target identity and signing provenance together; resume the same target."""
    from uuid import uuid4

    from career_lab.api.modules import public_state
    from career_lab.security.credentials import signed_credential
    from career_lab.storage.v2_store import session_owner
    from career_lab.storage.v2_tables import v2_sessions

    registration = getattr(gateway.registry, "language_scenarios", {}).get((name, language))
    if registration is None or registration.work_language != language:
        raise C.ProtocolError("scenario_module_unavailable", status=503)
    if owner.session_id != source_session_id or owner.executor.kind != "human":
        raise C.ProtocolError("human_required", status=403)
    sid = C.digest([source_session_id, feedback_id, request_id, "practice-session"])[:32]
    request = {
        "source_session": source_session_id,
        "feedback": feedback_id,
        "request_id": request_id,
        "scenario": name,
        "language": language,
        "selection": selection,
    }
    with (
        nullcontext(_connection) if _connection is not None else store.db.transaction()
    ) as connection:
        store._auth(connection, owner, "read")
        previous = (
            connection.execute(select(v2_sessions).where(v2_sessions.c.id == sid).with_for_update())
            .mappings()
            .first()
        )
        if previous:
            if C.SessionBindings.model_validate_json(previous["bindings"]) != registration.bindings:
                raise C.ProtocolError("practice_target_binding_changed", status=409)
            contexts = [
                C.AuthContext.model_validate_json(raw)
                for raw in connection.execute(
                    select(v2_credentials.c.context).where(v2_credentials.c.session_id == sid)
                ).scalars()
            ]
            humans = [context for context in contexts if context.executor.kind == "human"]
            if len(humans) != 1:
                raise C.ProtocolError("credential_derivation_unavailable", status=503)
            target = humans[0]
            store._auth(connection, target, "read")
            state = C.WorldStateV2.model_validate_json(previous["state"])
        else:
            target = session_owner(sid, uuid4().hex)
        token = signed_credential(
            connection,
            store.credential_key_provider,
            "practice-session",
            owner,
            target,
            request,
        )
        if not previous:
            state, _ = store.create_session(
                registration.bindings,
                registration.baseline_config,
                registration.resources,
                scenario_state=registration.scenario_state,
                session_id=sid,
                token=token,
                _connection=connection,
                _credential_id=target.credential_id,
            )
        store._auth(connection, target, "read")
    # Existing callers consume a JSON mapping; the domain model owns its shape.
    return C.PracticeSession.model_validate(
        {
            "schema_version": 2,
            "session_id": sid,
            "token": token,
            "state": public_state(state),
            "binding": {
                "protocol": 2,
                "sessionId": sid,
                "workLanguage": language,
                "scenarioHash": registration.bindings.scenario.sha256,
            },
        }
    ).model_dump(mode="json")
