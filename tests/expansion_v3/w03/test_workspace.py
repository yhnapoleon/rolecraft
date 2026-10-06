from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from sqlalchemy import select,func

from career_lab.contracts.v2.core import ObjectRef,ProtocolError,PageRequest,digest,Executor
from career_lab.contracts.v2.workspace import WorkProductVersion
from career_lab.storage.workspace_v2 import versions,requests,audits
from career_lab.workspace.service import create_service
from conftest import command,do,product,edit_payload
from conftest import test_states
from sqlalchemy import update


def counts(env):
    with env['engine'].connect() as conn:
        return tuple(conn.execute(select(func.count()).select_from(t)).scalar_one() for t in (versions,requests,audits))


def role(env,name): return env['auth'].model_copy(update={'actor_id':name,'capabilities':('read',),'credential_id':name})


def test_private_edits_are_immutable_and_do_not_change_business(env):
    original=product(env); old_hash=digest(original)
    newer=do(env,'work_products.edit',edit_payload(original,content='补充依据后再判断'))['object']
    assert newer['version']==2 and newer['purpose']=='未知用途'
    assert digest(env['service'].get_product(env['auth'],original['product_id'],1))==old_hash
    for who in ['tech_lead','supervisor','business_lead']:
        assert env['service'].list(role(env,who),'product',PageRequest())['items']==[]
        with pytest.raises(ProtocolError,match='not found'):env['service'].get_product(role(env,who),original['product_id'])
    with env['engine'].connect() as conn:
        state=env['authority'].state(conn,env['auth'],lock=False)
    assert (state.business_seq,state.resources,state.applied_milestones,state.status)==(7,{'capacity':30,'dev_days':3},('initial_plan_applied',),'active')
    assert (state.workspace_revision,state.storage_revision)==(2,12)


def test_exact_share_revoke_remove_restore_preserves_history(env):
    p=product(env)
    shared=do(env,'work_products.shares.create',{'product_id':p['product_id'],'product_version':1,'recipient_role':'tech_lead'})['object']
    v2=do(env,'work_products.edit',edit_payload(p,content='未分享的新版本'))['object']
    assert env['service'].get_product(role(env,'tech_lead'),p['product_id'])['version']==1
    for who in ['supervisor','business_lead']:
        with pytest.raises(ProtocolError):env['service'].get_product(role(env,who),p['product_id'],1)
    with pytest.raises(ProtocolError):env['service'].get_product(role(env,'tech_lead'),p['product_id'],2)
    old_version=env['service'].get_product(env['auth'],p['product_id'],1)
    revoked=do(env,'work_products.shares.update',{'product_id':p['product_id'],'share_id':shared['id'],'expected_revision':1,'operation':'revoke'})['object']
    with pytest.raises(ProtocolError):env['service'].get_product(role(env,'tech_lead'),p['product_id'],1)
    do(env,'work_products.shares.update',{'product_id':p['product_id'],'share_id':shared['id'],'expected_revision':2,'operation':'restore'})
    removed=do(env,'work_products.edit',edit_payload(v2,removed=True))['object']
    with pytest.raises(ProtocolError):env['service'].get_product(role(env,'tech_lead'),p['product_id'],1)
    restored=do(env,'work_products.edit',edit_payload(removed,removed=False))['object']
    assert restored['version']==4 and env['service'].get_product(role(env,'tech_lead'),p['product_id'])['version']==1
    assert env['service'].get_product(env['auth'],p['product_id'],1)==old_version
    assert revoked['revoked_at']['storage_revision']>shared['shared_at']['storage_revision']


def test_task_order_parent_merge_relations_remove_and_cycle(env):
    a=do(env,'work_items.create',{'title':'先试用','priority':2,'order':4})
    b=do(env,'work_items.create',{'title':'调查子事项','parent':a['ref']})
    unchanged=do(env,'work_items.patch',{'item_id':b['object']['id'],'expected_revision':1,'parent':None,'goal':'补充问题'})
    assert unchanged['object']['parent']==a['ref']
    merged=do(env,'work_items.create',{'title':'合并处理的事项','relations':[a['ref'],b['ref']],'priority':0})
    do(env,'work_items.patch',{'item_id':a['object']['id'],'expected_revision':1,'status':'blocked','priority':0,'order':-1})
    ordered=env['service'].list(env['auth'],'task',PageRequest())['items']
    assert ordered[0]['id']==a['object']['id'] and ordered[0]['status']=='blocked'
    with pytest.raises(ProtocolError,match='task cycle'):
        do(env,'work_items.patch',{'item_id':a['object']['id'],'expected_revision':2,'parent':b['ref']})
    child=do(env,'work_items.patch',{'item_id':b['object']['id'],'expected_revision':2,'clear_parent':True,'status':'removed'})['object']
    restored=do(env,'work_items.patch',{'item_id':child['id'],'expected_revision':3,'status':'paused'})['object']
    assert restored['parent'] is None and restored['status']=='paused'
    assert len(merged['object']['relations'])==2


