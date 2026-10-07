"""W05 production integration boundary, awaiting coordinator-pinned W01 input.

The evidence assembler and advisory evaluator are usable pure modules. HTTP,
lifecycle transitions, idempotency, and jobs must be registered on the shared
Gateway/V2Store. Never mount the historical test router as a production fallback.
"""
from career_lab.contracts.v2.core import ProtocolError


def create_service(*args, **kwargs):
    raise ProtocolError('module_unavailable', 'W05 requires the fixed public lifecycle and worker input', status=503)


def create_router(*args, **kwargs):
    raise ProtocolError('module_unavailable', 'Install W05 operations on the shared Gateway', status=503)


def create_review_evaluator(reader,*,engine=None,model_bytes=16000):
    """Default read-only factual/semantic handler; no provider required.

    Reader must supply an immutable authorized snapshot, frozen policies and the
    exact-version formation point. Persistence/worker/objections remain external.
    """
    from career_lab.evidence.v2.review_evaluator import ReviewEvaluator
    return ReviewEvaluator(reader,engine=engine,model_bytes=model_bytes)


def prepare_review_feedback(evaluator,auth,request):
    """Evaluate a caller-authorized saved ReviewRequest outside transactions.

    Returns one immutable report per exact work version. It does not invent an
    aggregate grade across works, close objections or start a worker/queue.
    """
    from career_lab.contracts import v2 as C
    if not isinstance(request,C.ReviewRequest):raise C.ProtocolError('saved_review_required')
    result=evaluator.handle(auth,request,request.as_of)
    subject=C.ObjectRef(session_id=request.session_id,kind='review',object_id=request.id,version=request.version)
    reports=[]
    for entry in result['reviews']:
        if entry['feedback'] is None:raise C.ProtocolError('subject_point_unknown')
        raw=entry['feedback']
        raw.update(subject=subject.model_dump(mode='json'),id=C.digest([subject.model_dump(mode='json'),entry['subject'],request.evaluation.model_dump(mode='json'),'w05-c8-feedback']))
        reports.append(C.FeedbackV2.model_validate(raw))
    return {'request':request,'request_hash':C.digest(request),'reports':tuple(reports),
            'followup_of':request.followup_of,'followup_status':result['followup_status']}


def review_feedback_plan(view,command,auth,prepared):
    """Commit only prepared public feedback through the single shared store.

    The worker must supply the actual claim/derived_subject to V2Store. Internal
    evidence snapshots/diagnostics are never retagged learner-visible here.
    """
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_store import Mutation,ObjectWrite,references
    request=prepared['request'];subject=C.ObjectRef(session_id=auth.session_id,kind='review',object_id=request.id,version=request.version)
    if request.session_id!=auth.session_id or C.digest(C.ReviewRequest.model_validate(view.get(subject).content))!=prepared['request_hash']:
        raise C.ProtocolError('review_input_changed',status=409)
    body=C.FeedbackInput.model_validate(command.payload)
    if body.subject!=subject:raise C.ProtocolError('feedback_subject_mismatch')
    for product in request.subjects:view.get(product)
    writes=[]
    for report in prepared['reports']:
        if report.subject!=subject or report.evaluation!=request.evaluation:raise C.ProtocolError('feedback_subject_mismatch')
        ref=C.ObjectRef(session_id=auth.session_id,kind='feedback',object_id=report.id,version=1)
        content=report.model_dump(mode='json')
        writes.append(ObjectWrite(ref=ref,expected_head=0,content=content,dependencies=references(content)))
    return Mutation(writes=tuple(writes),result={'feedbacks':[w.ref.model_dump(mode='json') for w in writes],
        'followup_of':[r.model_dump(mode='json') for r in request.followup_of],
        'followup_status':prepared['followup_status']})
