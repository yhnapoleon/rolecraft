"""Authorized native workbench reads and explicit reply-display receipts."""
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts.v2 import ObjectRead, ResourcePage, PublicEvent, ProtocolError, canonical
from career_lab.storage.v2_store import TransactionResult
from career_lab.storage.v2_tables import v2_transactions,v2_request_meta
from sqlalchemy import select
from career_lab.storage.v2_lifecycle import point
from career_lab.runtime.roles_v2 import record_reply_display


def public_event_history(store,registry,auth,at,*,since_seq=0,view=None):
    """Project persisted events using their trusted originating operation.

    W06 may consume this read adapter; catalog retrieval is never fabricated as
    a material_read event. No private payload is returned without its projector.
    """
    def read(view):
        visible={canonical(r.ref) for r in view.objects}
        with store.db.engine.connect() as conn:
            rows=conn.execute(select(v2_transactions.c.result,v2_request_meta.c.operation).join(v2_request_meta,
                (v2_transactions.c.session_id==v2_request_meta.c.session_id)&(v2_transactions.c.request_id==v2_request_meta.c.request_id))
                .where(v2_transactions.c.session_id==auth.session_id)).all()
        events=[]
        for raw,operation in rows:
            result=TransactionResult.model_validate_json(raw)
            projector=registry.projector_for_action(operation)
            for event in result.events:
                if not since_seq<event.seq<=at.business_seq or auth.actor_id not in event.visible_to:continue
                if auth.allowed_objects is not None and any(canonical(ref) not in visible for ref in event.refs):continue
                projected=projector(event,auth) if projector else PublicEvent.model_validate(event.model_dump(mode='json',exclude={'visible_to','data'})|{'data':{}})
                if projected is None:continue
                projected=PublicEvent.model_validate(projected.model_dump(mode='json'))
                if (projected.id,projected.seq,projected.transaction_id)!=(event.id,event.seq,event.transaction_id):
                    raise ProtocolError('event_projection_identity_mismatch')
                events.append(projected)
        return tuple(sorted(events,key=lambda e:e.seq))
    if view is not None:
        if view.state.session_id!=auth.session_id or point(view.state)!=at or view.reference_allowed is None:raise ProtocolError('event_view_invalid',status=409)
        return read(view)
    return store.query_at(auth,at,read,operation='timeline')


def install_native_reads(registry, module, *, role_mode="local_reference",store_provider=None):
    def timeline(view, payload, auth):
        kinds = {"config", "test", "business_request", "business_decision", "role_turn", "role_reply", "role_display", "submission", "cycle"}
        rows = sorted((r for r in view.objects if r.ref.kind in kinds), key=lambda r: (r.created_storage_revision, r.ref.object_id))
        data = {"role_mode":role_mode,"objects": [{"ref":r.ref.model_dump(mode="json"), "content":r.content} for r in rows],
                "as_of": point(view.state).model_dump(mode="json")}
        # The scoped observation adapter owns partial Agent state. An unrestricted
        # learner can inspect actual business resources and source/index versions.
        if auth.actor_id == "learner" and auth.allowed_objects is None:
            snapshot = module.snapshot(view)
            data["workspace"] = {"resources": dict(view.state.resources),
                "source_versions": dict(snapshot.source_versions), "indexed_versions": dict(snapshot.indexed_versions),
                "config": snapshot.config.model_dump(mode="json"),
                "material_titles": {f"{m.id}:{m.version}":m.title for m in module.package.materials
                    if snapshot.material_activation.get(f"{m.id}:{m.version}",view.state.business_seq+1)<=view.state.business_seq
                    and module.package.project(m.id,m.version,auth.actor_id,view.state.business_seq,auth.session_id)}}
        if store_provider is not None:
            data['events']=[e.model_dump(mode='json') for e in public_event_history(store_provider(),registry,auth,point(view.state),since_seq=payload.since_seq or 0,view=view)]
        return V2Response(result=data)
    registry.register(Operation("timeline", "read", ResourcePage, timeline, mutates=False, response_model=V2Response))
    registry.register(Operation("turns.display", "act", ObjectRead, record_reply_display))
    return registry