def test_concurrent_writers_conflict_and_duplicate_replays_after_restart(env):
    p=product(env)
    a=command(env,'work_products.edit',edit_payload(p,content='甲'),request_id='a')
    b=command(env,'work_products.edit',edit_payload(p,content='乙'),request_id='b')
    def submit(cmd):
        try:return env['service'].execute(env['auth'],cmd)
        except ProtocolError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(submit,[a,b]))
    assert sum(isinstance(x,dict) for x in results)==1
    assert 'version_conflict' in results
    winner=a if isinstance(results[0],dict) else b
    before=counts(env)
    restarted=create_service(env['engine'],env['authority'])
    assert restarted.execute(env['auth'],winner)==next(x for x in results if isinstance(x,dict))
    assert counts(env)==before
    with pytest.raises(ProtocolError,match='request id reused'):
        restarted.execute(env['auth'],winner.model_copy(update={'payload':edit_payload(p,content='conflict')}))


def test_atomic_rollback_of_all_writes_authority_and_request(env):
    before=counts(env);env['authority'].fail_after_advance=True
    cmd=command(env,'work_products.create',{'kind':'text','content':'不丢原文'})
    with pytest.raises(RuntimeError):env['service'].execute(env['auth'],cmd)
    assert counts(env)==before
    with env['engine'].connect() as c:assert env['authority'].state(c,env['auth'],lock=False).workspace_revision==0
    env['authority'].fail_after_advance=False
    result=env['service'].execute(env['auth'],cmd)
    assert result['object']['content']=='不丢原文' and counts(env)==(1,1,1)


def test_role_and_delegate_authority_rechecked_on_replay(env):
    cmd=command(env,'work_products.create',{'kind':'text','content':'secret'})
    env['service'].execute(env['auth'],cmd)
    env['authority'].revoked.add('trusted-human')
    with pytest.raises(ProtocolError,match='credential revoked'):env['service'].execute(env['auth'],cmd)
    env['authority'].revoked.clear()
    for auth in [role(env,'tech_lead'),env['auth'].model_copy(update={'capabilities':('read',)}),
                 env['auth'].model_copy(update={'allowed_actions':('work_items.create',)})]:
        with pytest.raises(ProtocolError):env['service'].execute(auth,cmd)
    assert counts(env)==(1,1,1)


def test_cross_session_scopes_and_future_reference_fail_without_leak(env):
    p=product(env); foreign=env['auth'].model_copy(update={'session_id':'other'})
    with pytest.raises(ProtocolError) as e:env['service'].get_product(foreign,p['product_id'])
    assert e.value.status==404 and p['title'] not in str(e.value)
    limited=env['auth'].model_copy(update={'allowed_objects':()})
    assert env['service'].list(limited,'product',PageRequest())['items']==[]
    ref={'session_id':'other','kind':'test','object_id':'private-test','version':1,'observed_at_seq':2}
    with pytest.raises(ProtocolError):product(env,evidence_refs=[ref])
    ref.update(session_id='s',observed_at_seq=8)
    with pytest.raises(ProtocolError,match='future reference'):product(env,evidence_refs=[ref])


def test_equivalent_text_and_template_preserved_and_author_not_rewritten(env):
    p=product(env,kind='options',content='A成本低，B更新快',structured_payload={'type':'options','options':[{'id':'a','title':'A','rationale':'成本低'},{'id':'b','title':'B','rationale':'更新快'}]})
    plain=product(env,content=p['content'])
    assert plain['content']==p['content'] and p['structured_payload']['options'][1]['title']=='B'
    agent=env['auth'].model_copy(update={'executor':Executor(id='external-1',kind='external_agent',delegation_id='d'),'credential_id':'agent-token'})
    candidate=do(env,'work_products.create',{'kind':'text','content':'Agent候选'},auth=agent)['object']
    adopted=do(env,'work_products.adopt',edit_payload(candidate))['object']
    assert adopted['author']['kind']=='external_agent' and adopted['executor']['kind']=='human'
    assert adopted['adoption']['status']=='adopted' and candidate['adoption']['status']=='unadopted'
    WorkProductVersion.model_validate(adopted)


