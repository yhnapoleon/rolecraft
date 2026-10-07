"""Read-only review handlers: local source gaps do not erase other feedback.

Public DTOs, persisted identities, worker registration and objections remain W01
contracts. This owned boundary returns separately timed, inspectable sections.
"""
from career_lab.contracts.v2.core import ProtocolError
from .assembler import EvidenceAssemblerV2,base_ref,purpose_of
from .factual import factual_feedback
from .history import before
from .availability import unavailable,SAFE_REASON

UNSET=object()
DECISIONS=frozenset({'launch','launch_narrow','no_go','defer_with_conditions'})


class ReviewEvaluator:
    def __init__(self,reader,*,engine=None,model_bytes=16000):
        from career_lab.rubrics.v4.feedback import FeedbackEngine
        self.reader=reader;self.engine=engine or FeedbackEngine();self.model_bytes=model_bytes

    def _decision(self,auth,subject,source,at,explicit):
        if explicit is not UNSET:
            if explicit is not None and explicit not in DECISIONS:raise ProtocolError('invalid_decision')
            return explicit,'explicit_request' if explicit is not None else 'unspecified'
        declared=source.structured_decision
        if declared is None:return None,'unspecified'
        if declared.value not in DECISIONS or declared.subject!=subject or declared.declared_at!=at or base_ref(declared.source)!=subject:
            raise ProtocolError('structured_decision_binding_mismatch')
        try:EvidenceAssemblerV2(self.reader).resolve(auth,declared.source,at)
        except (KeyError,ProtocolError) as error:
            if not unavailable(error):raise
            return None,'structured_unverified'
        return declared.value,'structured_subject'

    def review(self,auth,subjects,*,purpose,requested_at,decision=UNSET,scope=(),question=''):
        policies=self.reader.policies()
        if set(scope)-{p.id for p in policies}:raise ProtocolError('unknown_review_scope')
        selected=tuple(p for p in policies if not scope or p.id in scope)
        if not subjects or len(subjects)>50 or len(subjects)!=len({r.model_dump_json() for r in subjects}):raise ProtocolError('invalid_review_subjects')
        results=[]
        for subject in subjects:
            if subject.kind!='product':raise ProtocolError('unsupported_review_subject')
            # Session/subject access errors are intentionally not caught.
            source=self.reader.read(auth,subject,requested_at)
            if base_ref(source.ref)!=subject:raise ProtocolError('subject_identity_mismatch')
            at=source.created_at
            if at is None:
                results.append({'subject':subject.model_dump(mode='json'),'evaluated_at':None,'requested_at':requested_at.model_dump(mode='json'),
                    'verified_facts':{'section':'verified_facts','status':'unknown','summary':['作品形成时点未知，未用请求时点补造历史判断。']},
                    'historical_responsibilities':[],'feedback':None,'pending_reason':'subject_point_unknown'})
                continue
            if not before(at,requested_at):raise ProtocolError('future_subject_anchor')
            chosen,origin=self._decision(auth,subject,source,at,decision)
            facts=factual_feedback(self.reader,auth,subject,at,requested_at)
            reference_gap=any(r['status']!='exact_reference_verified' for r in facts['references'])
            snapshot=self.reader.snapshot(auth,subject,at)
            assembler=EvidenceAssemblerV2(self.reader,self.model_bytes)
            packages=tuple(assembler.assemble(auth=auth,subject_id=subject.object_id,subjects=(subject,),
                evidence_refs=source.declared_refs,purpose=purpose,decision=chosen,as_of=at,policy=policy,snapshot=snapshot,
                question=question,anchor_mode='product_version',requested_at=requested_at) for policy in selected)
            report,diagnostics=self.engine.evaluate(auth.session_id,subject,self.reader.evaluation,at,packages)
            history=diagnostics['historical_responsibilities']
            record_status=[]
            if purpose_of(purpose)=='result':
                for policy in selected:
                    if not policy.launch_only:continue
                    available=any(h['criterion']==policy.id and h['kind'] in {'actual_action','completion_claim'} and h['finding']!='unknown' for h in history)
                    record_status.append({'criterion':policy.id,'status':'provided' if available else 'pending',
                        'reason':'已提供可核验的实际行动或明确完成声明，见历史层具体结果。' if available else '未提供可核验的实际行动或明确完成声明记录；该报告事项待核验，不代表没有发生。'})
            diagnostics['result_record_status']=record_status
            result={'subject':subject.model_dump(mode='json'),'evaluated_at':at.model_dump(mode='json'),
                'requested_at':requested_at.model_dump(mode='json'),'decision':chosen,'decision_origin':origin,'verified_facts':facts,
                'historical_responsibilities':history,'result_record_status':record_status,
                'source_issues':[{'status':'pending','reason':SAFE_REASON}] if any(p.rule_context.get('source_issues') for p in packages) else [],
                'feedback':report.model_dump(mode='json'),'diagnostics':diagnostics}
            if reference_gap:result['pending_reason']='declared_reference_unverified'
            results.append(result)
        return {'reviews':results,'current_state_assessment':None,
                'boundary':'Each exact work uses its formation point; local source gaps do not erase other verified output.'}

    def handle(self,auth,request,requested_at,*,decision=UNSET):
        """Pure handler, prepared for the optional decision in the future DTO.

        Today the explicit keyword is available to the trusted adapter. Frozen
        ReviewInput is unchanged; an omitted field falls back to vetted structure,
        and an explicit None preserves uncertainty without forcing a form.
        """
        if decision is UNSET:
            fields=getattr(type(request),'model_fields',None)
            if fields is not None:
                if 'decision' in fields and 'decision' in request.model_fields_set:decision=request.decision
            elif hasattr(request,'decision'):decision=request.decision
        return self.review(auth,request.subjects,purpose=request.purpose,scope=request.scope,
                           question=request.question,requested_at=requested_at,decision=decision)
