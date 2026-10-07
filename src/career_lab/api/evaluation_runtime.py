"""W02 authorized sources/rules -> W05 evidence -> the common fixed worker.

Only the frozen public source projection supplies material text. Business facts
carry either the source quote or the actual saved approval/configuration ref.
"""
import hashlib
import json
from pathlib import Path
from sqlalchemy import select
from career_lab.contracts import v2 as C
from career_lab.storage.v2_tables import v2_snapshots
from career_lab.storage.v2_lifecycle import point


class ScenarioEvidencePort:
    """Bind W02's owned fact producer to real authorized store history."""
    def __init__(self,store,module):
        from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter
        self.store,self.module=store,module
        adapter=ScenarioFactAdapter(module,authorize=lambda auth:store.authorize(auth,'read'),
            window_reader=self.window,record_reader=self.record,reference_resolver=self.reference)
        self.source,self.rules,self.submission_rules=adapter.source_reader,adapter.rule_provider,adapter.submission_rule_provider

    def points(self,auth,at):
        self.store.authorize(auth,'read')
        with self.store.db.engine.connect() as conn:
            return tuple(point(C.WorldStateV2.model_validate_json(raw)) for raw in conn.execute(
                select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==auth.session_id,v2_snapshots.c.storage_revision<=at.storage_revision)).scalars())

    def window(self,auth,at):
        from career_lab.scenarios.v2.evaluation_facts import ScenarioEvidenceWindow
        from career_lab.storage.v2_tables import v2_transactions
        from career_lab.storage.v2_store import TransactionResult
        points=self.points(auth,at)
        with self.store.db.engine.connect() as conn:
            transactions=[TransactionResult.model_validate_json(raw) for raw in conn.execute(select(v2_transactions.c.result).where(v2_transactions.c.session_id==auth.session_id)).scalars()]
        completed={t.transaction_id:point(t.state) for t in transactions if t.state.storage_revision<=at.storage_revision}
        def read(view):
            events=[];cursor=0;complete=auth.allowed_objects is None and callable(view.public_history)
            while cursor<at.business_seq:
                if view.public_history is None:complete=False;break
                history=view.public_history(C.ResourcePage(since_seq=cursor,limit=100),auth)
                if not history.acquisitions_complete or history.next_seq<=cursor:complete=False;break
                events.extend(history.events);cursor=history.next_seq
            pairs=tuple((event,completed[event.transaction_id]) for event in events if event.transaction_id in completed)
            return ScenarioEvidenceWindow(self.module.snapshot(view),view.bindings,view.objects,pairs,points,
                tests_complete=auth.allowed_objects is None,events_complete=complete and len(pairs)==len(events))
        return self.store.query_at(auth,at,read)

    def record(self,auth,ref,at):
        if at is None:return self.store.query(auth,lambda view:view.get(ref))
        return self.store.query_at(auth,at,lambda view:view.get(ref))
    def reference(self,auth,ref,at):
        def read(view):
            if view.reference_allowed is None or not view.reference_allowed(ref):raise C.ProtocolError('object_not_found',status=404)
        return self.store.query_at(auth,at,read)


class OncePerInputModel:
    """A provider repair loop cannot silently repeat the same semantic input."""
    retries=0
    def __init__(self,model): self.model,self.revision,self.seen=model,model.revision,set()
    def complete(self,messages,tools):
        key=C.digest(messages[:2])
        if key in self.seen:raise RuntimeError('Explicit new review required after a failed model result')
        self.seen.add(key)
        return self.model.complete(messages,tools)


def create_feedback_handler(module, *, model=None):
    from career_lab.evidence.v2.ports import CriterionPolicy
    bundle=C.EvaluationBundle.model_validate_json(C.read_file(module.package.root,module.bindings.evaluation))
    protocol=json.loads(C.read_file(module.package.root,bundle.protocol))
    if not protocol.get('installed'):return None
    if protocol.get('owner')!='W05' or bundle.mode!='advisory':raise C.ProtocolError('evaluation_runtime_unavailable',status=503)
    repo=Path(__file__).resolve().parents[3]
    for name,expected in protocol['source_files'].items():
        target=(repo/name).resolve()
        if not target.is_relative_to(repo) or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
            raise C.ProtocolError('evaluation_source_mismatch',status=409)
    policies=tuple(CriterionPolicy(**p) for p in protocol['policies'])
    def traced(plan,reader):
        from dataclasses import replace
        from career_lab.storage.v2_store import FeedbackReadTrace
        traces=[]
        for write in plan.writes:
            at=C.FeedbackV2.model_validate(write.content).as_of
            deps={C.canonical(ref):ref for ref in write.dependencies}
            for record in reader.records.values():
                if record.created_at is None or any(getattr(record.created_at,k)>getattr(at,k) for k in ('business_seq','workspace_revision','storage_revision')):continue
                ref=C.ObjectRef.model_validate({k:v for k,v in record.ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields})
                deps[C.canonical(ref)]=ref
            for name in ('verified_facts','historical_responsibilities'):
                for i,_ in enumerate(write.content.get(name) or ()):
                    traces.append(FeedbackReadTrace(write.ref,f'/{name}/{i}',tuple(deps.values())))
            for name in ('items','rule_items'):
                for i,_ in enumerate(write.content.get(name) or ()):
                    traces.append(FeedbackReadTrace(write.ref,f'/{name}/{i}/explanation',tuple(deps.values())))
            for name in ('business_response','next_options','independent_understanding'):
                if name in write.content:traces.append(FeedbackReadTrace(write.ref,'/'+name,tuple(deps.values())))
        return replace(plan,feedback_read_traces=tuple(traces))

    def run(store,view,envelope,auth):
        from career_lab.evidence.v2.store_reader import StoreEvidenceReader
        from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator,submission_feedback_plan
        from career_lab.api.reviews_v2 import create_review_evaluator,prepare_review_feedback,review_feedback_plan
        from career_lab.rubrics.v4.feedback import FeedbackEngine
        from career_lab.rubrics.v4.judge import AdvisoryJudge
        from career_lab.rubrics.v4.support import EvidenceSupportVerifier
        module.check_bindings(view.bindings)
        source=ScenarioEvidencePort(store,module)
        reader=StoreEvidenceReader(store,auth,policies=policies,source_reader=source.source,rule_provider=source.rules,submission_rule_provider=source.submission_rules)
        engine=FeedbackEngine(AdvisoryJudge(OncePerInputModel(model),EvidenceSupportVerifier(OncePerInputModel(model)))) if model is not None else FeedbackEngine()
        subject=C.FeedbackInput.model_validate(envelope.command.payload).subject
        if subject.kind=='submission':
            submitted=C.SubmissionV2.model_validate(view.get(subject).content)
            prepared=SubmissionEvaluator(reader,engine=engine,work_language=module.work_language).evaluate(auth,submitted)
            return traced(submission_feedback_plan(view,envelope.command,auth,prepared),reader)
        request=C.ReviewRequest.model_validate(view.get(subject).content)
        prepared=prepare_review_feedback(create_review_evaluator(reader,engine=engine,work_language=module.work_language),auth,request)
        return traced(review_feedback_plan(view,envelope.command,auth,prepared),reader)
    return run
