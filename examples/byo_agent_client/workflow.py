"""Persist exact business commands before sending; resume without new effect keys."""
import json,os
from pathlib import Path
from uuid import uuid4
from career_lab.delegations.credentials import load_credentials
from career_lab.delegations.http_client import HttpAgentClient,RemoteFailure
from career_lab.contracts import v2 as C


def save(path,value):
    temporary=path.with_name(path.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    except BaseException:
        raise
    os.replace(temporary,path)


def run(config_path,journal_path,*,config_version,query='Which source supports this draft?'):
    credentials=load_credentials(config_path);client=HttpAgentClient(config_path);path=Path(journal_path)
    if path.exists():
        record=json.loads(path.read_text())
        if record.get('session_id')!=credentials.session_id or record.get('schema_version')!=1:raise ValueError('journal identity mismatch')
    else:
        observation=client.observation(credentials.session_id)
        if not observation.visible_sources:raise ValueError('Human investigation required before this example')
        record={'schema_version':1,'session_id':credentials.session_id,'client':'w06-no-model-example','provider':None,'model':None,'steps':[],
            'draft':'Source notes (unreviewed Agent draft):\n'+'\n'.join(x.text for x in observation.visible_sources),'query':query,'config_version':config_version}
        save(path,record)
    operations=('work_products.create','tests.create')
    for index,name in enumerate(operations):
        if len(record['steps'])<=index:
            observation=client.observation(credentials.session_id)
            tool=next((t for t in observation.tools if t.name==name and t.available),None)
            if tool is None:raise RemoteFailure('example_tool_unavailable',503)
            if name=='work_products.create':payload={'kind':'text','title':'Agent source notes','content':record['draft']}
            else:
                # Fixed example config version is explicit user setup, never a
                # guessed production version: the human must supply the config.
                payload={'query':record['query'],'config_version':record['config_version']}
            command=C.Command(schema_version=2,request_id=uuid4().hex,expected_version=observation.as_of.business_seq,
                expected_workspace_revision=observation.as_of.workspace_revision,operation=name,payload=payload)
            record['steps'].append({'name':name,'command':command.model_dump(mode='json'),'status':'unconfirmed'});save(path,record)
        step=record['steps'][index]
        if step['status']=='completed':continue
        try:
            recovered=client.call('requests.read',{'session_id':credentials.session_id,'query':{'request_id':step['command']['request_id']}})
            result=recovered['response']
        except RemoteFailure as error:
            if error.status!=404:raise
            result=client.call(name,{'session_id':credentials.session_id,'command':step['command']})
        step.update(status='completed',result=result);save(path,record)
    return record
