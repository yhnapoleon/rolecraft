"""Version-two protocol primitives. Version-one classes remain untouched."""
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
import hashlib
import json

from pydantic import AfterValidator, Field, JsonValue, model_validator
from career_lab.contracts.base import Contract, Identifier, NonNegativeInt, PositiveInt

Hash = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]

def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone required')
    return value

Timestamp = Annotated[datetime, AfterValidator(aware)]

class V2(Contract):
    schema_version: Literal[2] = 2

class ProtocolError(ValueError):
    def __init__(self, code: str, message: str | None = None, status: int = 422):
        self.code, self.status = code, status
        super().__init__(message or code.replace('_', ' '))

def canonical(value) -> str:
    """Typed defaults are materialized; mapping keys sorted, array order preserved."""
    if isinstance(value, Contract):
        value = value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

class FileRef(V2):
    path: Identifier
    sha256: Hash
    media_type: str = 'application/json'
    @model_validator(mode='after')
    def relative(self):
        p = PurePosixPath(self.path)
        if p.is_absolute() or '..' in p.parts or '\\' in self.path or ':' in self.path or self.path in {'.', ''}:
            raise ValueError('file reference must be a portable relative path')
        return self

def read_file(root: Path, ref: FileRef) -> bytes:
    root = root.resolve()
    p = (root / ref.path).resolve()
    if not p.is_relative_to(root):
        raise ProtocolError('file_outside_root', status=403)
    if not p.is_file():
        raise ProtocolError('file_missing', status=503)
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ProtocolError('file_hash_mismatch', status=409)
    return raw

class ObjectRef(V2):
    session_id: Identifier
    kind: Identifier
    object_id: Identifier
    version: PositiveInt
    config_version: NonNegativeInt | None = None
    @model_validator(mode='after')
    def config(self):
        if (self.kind == 'config') != (self.config_version is not None):
            raise ValueError('config references require config_version; other kinds prohibit it')
        return self

class EvidenceRefV2(ObjectRef):
    span_start: NonNegativeInt | None = None
    span_end: NonNegativeInt | None = None
    quote: str | None = None
    observed_at_seq: NonNegativeInt
    valid_from_seq: NonNegativeInt = 0
    valid_until_seq: NonNegativeInt | None = None
    @model_validator(mode='after')
    def spans(self):
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError('span endpoints must occur together')
        if self.span_start is not None and (self.span_end <= self.span_start or self.quote is None):
            raise ValueError('span requires nonempty range and quote')
        if self.valid_until_seq is not None and self.valid_until_seq < self.valid_from_seq:
            raise ValueError('invalid validity interval')
        return self

class Executor(V2):
    id: Identifier
    kind: Literal['human', 'external_agent', 'reference_agent', 'system']
    delegation_id: Identifier | None = None

class AuthContext(V2):
    session_id: Identifier
    actor_id: Identifier
    executor: Executor
    capabilities: tuple[Literal['read', 'act', 'submit', 'approve', 'delegate', 'research'], ...]
    allowed_actions: tuple[str, ...] | None = None
    allowed_objects: tuple[str, ...] | None = None
    create_under_tasks: tuple[str,...] = ()
    expires_at: Timestamp | None = None
    credential_id: Identifier

class DelegationGrant(V2):
    id: Identifier
    session_id: Identifier
    actor_id: Identifier
    executor: Executor
    capabilities: tuple[Literal['read', 'act', 'submit'], ...] = ('read',)
    allowed_actions: tuple[str, ...] | None = None
    allowed_objects: tuple[str, ...] | None = None
    create_under_tasks: tuple[str,...] = ()
    expires_at: Timestamp
    revoked: bool = False

class VersionPoint(V2):
    business_seq: NonNegativeInt
    workspace_revision: NonNegativeInt
    storage_revision: NonNegativeInt

class Command(V2):
    schema_version: Literal[2]
    request_id: Identifier
    expected_version: NonNegativeInt
    expected_workspace_revision: NonNegativeInt
    operation: Identifier
    payload: dict[str, JsonValue] = {}

class PageRequest(V2):
    cursor: NonNegativeInt = 0
    limit: Annotated[int, Field(ge=1, le=100)] = 50

class ErrorResponse(V2):
    code: Identifier
    message: str
    retryable: bool = False
    next_action: str | None = None

class ObjectRead(V2):
    ref: ObjectRef
    as_of: VersionPoint | None = None

class SourceIdentity(V2):
    base_commit: Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
    source_digest: Hash
    overlay: FileRef | None = None
    dependency_locks: tuple[FileRef, ...] = ()

class Budget(V2):
    model_calls: NonNegativeInt
    tokens: NonNegativeInt | None = None
    actions: NonNegativeInt
    wall_seconds: Annotated[float, Field(gt=0)]
    currency_limit: Annotated[float, Field(ge=0)] | None = None

class ModelAttemptUsage(V2):
    request_id: Identifier
    attempt_id: Identifier
    expected_provider: Identifier | None = None
    expected_model_revision: Identifier | None = None
    provider: Identifier | None
    model_revision: Identifier | None
    status: Literal['success', 'failed', 'timeout', 'unknown']
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cost: Annotated[float, Field(ge=0)] | None = None
    elapsed_seconds: Annotated[float, Field(ge=0)]
    usage_known: bool
    @model_validator(mode='after')
    def usage(self):
        if self.usage_known and (self.input_tokens is None or self.output_tokens is None):
            raise ValueError('known usage requires token counts')
        return self


class ActualConsumption(V2):
    model_attempt_count: NonNegativeInt = 0
    actions: NonNegativeInt = 0
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cost: Annotated[float,Field(ge=0)] | None = None
    wall_seconds: Annotated[float,Field(ge=0)] = 0
    usage_complete: bool = False
    cost_complete: bool = False


class ExternalReference(V2):
    """Immutable scenario-file reference; authorization is rechecked by the provider."""
    ref: ObjectRef
    source: FileRef
    content_hash: Hash
