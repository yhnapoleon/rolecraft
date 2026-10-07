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
