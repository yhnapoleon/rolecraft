"""Formal submission anchor: fixed submitted decision/config and exact products.

The shared worker performs generation outside its transaction and commits via
its existing claim/derived-subject boundary. No local queue or auto-revision.
"""
from career_lab.contracts import v2 as C
from career_lab.rubrics.v4.feedback import FeedbackEngine
from .assembler import EvidenceAssemblerV2
from .factual import factual_feedback
from .formal_feedback import attach_sections
from .localization import validate_language


class SubmissionEvaluator:
    def __init__(self,reader,*,engine=None,work_language='zh',model_bytes=16000):
        self.reader=reader;self.engine=engine or FeedbackEngine();self.work_language=validate_language(work_language);self.model_bytes=model_bytes

    def evaluate(self,auth,submission):
        if not isinstance(submission,C.SubmissionV2) or submission.session_id!=auth.session_id or submission.evaluation!=self.reader.evaluation:
            raise C.ProtocolError('submission_binding_mismatch')
        at=submission.as_of;reports=[]
        subject=C.ObjectRef(session_id=submission.session_id,kind='submission',object_id=submission.id,version=submission.version)
        assembler=EvidenceAssemblerV2(self.reader,self.model_bytes,work_language=self.work_language)
        for product in submission.products:
            source=self.reader.read(auth,product,at)
            snapshot=self.reader.snapshot(auth,product,at)
            # A rule provider must describe the actual submitted configuration.
            if submission.config is not None and snapshot.config_version is not None and snapshot.config_version!=submission.config.config_version:
                raise C.ProtocolError('submission_config_mismatch')
            packages=tuple(assembler.assemble(auth=auth,subject_id=product.object_id,subjects=(product,),evidence_refs=tuple({C.canonical(r):r for r in (*source.declared_refs,*submission.evidence_refs)}.values()),
                purpose='commitment',decision=submission.decision,as_of=at,policy=policy,snapshot=snapshot,anchor_mode='submission',requested_at=at) for policy in self.reader.policies())
            report,diagnostics=self.engine.evaluate(auth.session_id,product,self.reader.evaluation,at,packages,work_language=self.work_language)
            facts=factual_feedback(self.reader,auth,product,at,at,work_language=self.work_language,anchor_mode='submission')
            report=attach_sections(report,self.reader,auth,product,at,facts,diagnostics['historical_responsibilities'],diagnostics['rule_items'],work_language=self.work_language)
            raw=report.model_dump(mode='json');raw.update(subject=subject.model_dump(mode='json'),id=C.digest([subject.model_dump(mode='json'),product.model_dump(mode='json'),submission.evaluation.model_dump(mode='json'),'w05-submission-feedback']))
            reports.append(C.FeedbackV2.model_validate(raw))
        # Empty formal submissions are not assigned a synthetic quality grade.
        return {'submission':submission,'submission_hash':C.digest(submission),'reports':tuple(reports),'work_language':self.work_language}


def submission_feedback_plan(view,command,auth,prepared):
    from career_lab.storage.v2_store import Mutation,ObjectWrite,references
    submission=prepared['submission'];subject=C.ObjectRef(session_id=auth.session_id,kind='submission',object_id=submission.id,version=submission.version)
    if C.digest(C.SubmissionV2.model_validate(view.get(subject).content))!=prepared['submission_hash']:raise C.ProtocolError('submission_input_changed')
    if C.FeedbackInput.model_validate(command.payload).subject!=subject:raise C.ProtocolError('feedback_subject_mismatch')
    writes=[]
    for report in prepared['reports']:
        if report.subject!=subject or report.evaluation!=submission.evaluation:raise C.ProtocolError('feedback_subject_mismatch')
        content=report.model_dump(mode='json');ref=C.ObjectRef(session_id=auth.session_id,kind='feedback',object_id=report.id,version=1)
        writes.append(ObjectWrite(ref=ref,expected_head=0,content=content,dependencies=references(content)))
    return Mutation(writes=tuple(writes),result={'feedbacks':[w.ref.model_dump(mode='json') for w in writes]})


def submission_plan_with_feedback(view,command,auth,*,job_name='v2.submission-feedback'):
    """Atomic submission + derived feedback job, registered by the shared app.

    Queue while the submit transaction is still active. A second learner write
    after terminal submission is neither required nor used as a workaround.
    """
    from dataclasses import replace
    from career_lab.storage.v2_lifecycle import record_submission
    from career_lab.storage.v2_store import JobRequest
    plan=record_submission(view,command,auth)
    write=next(w for w in plan.writes if w.ref.kind=='submission')
    submitted=C.SubmissionV2.model_validate(write.content)
    job_command=C.Command(schema_version=2,request_id=C.digest([auth.session_id,command.request_id,'submission-feedback']),
        expected_version=command.expected_version,expected_workspace_revision=command.expected_workspace_revision,
        operation='feedback.create',payload=C.FeedbackInput(subject=write.ref).model_dump(mode='json'))
    job=JobRequest(name=job_name,command=job_command,sources=(write.ref,),context_hash=C.digest(submitted))
    return replace(plan,jobs=(*plan.jobs,job))
