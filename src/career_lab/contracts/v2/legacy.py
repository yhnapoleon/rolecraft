"""Lossless browser import vocabulary. No pending action/test is executed here."""
from pydantic import JsonValue
from .core import *
from .workspace import LegacyProvenance

PURPOSE_MAP={'探索笔记':'exploration','测试计划':'test_plan','方案比较':'comparison','试点决定':'commitment','自由作品':'freeform'}
KIND_MAP={'text':'text','test_set':'test_plan','investigation':'investigation'}
class LegacyProductImport(V2):
    kind: Literal['text','test_plan','investigation']
    purpose: str
    source: LegacyProvenance
    run_verification: Literal['unverified_local'] = 'unverified_local'
    execute_pending: Literal[False] = False

def normalize_legacy_product(raw:dict,source_session_id:str,source_schema='browser-v1'):
    kind=raw.get('kind','text')
    if kind not in KIND_MAP:raise ProtocolError('legacy_kind_unsupported')
    original=LegacyProvenance(source_schema=source_schema,source_session_id=source_session_id,original_id=raw['id'],original_kind=kind,original_purpose=raw.get('purpose'),raw=raw,original_hash=digest(raw))
    return LegacyProductImport(kind=KIND_MAP[kind],purpose=PURPOSE_MAP.get(raw.get('purpose'),raw.get('purpose','freeform')),source=original)

def restore_legacy_product(imported:LegacyProductImport):
    original=LegacyProvenance.model_validate(imported.source.model_dump(mode='json'))
    return original.raw
