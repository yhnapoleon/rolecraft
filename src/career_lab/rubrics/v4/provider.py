"""Explicit provider assembly; no implicit credentials, costs, or hidden retry."""
from career_lab.runtime.model_adapter import OpenAICompatibleModel
from .feedback import FeedbackEngine
from .judge import AdvisoryJudge
from .support import EvidenceSupportVerifier


def create_feedback_engine(*,api_key:str,base_url:str,model:str,support_model:str|None=None,
                           timeout:float=45.0,input_bytes:int=64000):
    """Configure real single-call adapters; construction performs no I/O.

    The existing provider bounds responses to 512 tokens. Each item permits at
    most two Judge proposals and two support calls. Caller authorizes execution
    and owns provider/cost configuration. No quality validation is implied.
    """
    if not api_key or not base_url or not model or not 0<timeout<=120:
        raise ValueError('explicit provider configuration is required')
    judge=OpenAICompatibleModel(api_key,base_url,model,timeout=timeout,retries=0)
    verifier=OpenAICompatibleModel(api_key,base_url,support_model or model,timeout=timeout,retries=0)
    return FeedbackEngine(AdvisoryJudge(judge,EvidenceSupportVerifier(verifier,input_bytes=input_bytes),input_bytes=input_bytes))
