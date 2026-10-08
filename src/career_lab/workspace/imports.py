"""Preview/apply selected browser objects; imported runs remain provenance only."""
from datetime import datetime

from career_lab.contracts.v2.core import AuthContext, Command, ProtocolError, canonical, digest
from career_lab.contracts.v2.legacy import normalize_legacy_product
from career_lab.contracts.v2.workspace import (
    WorkspaceImport, ImportResult, ImportReference, WorkspaceTask, WorkProductVersion,
    TestPlanPayload, TestCase, Adoption, LegacyProvenance, InvestigationPayload, InvestigationBlock,
    ImportConflict, ImportVersionMap,
)
from .ports import Snapshot, Mutation
from .domain import stored, reference, _new_scope

# Explicit limits bound both historical writes and missing-version metadata.
# Large original revision labels are rejected, never silently renumbered/dropped.
MAX_SOURCE_REVISION = 1000
MAX_HISTORY_PER_ITEM = 200
MAX_HISTORY_ROWS = 2000
MAX_VERSION_SPAN = 5000
MAX_REFERENCES = 2000
MAX_EXPANDED_BYTES = 8_000_000

_SECRET_KEYS = {'token', 'authorization', 'sessiontoken', 'apikey', 'password', 'credential',
                'accesstoken', 'refreshtoken', 'secret', 'bearer', 'cookie'}


