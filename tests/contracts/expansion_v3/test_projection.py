from datetime import datetime,timezone
import pytest
from career_lab.contracts.v2 import *
from career_lab.contracts.v2.projection import project_fragments,verify_disclosure_quotes
from career_lab.storage.v2_store import *
from career_lab.storage.v2_lifecycle import point
from .conftest import command,product_plan

@pytest.mark.parametrize('channel',['fact','material','memory','attachment','event','error','export'])
def test_disclosure_filters_all_channels_and_quotes(channel):
    ref=EvidenceRefV2(session_id='s',kind='document',object_id='secret',version=1,observed_at_seq=0,span_start=0,span_end=6,quote='SECRET')
    raw=SourceFragment(ref=ref,text='SECRET',channel=channel,disclosure=DisclosurePolicy(mode='never'),fact_ids=('hidden',))
    assert project_fragments((raw,),'tech_lead',0)==()
    paraphrase=raw.model_copy(update={'disclosure':DisclosurePolicy(mode='paraphrase_only',actors=('learner',),paraphrase='仍需核验')})
    result=project_fragments((paraphrase,),'learner',0)
    assert 'SECRET' not in result[0].model_dump_json() and result[0].ref.quote is None
    assert project_fragments((raw.model_copy(update={'disclosure':DisclosurePolicy(mode='role_only',actors=('tech_lead',))}),),'learner',0)==()
    assert project_fragments((paraphrase.model_copy(update={'ref':ref.model_copy(update={'observed_at_seq':2})}),),'learner',0)==()
    record=DisclosureRecord(fact_id='fact',source=ref,reply_ref=ObjectRef(session_id='s',kind='turn',object_id='t',version=1),quote='披露内容',verification='model_extracted')
    with pytest.raises(ProtocolError):verify_disclosure_quotes('我还没有说出该信息',(record,))
    assert verify_disclosure_quotes('实际披露内容',(record,))[0].verification=='model_extracted'

def test_share_exact_version_and_revocation_do_not_rewrite_past(foundation):
    store,auth,*_=foundation;first=store.execute(auth,command(store.view(auth)),product_plan);product=first.objects[0]
    role=store.role_reader(auth.session_id,'tech_lead')
    with pytest.raises(ProtocolError):store.read(role,product)
    share=ProductShare(id='share',session_id=auth.session_id,version=1,product=product,recipient_role='tech_lead',shared_at=point(first.state))
    ref=ObjectRef(session_id=auth.session_id,kind='share',object_id='share',version=1)
    def save(v,c,a):return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=share.model_dump(mode='json'),visible_to=('learner','tech_lead'),dependencies=(product,)),))
    saved=store.execute(auth,command(store.view(auth),'share'),save)
    assert store.read_shared_product(role,ref).ref==product
    updated=store.execute(auth,command(store.view(auth),'edit'),lambda v,c,a:product_plan(v,c,a,expected_head=1))
    assert store.read_shared_product(role,ref).ref.version==1
    revoked=ProductShare.model_validate(share.model_dump(mode='json')|{'version':2,'revoked_at':point(updated.state).model_dump(mode='json')})
    revref=ref.model_copy(update={'version':2})
    store.execute(auth,command(store.view(auth),'revoke'),lambda v,c,a:Mutation(writes=(ObjectWrite(ref=revref,expected_head=1,content=revoked.model_dump(mode='json'),visible_to=('learner','tech_lead'),dependencies=(product,)),)))
    with pytest.raises(ProtocolError):store.read_shared_product(role,ref)
    assert store.read(auth,ref).content==share.model_dump(mode='json')
    assert store.read(auth,product).ref.version==1

# Imported protocol models are not pytest test classes.
globals().pop('TestRequestV2', None)
globals().pop('TestResultV2', None)
globals().pop('TestCase', None)
globals().pop('TestPlanPayload', None)
globals().pop('TestCampaign', None)

globals().pop('TestExecutionMetadata', None)