def test_pagination_filters_first_and_returns_no_private_counts(env):
    for i in range(3):product(env,title=str(i))
    page=env['service'].list(env['auth'],'product',PageRequest(limit=2))
    assert len(page['items'])==2 and page['next_cursor']==2
    assert len(env['service'].list(env['auth'],'product',PageRequest(cursor=2,limit=2))['items'])==1
    assert env['service'].list(role(env,'tech_lead'),'product',PageRequest(limit=2))['next_cursor'] is None


def test_typed_defaults_and_concurrent_duplicate_request(env):
    cmd=command(env,'work_products.create',{'kind':'text','content':'草稿'},request_id='typed')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:env['service'].execute(env['auth'],cmd),range(2)))
    assert results[0]==results[1] and counts(env)==(1,1,1)
    from career_lab.contracts.v2.requests import ProductCreate
    explicit=cmd.model_copy(update={'payload':ProductCreate.model_validate(cmd.payload).model_dump(mode='json')})
    assert env['service'].execute(env['auth'],explicit)==results[0]


@pytest.mark.parametrize('status',['paused','submitted'])
def test_terminal_session_rejects_new_writes_but_prior_request_replays(env,status):
    cmd=command(env,'work_products.create',{'kind':'text','content':'已保存'})
    first=env['service'].execute(env['auth'],cmd)
    with env['engine'].begin() as conn:
        state=env['authority'].state(conn,env['auth'],lock=False).model_copy(update={'status':status})
        conn.execute(update(test_states).where(test_states.c.id=='s').values(state=state.model_dump_json()))
    assert env['service'].execute(env['auth'],cmd)==first
    with pytest.raises(ProtocolError,match='session '+status):product(env)
    assert counts(env)==(1,1,1)


def test_child_ids_and_revisions_are_assigned_by_service(env):
    p=product(env,kind='test_plan',structured_payload={'type':'test_plan','cases':[{'id':'client-id','revision':99,'query':'问题'}]})
    row=p['structured_payload']['cases'][0]
    assert row['id']!='client-id' and row['revision']==1
    changed={**p['structured_payload'],'cases':[{**row,'query':'新问题','revision':77}]}
    newer=do(env,'work_products.edit',edit_payload(p,structured_payload=changed))['object']
    newrow=newer['structured_payload']['cases'][0]
    assert newrow['id']==row['id'] and newrow['revision']==2
    again=do(env,'work_products.edit',edit_payload(newer,title='只改标题'))['object']
    assert again['structured_payload']['cases'][0]['revision']==2


def test_external_agent_cannot_supply_or_clear_human_judgment(env):
    p=product(env,kind='investigation',structured_payload={'type':'investigation','question':'需要核查什么','review_note':'用户的判断','review_direction':'mixed'})
    agent=env['auth'].model_copy(update={'executor':Executor(id='a',kind='external_agent'),'credential_id':'agent'})
    with pytest.raises(ProtocolError,match='human judgment only'):
        do(env,'work_products.edit',edit_payload(p,structured_payload=None),auth=agent)
    q=product(env,kind='investigation',structured_payload=None)
    with pytest.raises(ProtocolError,match='human judgment only'):
        do(env,'work_products.edit',edit_payload(q,structured_payload={'type':'investigation','review_note':'冒充用户'}),auth=agent)


def test_sharing_does_not_bypass_source_quote_visibility(env):
    env['authority'].references.add(('document','source',1))
    p=product(env,evidence_refs=[{'session_id':'s','kind':'document','object_id':'source','version':1,'observed_at_seq':7,'quote':'仅本人可读原文'}])
    do(env,'work_products.shares.create',{'product_id':p['product_id'],'product_version':1,'recipient_role':'tech_lead'})
    env['authority'].references.clear()
    with pytest.raises(ProtocolError,match='not found'):env['service'].get_product(role(env,'tech_lead'),p['product_id'])
    assert env['service'].list(role(env,'tech_lead'),'product',PageRequest())['items']==[]