def reject_credentials(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k.lower().replace('_', '').replace('-', '') in _SECRET_KEYS:
                raise ProtocolError('credentials_not_importable')
            reject_credentials(v)
    elif isinstance(value, (list, tuple)):
        for v in value: reject_credentials(v)


def _inferred_references(item, source_session):
    """Do not interpret local config-version numbers as server test revisions."""
    ids = set()
    def remember(oid):
        if isinstance(oid,str):ids.add(oid)
        if len(ids)>MAX_REFERENCES:raise ProtocolError('import_reference_limit')
    raw = item.raw
    for ev in raw.get('evidence', []):
        if isinstance(ev, dict) and isinstance(ev.get('id'), str): remember(ev['id'])
    for row in raw.get('cases', []):
        if isinstance(row, dict):
            for ref in row.get('refs', []):
                if isinstance(ref, dict) and isinstance(ref.get('id'), str): remember(ref['id'])
    for block in raw.get('blocks', []):
        if not isinstance(block, dict): continue
        if isinstance(block.get('testId'), str): remember(block['testId'])
        for oid in block.get('testIds',[]):remember(oid)
        if isinstance(block.get('material'), dict) and isinstance(block['material'].get('id'), str):
            remember(block['material']['id'])
    return [ImportReference(original_id=oid, original_session_id=source_session,
                            status='unverified_local') for oid in sorted(ids)]


def _history(item):
    """Return only actual saved images. Missing source revisions stay missing."""
    raw=item.raw
    current=raw.get('revision',1)
    if not isinstance(current,int) or isinstance(current,bool) or current<1: raise ProtocolError('invalid_legacy_revision')
    if current>MAX_SOURCE_REVISION:raise ProtocolError('import_history_limit')
    events=raw.get('sourceHistory',[])
    if not isinstance(events,list):raise ProtocolError('invalid_legacy_history')
    if len(events)>MAX_HISTORY_PER_ITEM:raise ProtocolError('import_history_limit')
    images={}
    for event in events:
        if not isinstance(event,dict):raise ProtocolError('invalid_legacy_history')
        detail=event.get('detail')
        if detail is not None and not isinstance(detail,dict):raise ProtocolError('invalid_legacy_history')
        previous=detail.get('previous',event) if detail is not None else event
        if not isinstance(previous,dict):raise ProtocolError('invalid_legacy_history')
        revision=previous.get('revision')
        if not isinstance(revision,int) or isinstance(revision,bool) or not 0<revision<current:
            raise ProtocolError('invalid_legacy_history')
        if revision in images and digest(images[revision])!=digest(previous):raise ProtocolError('legacy_history_conflict')
        images[revision]=previous
    images[current]=raw
    return sorted(images.items())


def _legacy_structure(snapshot,auth,p,item,image,kind):
    """Keep legacy content; only link actual same-session authorized records.

    Unknown old references remain in legacy.raw and ImportResult.unresolved.
    Empty links never claim that a test ran or a source was read.
    """
    def test_ref(oid):
        if not isinstance(oid,str) or p.source_session_id!=auth.session_id:return None
        try:
            rec=snapshot.get('test',oid)
            if snapshot.reference_allowed(rec.ref):return rec.ref
        except ProtocolError as e:
            if e.status not in {403,404}:raise
        return None
    def source_ref(raw):
        if not isinstance(raw,dict) or p.source_session_id!=auth.session_id:return None
        for record in snapshot.heads('test'):
            for citation in record.content.get('citations',[]):
                if citation.get('object_id')==raw.get('id') and citation.get('version')==raw.get('version'):
                    from career_lab.contracts.v2.core import EvidenceRefV2
                    ref=EvidenceRefV2.model_validate(citation)
                    if snapshot.reference_allowed(ref):return ref
        return None
    if kind=='test_plan':
        rows=image.get('cases',[])
        if not isinstance(rows,list) or len(rows)>20:raise ProtocolError('invalid_legacy_cases')
        payload=TestPlanPayload(cases=tuple(TestCase(id=str(r['id']),revision=r.get('revision',1),query=r.get('question',''),
            intent=r.get('intent',''),declared_expected=r.get('expectation'),
            refs=tuple(ref for old in r.get('refs',[]) if (ref:=source_ref(old)) is not None)) for r in rows))
        if len({r.id for r in payload.cases})!=len(payload.cases):raise ProtocolError('duplicate_child_id')
        return payload
    if kind=='investigation':
        raw_blocks=image.get('blocks',[])
        if not isinstance(raw_blocks,list) or len(raw_blocks)>8:raise ProtocolError('invalid_legacy_blocks')
        blocks=[]
        for index,block in enumerate(raw_blocks):
            block_type=block.get('type')
            if block_type not in {'note','text','test_compare','source_check','retest'}:raise ProtocolError('invalid_legacy_block_type')
            blocks.append(InvestigationBlock(id=str(block.get('id') or digest([item.original_id,'legacy-block',index])),
                revision=block.get('revision',1),type=block_type,title=block.get('title',block.get('label','')),
                text=block.get('text',''),test_ref=test_ref(block.get('testId')),source_ref=source_ref(block.get('material')),
                test_refs=tuple(ref for oid in block.get('testIds',[]) if (ref:=test_ref(oid)) is not None)))
        if len({b.id for b in blocks})!=len(blocks):raise ProtocolError('duplicate_child_id')
        review=image.get('review') or {}
        return InvestigationPayload(question=image.get('question',''),blocks=tuple(blocks),
            review_note=review.get('note',''),review_focus=review.get('focus','uncertain'),review_direction='unknown')
    return None


def import_workspace(snapshot: Snapshot, auth: AuthContext, command: Command, now: datetime) -> Mutation:
    reject_credentials(command.payload)
    p = WorkspaceImport.model_validate(command.payload)
    _new_scope(auth)
    if command.operation != 'workspace_imports': raise ProtocolError('import_mode_mismatch')
    if not p.items or len(p.items) > 500 or len(canonical(p).encode()) > 2_000_000:
        raise ProtocolError('import_size')
    if len({i.original_id for i in p.items}) != len(p.items): raise ProtocolError('duplicate_import_id')
    if any(i.raw.get('id') != i.original_id for i in p.items): raise ProtocolError('import_identity_mismatch')
    if any(i.source_schema != p.source_schema or i.source_session_id != p.source_session_id for i in p.items):
        raise ProtocolError('import_source_mismatch')
    import_id = digest([auth.session_id, 'workspace_import', p.package_id])
    fingerprint = digest(p.model_dump(mode='json', exclude={'mode', 'preview_storage_revision'}))
    try:
        prior = snapshot.get('workspace_import', import_id)
    except ProtocolError as error:
        if error.code != 'not_found': raise
    else:
        if prior.content['fingerprint'] != fingerprint: raise ProtocolError('import_package_conflict', status=409)
        result = ImportResult.model_validate(prior.content['result'])
        return Mutation((), result.model_copy(update={'mode': p.mode}).model_dump(mode='json'), command.operation)
    if p.mode == 'apply' and p.preview_storage_revision != snapshot.state.storage_revision:
        raise ProtocolError('import_preview_stale', status=409)
    histories={};span=0;rows=0
    for item in p.items:
        if item.original_kind=='task':continue
        images=_history(item);histories[item.original_id]=images
        span+=images[-1][0];rows+=len(images)
        if span>MAX_VERSION_SPAN or rows>MAX_HISTORY_ROWS:raise ProtocolError('import_history_limit')
    tasks = {i.original_id: i for i in p.items if i.original_kind == 'task'}
    id_map = {i.original_id: reference(snapshot, 'task' if i.original_id in tasks else 'product',
              digest([auth.session_id, p.package_id, i.original_id]), 1) for i in p.items}
    unresolved = {};resolved={};references={}
    for r in p.references:
        key=(r.original_session_id,r.original_id)
        if key in references and references[key]!=r:raise ProtocolError('conflicting_import_reference')
        references[key]=r
        if len(references)>MAX_REFERENCES:raise ProtocolError('import_reference_limit')
    for item in p.items:
        for r in _inferred_references(item,p.source_session_id):
            # Explicit records are authoritative after validation below. An
            # inferred placeholder must not recreate an already-resolved source.
            references.setdefault((r.original_session_id,r.original_id),r)
            if len(references)>MAX_REFERENCES:raise ProtocolError('import_reference_limit')
    for key,r in references.items():
        if r.original_session_id != auth.session_id:
            fixed = r.model_copy(update={'status': 'foreign_session', 'resolved': None})
        elif r.resolved is not None:
            if (r.resolved.session_id != auth.session_id or r.resolved.object_id != r.original_id
                    or not snapshot.reference_allowed(r.resolved)):
                raise ProtocolError('unverified_import_resolution')
            resolved[key]=r.resolved
            continue
        else:
            fixed = r.model_copy(update={'status': 'unverified_local', 'resolved': None})
        unresolved[key] = fixed
    writes = [];conflicts=[];version_map=[];expanded=0
    def append_write(record):
        nonlocal expanded
        expanded+=len(canonical(record).encode())
        if expanded>MAX_EXPANDED_BYTES:raise ProtocolError('import_expansion_limit')
        writes.append(record)
    for item in p.items:
        raw = item.raw; ref = id_map[item.original_id]
        if item.original_kind == 'task':
            if not isinstance(raw.get('title'), str) or not raw['title'].strip() or len(raw['title']) > 120:
                raise ProtocolError('invalid_legacy_task')
            priority = {'first': 0, 'next': 1, 'later': 2}.get(raw.get('priority'), 1)
            status = {'open':'open','working':'active','done':'done','paused':'paused','blocked':'blocked','removed':'removed'}.get(raw.get('status'), 'open')
            model = WorkspaceTask(id=ref.object_id, session_id=auth.session_id, revision=1,
                title=raw['title'], goal=str(raw.get('note', '')), priority=priority,
                order=list(tasks).index(item.original_id), status=status, created_at=now, updated_at=now)
            append_write(stored(snapshot, 'task', ref.object_id, 1, model))
            # Task contract has no provenance slot. Keep the exact sanitized
            # source as a separate private object, never fabricate task history.
            append_write(stored(snapshot, 'legacy_task', ref.object_id, 1, item))
            continue
        mapped = normalize_legacy_product(raw, p.source_session_id, p.source_schema)
        if mapped.source.original_id != item.original_id or mapped.source.original_hash != item.original_hash:
            raise ProtocolError('import_identity_mismatch')
        task = id_map.get(raw.get('taskId')) or resolved.get((p.source_session_id,str(raw.get('taskId'))))
        if task and task.kind != 'task': raise ProtocolError('invalid_task_mapping')
        if raw.get('taskId') and task is None:
            lost = ImportReference(original_id=str(raw['taskId']), original_session_id=p.source_session_id, status='missing')
            unresolved[(lost.original_session_id, lost.original_id)] = lost
        images=histories[item.original_id]
        found_versions={version for version,_ in images}
        for missing_version in sorted(set(range(1,max(found_versions)+1))-found_versions):
            conflicts.append(ImportConflict(original_id=item.original_id,original_version=missing_version,reason='missing_history'))
            version_map.append(ImportVersionMap(original_session_id=p.source_session_id,original_id=item.original_id,
                original_version=missing_version,target=None,status='unresolved'))
        for version,(source_revision,image) in enumerate(images,1):
            image_kind=normalize_legacy_product({**image,'id':item.original_id,'kind':image.get('kind',raw.get('kind','text'))},p.source_session_id,p.source_schema)
            structure=_legacy_structure(snapshot,auth,p,item,image,image_kind.kind)
            content=image.get('body','')
            if not isinstance(content,str) or len(content)>50000:raise ProtocolError('invalid_legacy_content')
            provenance=item if version==len(images) else LegacyProvenance(
                source_schema=p.source_schema,source_session_id=p.source_session_id,
                original_id=item.original_id,original_kind=image_kind.source.original_kind,
                original_purpose=image.get('purpose'),raw=image,original_hash=digest(image))
            model=WorkProductVersion(product_id=ref.object_id,session_id=auth.session_id,version=version,
                cycle=reference(snapshot,'cycle',snapshot.state.cycle_id,1),task=task if version==len(images) else None,
                kind=image_kind.kind,purpose=image_kind.purpose,title=str(image.get('title','')),
                content=content,structured_payload=structure,author=auth.executor,executor=auth.executor,
                source_return_id=raw.get('returnId'),adoption=Adoption(),removed_at=now if image.get('removedAt') else None,
                content_hash=digest({'content':content,'structured_payload':structure.model_dump(mode='json') if structure else None}),
                created_at=now,legacy=provenance)
            append_write(stored(snapshot,'product',ref.object_id,version,model))
            alias=item.original_id+'@v'+str(source_revision)
            if alias in id_map:raise ProtocolError('import_id_alias_conflict')
            id_map[alias]=reference(snapshot,'product',ref.object_id,version)
            version_map.append(ImportVersionMap(original_session_id=p.source_session_id,original_id=item.original_id,
                original_version=source_revision,target=id_map[alias],status='unverified_local'))
        id_map[item.original_id]=reference(snapshot,'product',ref.object_id,len(images))
    for unresolved_ref in unresolved.values():
        conflicts.append(ImportConflict(original_id=unresolved_ref.original_id,
            reason='foreign_session' if unresolved_ref.status=='foreign_session' else 'unresolved_reference'))
    point = snapshot.point if p.mode == 'preview' else snapshot.next_point
    result = ImportResult(package_id=p.package_id, mode=p.mode, id_map=id_map,
        unresolved=tuple(unresolved.values()), as_of=point, applied=p.mode=='apply',conflicts=tuple(conflicts),version_map=tuple(version_map))
    if expanded+len(canonical(result).encode())>MAX_EXPANDED_BYTES:raise ProtocolError('import_expansion_limit')
    if p.mode == 'preview': return Mutation((), result.model_dump(mode='json'), command.operation)
    append_write(stored(snapshot,'workspace_import',import_id,1,
                         {'fingerprint':fingerprint,'result':result.model_dump(mode='json')}))
    return Mutation(tuple(writes), result.model_dump(mode='json'), command.operation)
