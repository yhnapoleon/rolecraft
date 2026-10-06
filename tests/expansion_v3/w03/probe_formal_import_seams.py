"""Read-only-to-input probe of the frozen core; uses a fresh synthetic SQLite DB.

Results name integration gaps, not passed W03 product acceptance.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

from career_lab.contracts.v2 import (
    AssistantConfig, SessionBindings, FileRef, Command, ObjectRef,
    WorkspaceTask, WorkProductVersion, LegacyProvenance, ProtocolError, digest,
)
from career_lab.storage.v2_store import V2Store, ObjectWrite, Mutation, references


def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    db=output/'probe.db'
    if db.exists():raise RuntimeError('Use a new probe output directory')
    store=V2Store(f'sqlite:///{db}')
    file=FileRef(path='synthetic.json',sha256='1'*64)
    state,token=store.create_session(SessionBindings(scenario=file,runtime=file,evaluation=file),
        AssistantConfig(id='config',session_id='fixture',domains=('stable_faq',)),{'capacity':30})
    auth=store.authenticate(state.session_id,token);now=datetime.now(timezone.utc);results=[]
    def ref(kind,oid,version):return ObjectRef(session_id=state.session_id,kind=kind,object_id=oid,version=version)
    def probe(name,writes):
        current=store.view(auth).state
        cmd=Command(schema_version=2,request_id=name,expected_version=current.business_seq,expected_workspace_revision=current.workspace_revision,operation='work_items.batch',payload={})
        try:
            store.execute(auth,cmd,lambda *args:Mutation(writes=tuple(writes)))
            result={'probe':name,'outcome':'committed'}
        except ProtocolError as error:result={'probe':name,'outcome':'rejected','code':error.code}
        results.append(result)
    first=WorkspaceTask(id='task',session_id=state.session_id,title='history1',revision=1,created_at=now,updated_at=now)
    second=first.model_copy(update={'title':'history2','revision':2})
    probe('multiple_versions_one_transaction',[
        ObjectWrite(ref=ref('task','task',1),expected_head=0,content=first.model_dump(mode='json')),
        ObjectWrite(ref=ref('task','task',2),expected_head=1,content=second.model_dump(mode='json'))])
    raw={'id':'old-work','opaque_data':{'session_id':'original-session','kind':'test','object_id':'original-test','version':1}}
    legacy=LegacyProvenance(source_schema='browser-v1',source_session_id='original-session',original_id='old-work',original_kind='text',raw=raw,original_hash=digest(raw))
    product=WorkProductVersion(product_id='product',session_id=state.session_id,version=1,
        cycle=ref('cycle',state.cycle_id,1),author=auth.executor,executor=auth.executor,created_at=now,
        content='original text',content_hash=digest({'content':'original text','structured_payload':None}),legacy=legacy)
    content=product.model_dump(mode='json')
    probe('inert_legacy_json_shaped_like_reference',[
        ObjectWrite(ref=ref('product','product',1),expected_head=0,content=content,dependencies=references(content))])
    results.append({'probe':'import_receipt_kinds','registered':{k:k in store.object_models for k in ['legacy_task','workspace_import']}})
    store.db.engine.dispose()
    (output/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main(sys.argv[1])
