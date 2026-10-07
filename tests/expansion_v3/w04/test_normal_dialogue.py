"""User-directed Chinese vertical slice: ordinary work language stays usable."""
import json
import pytest
from career_lab.runtime.context_v2 import assemble_context,role_text
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.contracts.v2 import TurnInput
from test_context import package,catalog,frame,owner
from test_runtime import request,generate

@pytest.mark.parametrize('question',[
    '请比较35-45人的试点范围。','2026-10-31前可以完成吗？','scope_filter是否需要开启？',
    'human_fallback应如何安排？','real-time更新有什么取舍？','先用read-only access可以吗？',
    '请给我20-30分钟的调查建议。','我们先做cost-benefit分析。','36.5%的比例该怎样理解？','2026/10/31是预计日期。',
])
def test_real_w02_normal_questions_and_generated_mentions_are_preserved(package,catalog,question):
    snap=assemble_context(catalog,frame(package,catalog));req=request(owner())
    req=req.model_copy(update={'input':TurnInput(role_id=snap.role.id,text=question)})
    public,audit=generate(snap,owner(),req,ScriptedModel([ModelReply(text=question)]))
    assert public.question==public.text==question
    assert audit.prompt_messages[-1].content==question and public.status=='completed'


def test_local_adapter_shows_material_titles_and_versions_instead_of_s_ids(package,catalog):
    snap=assemble_context(catalog,frame(package,catalog));model=LocalRoleModel()
    public,audit=generate(snap,owner(),request(owner()),model)
    data=json.loads(audit.prompt_messages[0].content.split('\nCONTEXT\n',1)[1])
    assert model.retries==0 and data['sources']
    for source in data['sources']:
        assert 'display_name' in source and 'id' not in source
    shown=data['sources'][:4]
    assert all('['+source['display_name']+']' in public.text for source in shown)
    assert '[S1]' not in public.text and '[S2]' not in public.text
    materials={(m.id,m.version):m.title for m in catalog.materials}
    for source in snap.context.sources:
        if not snap.private_ref(source.ref):
            label=materials[source.ref.object_id,source.ref.version]+' · v'+str(source.ref.version)
            assert snap.source_label(source)==label
        else:assert snap.source_label(source)==role_text('zh','colleague_note')


CUSTOM_TERMS=('success_metric','weekly_hours_saved','pilot_followup_task','stage2_owner_notes')


@pytest.mark.parametrize('term',CUSTOM_TERMS)
def test_user_defined_names_survive_question_reply_and_next_memory(package,catalog,term):
    from dataclasses import replace
    from career_lab.storage.role_memory import memory_from_generation
    question=f'把 {term} 定为每周节省工时可以吗？'
    snap=assemble_context(catalog,frame(package,catalog));req=request(owner())
    req=req.model_copy(update={'input':TurnInput(role_id=snap.role.id,text=question)})
    public,audit=generate(snap,owner(),req,ScriptedModel([ModelReply(text=question)]))
    assert public.question==public.text==audit.prompt_messages[-1].content==question
    memory=memory_from_generation(public,audit)
    next_snap=assemble_context(catalog,replace(frame(package,catalog),memories=(memory,)))
    assert question in memory.fragment.text and question in next_snap.messages(owner())[0][0]['content']


CLAUDE_TERMS=('35-45','3-5万','2026-10-31','2026-11-15','M1-M3','follow-up','scope_filter','human_fallback')


def test_claude_p1_terms_survive_actual_worker_store_readback_and_next_memory(tmp_path,package,catalog):
    """Real store/worker, bounded private-port fixture; not production persistence QA.

    The next memory is projected from an actually committed/publicly read reply.
    Full private generation carrier and real language judgment remain separate.
    """
    from dataclasses import replace
    from career_lab.contracts.v2 import Command
    from career_lab.api.modules import ExtensionRegistry,Gateway
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import Worker,ClaimedHandler
    from career_lab.runtime.context_v2 import ContextPort
    from career_lab.runtime.roles_v2 import RoleService
    from career_lab.storage.role_memory import parse_public_reply,memory_from_generation
    from test_private_port_boundary import ControlledSnapshot,ControlledPrivatePort,ControlledReplyVerifier
    from test_runtime import common_store
    class ReadbackSnapshot(ControlledSnapshot):
        memories=()
        def project_fixed(self,*args):return replace(super().project_fixed(*args),memories=self.memories)
    class PerReplyAudit(ControlledPrivatePort):
        def prepare(self,*args):
            writes=super().prepare(*args);generation=args[-1]
            write=writes[0].model_copy(update={'ref':writes[0].ref.model_copy(update={'object_id':'audit-'+generation.reply_ref.object_id})})
            self.plans[-1]=write;return (write,)
    question='人数35-45，预算3-5万，上线日期2026-10-31→2026-11-15，里程碑M1-M3，follow-up以及scope_filter和human_fallback如何安排？'
    question+=' 另定义 '+', '.join(CUSTOM_TERMS)+'。'
    answer='关于'+question+'我需要先看更多证据。'
    model=ScriptedModel([ModelReply(text=answer),ModelReply(text='继续核对上一轮保留的条件。')])
    store,auth=common_store(tmp_path,catalog);projection=ReadbackSnapshot(package,catalog);private=PerReplyAudit()
    service=RoleService(ContextPort(catalog,projection),model,private_port=private,reply_verifier=ControlledReplyVerifier())
    registry=ExtensionRegistry();service.install(registry);gateway=Gateway(store,registry)
    jobs=JobRepository(store.db);worker=Worker(jobs,{'v2.role_turn':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.role_turn',payload,claim=claim))})
    def run(text,key):
        view=store.view(auth)
        command=Command(schema_version=2,request_id=key,operation='turns.create',expected_version=view.state.business_seq,
            expected_workspace_revision=view.state.workspace_revision,payload=TurnInput(role_id='tech_lead',text=text).model_dump(mode='json'))
        queued=gateway.dispatch(auth,'turns.create',command.model_dump(mode='json'))
        worker.run_once();job=jobs.get(queued['result']['queued_jobs'][0]);assert job['status']=='completed',job
        return command
    before=store.view(auth).state.resources
    command=run(question,'normal-original')
    record=next(x for x in store.view(auth).objects if x.ref.kind=='role_reply')
    persisted=parse_public_reply(store.read(auth,record.ref).content)
    assert persisted.question==question and persisted.text==answer
    replay=gateway.dispatch(auth,'turns.create',command.model_dump(mode='json'))
    assert replay['result']['question']==question
    memory=memory_from_generation(persisted,private.generations[0]);projection.memories=(memory,)
    run('请接续上一轮讨论，保留已经提过的具体条件。','normal-next')
    first_prompt=model.calls[0][-1]['content'];next_prompt=model.calls[1][0]['content']
    for term in (*CLAUDE_TERMS,*CUSTOM_TERMS):
        assert term in question and term in first_prompt and term in persisted.text
        assert term in memory.fragment.text and term in next_prompt
    assert '[来源引用]' not in first_prompt
    assert store.view(auth).state.resources==before
    assert len(model.calls)==2 and all(x.error_code is None for x in [persisted])
