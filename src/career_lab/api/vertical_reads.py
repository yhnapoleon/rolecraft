"""Authorized native workbench reads and explicit reply-display receipts."""
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts.v2 import ObjectRead, ResourcePage, PublicEvent, ProtocolError, canonical
from career_lab.storage.v2_store import TransactionResult
from career_lab.storage.v2_tables import v2_transactions,v2_request_meta
from sqlalchemy import select
from career_lab.storage.v2_lifecycle import point
from career_lab.runtime.roles_v2 import record_reply_display


def history_reader(registry):
    """Read persisted events and acquisition receipts on the current transaction."""
    from career_lab.delegations.sources import PublicHistoryWindow, MaterialReadReceipt
    from career_lab.contracts.v2 import DisclosedFragment, StoredEvent
    from career_lab.storage.v2_tables import v2_events
    def read(conn,view,page,auth):
        at=point(view.state)
        if page.cursor or page.as_of_seq not in (None,at.business_seq):raise ProtocolError('observation_window_unsupported',status=422)
        since=page.since_seq or 0
        if since>at.business_seq:raise ProtocolError('history_cursor_invalid',status=422)
        through=min(at.business_seq,since+page.limit)
        rows=conn.execute(select(v2_transactions.c.result,v2_request_meta.c.operation).join(v2_request_meta,
            (v2_transactions.c.session_id==v2_request_meta.c.session_id)&(v2_transactions.c.request_id==v2_request_meta.c.request_id))
            .where(v2_transactions.c.session_id==auth.session_id)).all()
        expected={StoredEvent.model_validate_json(raw).id for raw in conn.execute(select(v2_events.c.record).where(
            v2_events.c.session_id==auth.session_id,v2_events.c.seq<=at.business_seq)).scalars()}
        scanned=set();events=[];receipts=[]
        def permitted(ref):
            try:return view.reference_allowed is not None and view.reference_allowed(ref)
            except ProtocolError:return False
        for raw,operation in rows:
            result=TransactionResult.model_validate_json(raw)
            if result.state.storage_revision>at.storage_revision:continue
            projector=registry.projector_for_action(operation)
            for event in result.events:
                if event.seq>at.business_seq:continue
                scanned.add(event.id)
                if auth.actor_id not in event.visible_to:continue
                if any(not permitted(ref) for ref in event.refs):continue
                projected=projector(event,auth) if projector else PublicEvent.model_validate(event.model_dump(mode='json',exclude={'visible_to','data'})|{'data':{}})
                if projected is None:continue
                projected=PublicEvent.model_validate(projected.model_dump(mode='json'))
                if (projected.id,projected.seq,projected.transaction_id)!=(event.id,event.seq,event.transaction_id):raise ProtocolError('event_projection_identity_mismatch')
                if since<event.seq<=through:events.append(projected)
                if event.type=='material_read' and operation=='read_material':
                    fragments=tuple(DisclosedFragment.model_validate(f) for f in result.result.get('fragments',()))
                    fragments=tuple(f.model_copy(update={'fact_ids':()}) for f in fragments if permitted(f.ref))
                    if fragments:receipts.append(MaterialReadReceipt(projected,fragments))
        return PublicHistoryWindow(at,tuple(sorted(events,key=lambda e:e.seq)),tuple(sorted(receipts,key=lambda r:r.event.seq)),through,scanned==expected)
    return read


def public_event_history(store,registry,auth,at,*,since_seq=0,view=None):
    from career_lab.contracts.v2 import ResourcePage
    def read(current):
        if current.public_history is None:raise ProtocolError('observation_history_unavailable',status=503)
        events=[];cursor=since_seq
        while cursor<at.business_seq:
            result=current.public_history(ResourcePage(since_seq=cursor,limit=100),auth)
            if not result.acquisitions_complete or result.next_seq<=cursor:raise ProtocolError('observation_history_unavailable',status=503)
            events.extend(result.events);cursor=result.next_seq
        return tuple(events)
    if view is not None:
        if view.state.session_id!=auth.session_id or point(view.state)!=at:raise ProtocolError('event_view_invalid',status=409)
        return read(view)
    return store.query_at(auth,at,read,operation='timeline')


