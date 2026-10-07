"""Narrow source-level fallback, never a blanket exception handler."""
from career_lab.contracts.v2.core import ProtocolError

# These are source lookup/verification failures under a separately authorized
# session and subject. Credential, invariant and programming failures propagate.
SOURCE_CODES=frozenset({
    'not_found','object_not_found','object_scope_denied','source_not_visible',
    'source_unavailable','source_missing','historical_evidence_missing',
    'evidence_forbidden','source_time_unknown','future_evidence',
    'evidence_version_mismatch','evidence_quote_mismatch','evidence_time_mismatch',
})
ACTIVITY_CODES=frozenset({'activity_provenance_mismatch','activity_target_missing','activity_target_mismatch'})
SAFE_REASON='部分依据当前无法核验，该项保留待核验；其余已核验结果仍有效。'


def unavailable(error):
    # EvidenceReader explicitly specifies KeyError for a missing source.
    return isinstance(error,KeyError) or isinstance(error,ProtocolError) and error.code in SOURCE_CODES
