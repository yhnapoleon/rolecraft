"""Explicit provider assembly; no implicit credentials, costs, or hidden retry."""

from career_lab.runtime.model_adapter import OpenAICompatibleModel
from .feedback import FeedbackEngine
from .judge import AdvisoryJudge
from .support import EvidenceSupportVerifier


def create_feedback_engine(
    *,
    api_key: str,
    base_url: str,
    model: str,
    support_model: str | None = None,
    timeout: float = 45.0,
    input_bytes: int = 64000,
):
    """Configure real single-call adapters; construction performs no I/O.

    The existing provider bounds responses to 512 tokens. Each item permits one
    Judge proposal and at most one support call; validation never retries. Caller authorizes execution
    and owns provider/cost configuration. No quality validation is implied.
    """
    if not api_key or not base_url or not model or not 0 < timeout <= 120:
        raise ValueError("explicit provider configuration is required")
    judge = OpenAICompatibleModel(api_key, base_url, model, timeout=timeout, retries=0)
    verifier = OpenAICompatibleModel(
        api_key, base_url, support_model or model, timeout=timeout, retries=0
    )
    return FeedbackEngine(
        AdvisoryJudge(
            judge,
            EvidenceSupportVerifier(verifier, input_bytes=input_bytes),
            input_bytes=input_bytes,
        )
    )


def require_first_model_attempt(claim):
    """workbench calls after authorized saved-result replay, BEFORE model generation.

    A leased attempt beyond 1 may only replay an already committed result. It
    must not regenerate even when the previous attempt crashed before saving.
    An explicit user retry must create a new authorized request/job identity.
    This helper owns no queue or persistence and does not install itself.
    """
    from career_lab.jobs.worker import WorkerClaim
    from career_lab.contracts.v2.core import ProtocolError

    if not isinstance(claim, WorkerClaim) or claim.attempt != 1:
        raise ProtocolError("model_attempt_requires_explicit_retry", status=409)
