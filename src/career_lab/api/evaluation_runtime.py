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
    def __init__(self, store, module): self.store,self.module=store,module

    def points(self,auth,at):
        self.store.authorize(auth,'read')
        with self.store.db.engine.connect() as conn:
            return tuple(point(C.WorldStateV2.model_validate_json(raw)) for raw in conn.execute(
                select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==auth.session_id,v2_snapshots.c.storage_revision<=at.storage_revision)).scalars())

    def source(self,auth,ref,at):
        from career_lab.evidence.v2.ports import SourceRecord
        def read(view):
            self.module.reference(auth,ref,at,view.bindings,scenario_state=view.private_scenario_state)
            material=next(m for m in self.module.package.materials if (m.id,m.version)==(ref.object_id,ref.version))
            projected=self.module.package.project(ref.object_id,ref.version,auth.actor_id,at.business_seq,auth.session_id)
            # Absolute citation offsets are from the actual file. Never pad a
            # redacted text or pass a partially private file to the evaluator.
            originals={(f.ref.span_start,f.ref.span_end,f.text) for f in material.fragments}
            approved={(f.ref.span_start,f.ref.span_end,f.text) for f in projected}
            if not originals or originals!=approved:raise C.ProtocolError('source_unavailable',status=404)
            filename=self.module.package.rules['material_files'][ref.object_id][str(ref.version)]
            text=C.read_file(self.module.package.root,self.module.files[filename]).decode('utf-8')
            activation=view.private_scenario_state.material_activation[f'{ref.object_id}:{ref.version}']
            born=min((p for p in self.points(auth,at) if p.business_seq>=activation),key=lambda p:p.storage_revision,default=None)
            bare={k:v for k,v in ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields}
            # A document-only reference resolves to an explicit permitted excerpt;
            # it never becomes a fabricated whole-file span across fragments.
            chosen=ref if isinstance(ref,C.EvidenceRefV2) and ref.quote is not None else projected[0].ref
            observed=ref.observed_at_seq if isinstance(ref,C.EvidenceRefV2) else activation
            evidence=C.EvidenceRefV2(**bare,quote=chosen.quote,span_start=chosen.span_start,span_end=chosen.span_end,
                observed_at_seq=observed,valid_from_seq=activation,valid_until_seq=chosen.valid_until_seq)
            return SourceRecord(evidence,text,born)
        return self.store.query_at(auth,at,read)

    def rules(self,auth,subject,at):
        from career_lab.evidence.v2.ports import RuleSnapshot,VerifiedFact,ResponsibilityFact
        points={p.storage_revision:p for p in self.points(auth,at)}
        def read(view):
            view.get(subject)
            def evidence(row):
                born=points.get(row.created_storage_revision)
                if born is None:raise C.ProtocolError('source_time_unknown')
                return C.EvidenceRefV2(**row.ref.model_dump(),observed_at_seq=born.business_seq)
            tests=tuple(r for r in view.objects if r.ref.kind=='test')
            responsibilities=tuple(ResponsibilityFact('R4.functional_tests','actual_action',points[r.created_storage_revision],
                points[r.created_storage_revision],(subject,),(evidence(r),),actor_id=auth.actor_id,executor=r.creator)
                for r in tests if r.created_storage_revision in points)
            basic={'tests':tuple(C.TestResultV2.model_validate(r.content) for r in tests),
                'test_refs':tuple(evidence(r) for r in tests),'responsibilities':responsibilities}
            try:snapshot=self.module.snapshot(view)
            except C.ProtocolError:return RuleSnapshot(at,**basic)
            config=view.get(view.private_scenario_state.current_config)
            cfg=C.AssistantConfig.model_validate(config.content);cref=evidence(config);facts=[]
            def authored(name):
                candidates=[f for f in self.module.package.facts if f.id==name and f.disclosure.mode=='public']
                for fact in candidates:
                    source=fact.source.model_copy(update={'session_id':auth.session_id})
                    try:self.module.reference(auth,source,at,view.bindings,scenario_state=view.private_scenario_state)
                    except C.ProtocolError:continue
                    return fact.value,source
                raise C.ProtocolError('source_unavailable',status=404)
            def resource(name):
                decisions=sorted((r for r in view.objects if r.ref.kind=='business_decision' and r.content['status'] in {'approved','accepted'} and name in r.content['granted']),key=lambda r:r.created_storage_revision,reverse=True)
                if decisions:return decisions[0].content['granted'][name],evidence(decisions[0])
                value,ref=authored(name)
                if value!=snapshot.world.resources.get(name):raise C.ProtocolError('resource_source_unavailable',status=404)
                return value,ref
            facts.extend([VerifiedFact('participants',cfg.participants,(cref,)),VerifiedFact('requested_launch_day',cfg.launch_day,(cref,))])
            for name,label in [('capacity','capacity'),('dev_days','available_dev_days'),('deadline_day','deadline_day')]:
                try:value,source=resource(name);facts.append(VerifiedFact(label,value,(source,)))
                except C.ProtocolError:pass
            try:
                cost=0;refs=[cref]
                for work in cfg.work_items:
                    value,source=authored('cost_'+work);cost+=value;refs.append(source)
                facts.append(VerifiedFact('required_dev_days',cost,tuple(refs)))
            except C.ProtocolError:pass
            decisions=sorted((r for r in view.objects if r.ref.kind=='business_decision'),key=lambda r:r.created_storage_revision)
            return RuleSnapshot(at,facts=tuple(facts),config_version=cfg.config_version,
                business_response=decisions[-1].content['reason'] if decisions else '',
                business_response_refs=(evidence(decisions[-1]),) if decisions else (),**basic)
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
        reader=StoreEvidenceReader(store,auth,policies=policies,source_reader=source.source,rule_provider=source.rules)
        engine=FeedbackEngine(AdvisoryJudge(OncePerInputModel(model),EvidenceSupportVerifier(OncePerInputModel(model)))) if model is not None else FeedbackEngine()
        subject=C.FeedbackInput.model_validate(envelope.command.payload).subject
        if subject.kind=='submission':
            submitted=C.SubmissionV2.model_validate(view.get(subject).content)
            prepared=SubmissionEvaluator(reader,engine=engine,work_language='zh').evaluate(auth,submitted)
            return traced(submission_feedback_plan(view,envelope.command,auth,prepared),reader)
        request=C.ReviewRequest.model_validate(view.get(subject).content)
        prepared=prepare_review_feedback(create_review_evaluator(reader,engine=engine,work_language='zh'),auth,request)
        return traced(review_feedback_plan(view,envelope.command,auth,prepared),reader)
    return run
