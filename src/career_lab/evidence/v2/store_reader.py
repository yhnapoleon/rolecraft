"""Read-only evidence capture from the existing authorized V2Store.

No research export, alternate database, private scenario body, writes or model
calls. The query boundary supplies projected objects; existing snapshot/event
rows supply their actual points and activities. Material text and business rule
facts come only through explicitly injected public source/rule adapters.
"""
from dataclasses import replace
from sqlalchemy import select
from career_lab.contracts import v2 as C
from career_lab.storage.v2_tables import v2_snapshots,v2_events
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.role_memory import RoleTurn,RoleReply,RoleDisplay
from .ports import SourceRecord,ActivityRecord,ActivityLedger,RuleSnapshot
from .assembler import base_ref,product_text
from .history import before


class StoreEvidenceReader:
    def __init__(self,store,auth,*,policies,source_reader=None,rule_provider=None,submission_rule_provider=None):
        if auth.actor_id!='learner' or auth.executor.kind not in {'human','external_agent'}:raise C.ProtocolError('public_actor_required',status=403)
        self.store=store;self.identity=(auth.session_id,auth.actor_id,auth.credential_id)
        self._policies=tuple(policies);self.source_reader=source_reader;self.rule_provider=rule_provider;self.submission_rule_provider=submission_rule_provider
        if not self._policies:raise ValueError('frozen evaluation policies required')
        self.records={};self.event_targets={};self.activities=[]
        def capture(view):
            self.captured_at=point(view.state);self.evaluation=view.bindings.evaluation
            # Only metadata points and visible events are consumed here. Object
            # bodies come exclusively from the common authorized query view.
            with store.db.engine.connect() as conn:
                states=[C.WorldStateV2.model_validate_json(x) for x in conn.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==auth.session_id,v2_snapshots.c.storage_revision<=self.captured_at.storage_revision)).scalars()]
                events=[C.StoredEvent.model_validate_json(x) for x in conn.execute(select(v2_events.c.record).where(v2_events.c.session_id==auth.session_id,v2_events.c.seq<=self.captured_at.business_seq).order_by(v2_events.c.seq)).scalars()]
            self.points={state.storage_revision:point(state) for state in states}
            self.states={C.canonical(point(state)):state for state in states}
            allowed={C.canonical(row.ref):row for row in view.objects}
            for row in view.objects:
                born=self.points.get(row.created_storage_revision)
                text=None;refs=();author=executor=adopter=None;activity=None;target=None;other=None
                if row.ref.kind=='product':
                    product=C.WorkProductVersion.model_validate(row.content)
                    text=product_text(product);refs=tuple(C.EvidenceRefV2.model_validate(x) for x in self._declared(product))
                    author=product.author;executor=product.executor;adopter=product.adoption.adopter
                elif row.ref.kind=='test':
                    test=C.TestResultV2.model_validate(row.content);text=test.query+'\n'+test.answer
                    executor=test.execution.executor;activity='test_run'
                elif row.ref.kind=='role_turn':
                    turn=RoleTurn.model_validate(row.content);text=turn.input.text;executor=turn.executor;activity='question_sent';other=turn.input.role_id
                elif row.ref.kind=='role_reply':
                    reply=RoleReply.model_validate(row.content);text=reply.text;executor=reply.executor;target=reply.request;other=reply.role_id
                    if reply.status=='completed':activity='reply_received'
                elif row.ref.kind=='role_display':
                    display=RoleDisplay.model_validate(row.content);text='Displayed reply';executor=display.executor;activity='learner_displayed';target=display.reply
                elif row.ref.kind in {'config','business_request','business_decision','submission','review'}:
                    # Deterministic public typed records, not hidden evaluation data.
                    text=C.canonical(row.content);executor=row.creator
                if text is None:continue
                ref=C.EvidenceRefV2(**row.ref.model_dump(),observed_at_seq=born.business_seq if born else 0)
                record=SourceRecord(ref,text,born,refs,author,executor,adopter,activity,target,auth.actor_id)
                self.records[self.key(ref)]=record
                if activity and born is not None and executor is not None:
                    self.activities.append(ActivityRecord(ref,activity,born,executor,auth.actor_id,target,other))
            for event in events:
                if event.type!='material_read' or auth.actor_id not in event.visible_to:continue
                data=event.data
                if not isinstance(data.get('material_id'),str) or type(data.get('version')) is not int:continue
                target=C.ObjectRef(session_id=auth.session_id,kind='material',object_id=data['material_id'],version=data['version'])
                try:
                    if view.reference_allowed is None or not view.reference_allowed(target):continue
                except C.ProtocolError:continue
                born=min((p for p in self.points.values() if p.business_seq>=event.seq),key=lambda p:p.storage_revision,default=None)
                if born is None:continue
                ref=C.EvidenceRefV2(session_id=auth.session_id,kind='event',object_id=event.id,version=1,observed_at_seq=event.seq)
                text='Material read: '+target.object_id+' v'+str(target.version)
                self.records[self.key(ref)]=SourceRecord(ref,text,born,executor=event.executor,activity_kind='material_read',activity_target=target,actor_id=auth.actor_id)
                self.event_targets[event.id]=target
                self.activities.append(ActivityRecord(ref,'material_read',born,event.executor,auth.actor_id,target))
            # Complete ledger assertions remain the caller's frozen source policy;
            # capturing all SQL rows alone does not prove all business producers
            # recorded the five activity kinds. Visible rows still remain useful.
            self.activities.sort(key=lambda r:(r.occurred_at.storage_revision,r.occurred_at.workspace_revision,r.occurred_at.business_seq,C.canonical(r.ref)))
            self.ledger=ActivityLedger(tuple(self.activities),tuple((k,False) for k in ('material_read','test_run','question_sent','reply_received','learner_displayed')),
                covered_from=C.VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0),covered_through=self.captured_at,captured_at=self.captured_at)
            self.snapshot_sha256=C.digest({'point':self.captured_at.model_dump(mode='json'),'records':[{'ref':r.ref.model_dump(mode='json'),'text':r.text,'created_at':r.created_at.model_dump(mode='json') if r.created_at else None} for r in self.records.values()]})
        store.query(auth,capture)

    @staticmethod
    def key(ref):return (ref.session_id,ref.kind,ref.object_id,ref.version,ref.config_version)

    @staticmethod
    def _declared(product):
        # Only explicit evidence arrays, including structured block/case refs;
        # task/cycle/share/internal provenance do not become citations.
        refs=list(product.evidence_refs)
        payload=product.structured_payload
        if payload and payload.type=='test_plan':refs.extend(r for case in payload.cases for r in case.refs)
        if payload and payload.type=='investigation':refs.extend(b.source_ref for b in payload.blocks if b.source_ref is not None)
        return [r.model_dump(mode='json') for r in refs]

    def authorize(self,auth):
        if (auth.session_id,auth.actor_id,auth.credential_id)!=self.identity:raise C.ProtocolError('not_found',status=404)
        self.store.authorize(auth,'read')

    def read(self,auth,ref,as_of):
        self.authorize(auth)
        if ref.session_id!=auth.session_id:raise C.ProtocolError('not_found',status=404)
        if not before(as_of,self.captured_at):raise C.ProtocolError('snapshot_window_unavailable')
        if ref.kind=='event' and ref.object_id in self.event_targets:
            self.store.can_reference(auth,self.event_targets[ref.object_id])
        elif ref.kind=='material':
            self.store.can_reference(auth,ref)
            if self.source_reader is None:raise C.ProtocolError('source_unavailable',status=404)
            record=self.source_reader(auth,ref,as_of)
            if base_ref(record.ref)!=base_ref(ref):raise C.ProtocolError('evidence_version_mismatch')
            return record
        else:self.store.read(auth,base_ref(ref),storage_revision=self.captured_at.storage_revision)
        record=self.records.get(self.key(ref))
        if record is None:raise KeyError(self.key(ref))
        return record

    def activity_log(self,auth,as_of):
        self.authorize(auth)
        if not before(as_of,self.captured_at):raise C.ProtocolError('snapshot_window_unavailable')
        return self.ledger

    def policies(self):return self._policies

    def snapshot(self,auth,subject,as_of):
        self.authorize(auth);self.read(auth,subject,as_of)
        state=self.states.get(C.canonical(as_of))
        if state is None:raise C.ProtocolError('rule_snapshot_unavailable')
        if self.rule_provider is not None:return self.rule_provider(auth,subject,as_of)
        tests=[];refs=[]
        for record in self.records.values():
            if record.ref.kind!='test' or not before(record.created_at,as_of):continue
            try:stored=self.store.read(auth,base_ref(record.ref),storage_revision=as_of.storage_revision)
            except C.ProtocolError:continue
            tests.append(C.TestResultV2.model_validate(stored.content));refs.append(record.ref)
        return RuleSnapshot(as_of,tests=tuple(tests),test_refs=tuple(refs),config_version=state.config_version)


    def submission_snapshot(self,auth,submission):
        """All submitted works are one evaluation scope for rubric-v2.

        Single-work source compatibility is retained. Multiple-work content
        absence cannot be inferred by merging per-work snapshots; without the
        trusted aggregate provider it remains unknown.
        """
        self.authorize(auth)
        if submission.session_id!=auth.session_id:raise C.ProtocolError('not_found',status=404)
        for ref in submission.products:self.read(auth,ref,submission.as_of)
        if self.submission_rule_provider is not None:
            return self.submission_rule_provider(auth,submission)
        if len(submission.products)==1:return self.snapshot(auth,submission.products[0],submission.as_of)
        histories=[]
        for ref in submission.products:
            for duty in self.snapshot(auth,ref,submission.as_of).responsibilities:
                if duty not in histories:histories.append(duty)
        return RuleSnapshot(submission.as_of,config_version=submission.config.config_version if submission.config else None,responsibilities=tuple(histories))