def public_material_resolver(module):
    """Permit a whole-file citation only when every original fragment is public.

    W05 emits whole-file spans for document-level rule proofs. Preserve the exact
    span and text; never trim proof text or admit a partially disclosed file.
    """
    from career_lab.contracts.v2 import EvidenceRefV2, read_file
    def resolve(auth,ref,as_of,bindings,*,scenario_state):
        try:return module.reference(auth,ref,as_of,bindings,scenario_state=scenario_state)
        except ProtocolError as exc:
            if exc.code!='reference_span_forbidden' or not isinstance(ref,EvidenceRefV2):raise
        document=ref.model_copy(update={'quote':None,'span_start':None,'span_end':None})
        resolved=module.reference(auth,document,as_of,bindings,scenario_state=scenario_state)
        material=module.package.material(ref.object_id,ref.version)
        if any(f.disclosure.mode!='public' or (f.disclosure.actors and auth.actor_id not in f.disclosure.actors) for f in material.fragments):raise ProtocolError('reference_span_forbidden',status=403)
        projected=module.package.project(ref.object_id,ref.version,auth.actor_id,as_of.business_seq,auth.session_id)
        if {(f.ref.span_start,f.ref.span_end,f.text) for f in projected}!={(f.ref.span_start,f.ref.span_end,f.text) for f in material.fragments}:raise ProtocolError('reference_span_forbidden',status=403)
        text=read_file(module.package.root,resolved.source).decode('utf-8')
        if ref.span_start!=0 or ref.span_end!=len(text) or ref.quote!=text:raise ProtocolError('reference_span_forbidden',status=403)
        return resolved
    return resolve


def install_native_reads(registry, module, *, role_mode="local_reference",feedback_mode="waiting_model",store_provider=None):
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
    def context(view,page,auth):
        from career_lab.api.modules import public_state, PUBLIC_OPERATIONS
        module.check_bindings(view.bindings)
        if auth.allowed_objects is not None:raise ProtocolError('use_scoped_observation',status=403)
        return V2Response(result={'session':{'protocol':2,'sessionId':auth.session_id,'workLanguage':module.work_language,'scenarioHash':view.bindings.scenario.sha256},
            'state':public_state(view.state),'as_of':point(view.state).model_dump(mode='json'),
            'available':{name:bool(registry.availability(name).ready) for name in PUBLIC_OPERATIONS},
            'semantic':{'roles':'model' if role_mode=='model' else 'waiting_model' if role_mode=='local_reference' else 'unavailable',
                'feedback':feedback_mode,'assistant':'waiting_model'},
            'timeline':timeline(view,page,auth).result,
            'materials':registry.operations['materials.list'].handler(view,ResourcePage(limit=100),auth).result})
    def object_read(view,payload,auth):
        from career_lab.contracts.v2 import ObjectRef
        ref=payload.ref
        if ref.session_id!=auth.session_id or view.reference_allowed is None or not view.reference_allowed(ref):raise ProtocolError('object_not_found',status=404)
        if ref.kind=='material':
            module.reference(auth,ref,point(view.state),view.bindings,scenario_state=view.private_scenario_state)
            fragments=module.package.project(ref.object_id,ref.version,auth.actor_id,view.state.business_seq,auth.session_id)
            material=module.package.material(ref.object_id,ref.version)
            activation=view.private_scenario_state.material_activation[f'{ref.object_id}:{ref.version}']
            content={'title':material.title,'fragments':[f.model_copy(update={'ref':f.ref.model_copy(update={'observed_at_seq':view.state.business_seq,'valid_from_seq':activation})}).model_dump(mode='json',exclude={'fact_ids'}) for f in fragments]}
        elif ref.kind=='event':
            events=public_event_history(store_provider(),registry,auth,point(view.state),view=view)
            event=next((e for e in events if e.id==ref.object_id),None)
            if event is None:raise ProtocolError('object_not_found',status=404)
            content={'text':f"Material read: {event.data['material_id']} v{event.data['version']}" if event.type=='material_read' else event.type,'event':event.model_dump(mode='json')}
        else:content=view.get(ref).content
        return V2Response(result={'schema_version':2,'ref':ref.model_dump(mode='json'),'content':content})
    registry.register(Operation('workbench.read','read',ResourcePage,context,mutates=False,response_model=V2Response))
    registry.register(Operation('objects.read','read',ObjectRead,object_read,mutates=False,response_model=V2Response))
    return registry
