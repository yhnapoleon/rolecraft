"""Read-only review handlers with a default factual layer and no model calls.

Public Gateway/worker registration and persistent objection DTOs remain W01's
contract. This owned handler returns separately timed, inspectable sections.
"""
from career_lab.contracts.v2.core import ProtocolError
from .assembler import EvidenceAssemblerV2
from .factual import factual_feedback
from .history import before


class ReviewEvaluator:
    def __init__(self,reader,*,engine=None,model_bytes=16000):
        from career_lab.rubrics.v4.feedback import FeedbackEngine
        self.reader=reader;self.engine=engine or FeedbackEngine();self.model_bytes=model_bytes

    def review(self,auth,subjects,*,purpose,requested_at,decision=None,scope=(),question=''):
        policies=self.reader.policies()
        if set(scope)-{p.id for p in policies}:raise ProtocolError('unknown_review_scope')
        selected=tuple(p for p in policies if not scope or p.id in scope)
        if not subjects or len(subjects)>50 or len(subjects)!=len({r.model_dump_json() for r in subjects}):raise ProtocolError('invalid_review_subjects')
        results=[]
        for subject in subjects:
            if subject.kind!='product':raise ProtocolError('unsupported_review_subject')
            source=self.reader.read(auth,subject,requested_at)
            at=source.created_at
            if at is None:
                results.append({'subject':subject.model_dump(mode='json'),'evaluated_at':None,'requested_at':requested_at.model_dump(mode='json'),
                    'verified_facts':{'section':'verified_facts','status':'unknown','summary':['作品形成时点未知，未用请求时点补造历史判断。']},
                    'historical_responsibilities':[],'feedback':None,'pending_reason':'subject_point_unknown'})
                continue
            if not before(at,requested_at):raise ProtocolError('future_subject_anchor')
            facts=factual_feedback(self.reader,auth,subject,at,requested_at)
            if any(r['status']!='exact_reference_verified' for r in facts['references']):
                results.append({'subject':subject.model_dump(mode='json'),'evaluated_at':at.model_dump(mode='json'),'requested_at':requested_at.model_dump(mode='json'),
                    'verified_facts':facts,'historical_responsibilities':[],'feedback':None,'pending_reason':'declared_reference_unverified'})
                continue
            snapshot=self.reader.snapshot(auth,subject,at)
            assembler=EvidenceAssemblerV2(self.reader,self.model_bytes)
            # Product-linked citations are evaluated at the product's time.
            # A request cannot silently attach later evidence to an older work.
            packages=tuple(assembler.assemble(auth=auth,subject_id=subject.object_id,subjects=(subject,),
                evidence_refs=source.declared_refs,purpose=purpose,decision=decision,as_of=at,policy=policy,snapshot=snapshot,
                question=question,anchor_mode='product_version',requested_at=requested_at) for policy in selected)
            report,diagnostics=self.engine.evaluate(auth.session_id,subject,self.reader.evaluation,at,packages)
            results.append({'subject':subject.model_dump(mode='json'),'evaluated_at':at.model_dump(mode='json'),
                'requested_at':requested_at.model_dump(mode='json'),'verified_facts':facts,
                'historical_responsibilities':diagnostics['historical_responsibilities'],
                'feedback':report.model_dump(mode='json'),'diagnostics':diagnostics})
        return {'reviews':results,'current_state_assessment':None,
                'boundary':'Each exact product version uses its formation point; no later current-state check is implied.'}

    def handle(self,auth,request,requested_at):
        """Pure ReviewInput handler; never writes a lifecycle or starts a queue."""
        return self.review(auth,request.subjects,purpose=request.purpose,scope=request.scope,
                           question=request.question,requested_at=requested_at,decision=None)
