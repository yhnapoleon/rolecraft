"""Projection from explicit public source ports, never from ScenarioSpec."""

from dataclasses import dataclass
from typing import Callable
from career_lab.contracts import v2 as C
from .service import require_learner


@dataclass(frozen=True)
class PublicSources:
    as_of: C.VersionPoint
    catalog: tuple[C.MaterialMetadata, ...]
    visible_sources: tuple[C.ObservedFragment, ...]
    actual_disclosures: tuple[C.PublicDisclosureRecord, ...]
    read_versions: tuple[C.ObjectRef, ...]
    events: tuple[C.PublicEvent, ...]
    next_seq: int
    budget: C.Budget | None = None


def build_observation(view, query, auth, tools, source_provider):
    require_learner(auth)
    if source_provider is None:
        raise C.ProtocolError("observation_source_unavailable", status=503)
    source = source_provider(view, query, auth)
    if not isinstance(source, PublicSources):
        raise C.ProtocolError("observation_source_contract_invalid", status=503)
    at = C.VersionPoint(
        **view.state.model_dump(include={"business_seq", "workspace_revision", "storage_revision"})
    )
    if source.as_of != at or not (query.since_seq or 0) <= source.next_seq <= at.business_seq:
        raise C.ProtocolError("observation_window_invalid", status=503)

    def authorized(ref):
        if (
            ref.session_id != auth.session_id
            or ref.kind == "role_context"
            or view.reference_allowed is None
        ):
            raise C.ProtocolError("observation_scope_invalid", status=503)
        try:
            allowed = view.reference_allowed(ref)
        except C.ProtocolError:
            allowed = False
        if not allowed:
            raise C.ProtocolError("observation_scope_invalid", status=503)

    for ref in (*source.read_versions, *[r.ref for r in source.visible_sources]):
        authorized(ref)
    for fragment in source.visible_sources:
        # Internal fact keys have no meaning in the public learner projection.
        if fragment.fact_ids:
            raise C.ProtocolError("observation_private_metadata", status=503)
        if fragment.disclosure_ref is not None:
            authorized(fragment.disclosure_ref)
    for disclosure in source.actual_disclosures:
        authorized(disclosure.source)
        authorized(disclosure.reply_ref)
        reply = next((r for r in view.objects if r.ref == disclosure.reply_ref), None)
        if reply is None or disclosure.quote not in reply.content.get("text", ""):
            raise C.ProtocolError("observation_disclosure_unverified", status=503)
    for material in source.catalog:
        authorized(
            C.ObjectRef(
                session_id=auth.session_id,
                kind="material",
                object_id=material.id,
                version=material.version,
            )
        )
    visible_events = []
    previous = query.since_seq or 0
    if len(source.events) > query.limit:
        raise C.ProtocolError("observation_event_window_invalid", status=503)
    for event in source.events:
        if event.session_id != auth.session_id or not previous < event.seq <= source.next_seq:
            raise C.ProtocolError("observation_event_window_invalid", status=503)
        for ref in event.refs:
            authorized(ref)
        previous = event.seq
        visible_events.append(
            C.ObjectRef(session_id=auth.session_id, kind="event", object_id=event.id, version=1)
        )
    heads = {}
    for record in view.objects:
        if record.ref.kind not in {"product", "test"}:
            continue
        key = (record.ref.kind, record.ref.object_id)
        if key not in heads or record.ref.version > heads[key].ref.version:
            heads[key] = record
    return C.Observation(
        session_id=auth.session_id,
        actor=auth.executor,
        as_of=at,
        catalog=source.catalog,
        visible_sources=source.visible_sources,
        actual_disclosures=source.actual_disclosures,
        read_versions=source.read_versions,
        events=tuple(visible_events),
        next_seq=source.next_seq,
        budget=source.budget,
        products=tuple(r.ref for r in heads.values() if r.ref.kind == "product"),
        tests=tuple(r.ref for r in heads.values() if r.ref.kind == "test"),
        tools=tools,
    )
