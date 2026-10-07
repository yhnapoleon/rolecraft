"""Full W05 evaluator over the explicitly frozen W02 r9 adapter.

Run only in the isolated, hash-checked W02-owned + c9 + W05 combination.
History captures actual FastAPI/Gateway/SQLite calls; this is not the W14
production history reader, normal v4 QA, or model-quality evidence.
"""
from pathlib import Path
import importlib.util,json,os
import pytest
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,Operation
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.workspace.extension import install_workspace_operations
from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator,submission_plan_with_feedback,submission_feedback_plan
from career_lab.rubrics.v4.rubric_v2 import create_installed_reader
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker,ClaimedHandler

pytestmark=pytest.mark.skipif(not os.environ.get('W05_W02_COMBO_ROOT'),reason='requires authorized exact W02 r9 isolated combination')

@pytest.fixture(params=['zh','en'])
def combined(request,tmp_path):
    from career_lab.scenarios.v2.module import ScenarioModule
    repo=Path(os.environ['W05_W02_COMBO_ROOT']);path=repo/'tests/expansion_v3/w02/test_evaluation_facts.py'
    spec=importlib.util.spec_from_file_location('frozen_w02_r9_history',path);fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    module=ScenarioModule(Path(os.environ.get('W05_W02_SCENE_ROOT',str(repo/'installed/scenarios/pm_pilot/v2'))),work_language=request.param)
    registry=module.install(ExtensionRegistry());install_workspace_operations(registry,roles=tuple(r.id for r in module.package.bundle.role_specs));install_feedback_recovery(registry)
    registry.register(Operation('submissions.create','submit',C.SubmitInput,submission_plan_with_feedback))
    app=create_app('sqlite:///'+str(tmp_path/'combo.db'),extensions=registry);holder={}
    def generate(view,envelope,actor):
        h=holder['h'];subject=C.FeedbackInput.model_validate(envelope.command.payload).subject
        submission=C.SubmissionV2.model_validate(view.get(subject).content)
        reader=create_installed_reader(h.store,actor,module.package.root,source_reader=h.adapter.source_reader,
            rule_provider=h.adapter.rule_provider,submission_rule_provider=h.adapter.submission_rule_provider,work_language=request.param)
        prepared=SubmissionEvaluator(reader,work_language=request.param,model_bytes=64000).evaluate(actor,submission)
        holder['prepared']=prepared
        return submission_feedback_plan(view,envelope.command,actor,prepared)
    registry.register_job('v2.submission-feedback',generate)
    with TestClient(app) as client:
        created=client.post('/sessions',json={'schema_version':2,'scenario':'pm_pilot_v2'});assert created.status_code==200,created.text
        h=fixture.History(app,client,module,created.json());holder['h']=h
        queue=JobRepository(h.store.db);worker=Worker(queue,{'v2.submission-feedback':ClaimedHandler(lambda payload,claim:app.state.gateway.run_job('v2.submission-feedback',payload,claim=claim))})
        yield h,worker,queue,holder
    app.state.store.close();app.state.v2_store.db.engine.dispose()

@pytest.mark.parametrize('branch',['ignored','stale','fresh_limited','fresh_approved','no_go','defer_with_conditions'])
def test_w05_frozen_w02_full_feedback(combined,branch,tmp_path):
    h,worker,queue,holder=combined
    question='住宿报销上限是多少？' if h.module.work_language=='zh' else 'What is the hotel reimbursement limit per night?'
    old=h.run(question)
    h.apply(freshness_guard='warn',participants=50 if branch=='fresh_approved' else 20)
    if branch=='fresh_approved':
        request=h.post('actions','request_business',{'tool':'request_business','terms':{'capacity':60},'reason':'Candidate user scope exceeds current capacity',
            'evidence_refs':[{'session_id':h.sid,'kind':'material','object_id':'user_groups','version':1,'observed_at_seq':0}]})
        decision=h.post('approvals/resolve','resolve_approval',{'request':request['result']['request'],'expected_request_revision':1})
        assert decision['result']['decision']['status']=='approved'
        h.apply(freshness_guard='warn',participants=50)
    if branch in {'stale','fresh_limited','fresh_approved'}:h.run(question)
    if branch.startswith('fresh'):
        h.post('actions','refresh_index',{'tool':'refresh_index'});h.run(question)
    products=(h.product('This note establishes the intended audience.'),h.product('This note compares next steps and evidence needs.'))
    choice=branch if branch in {'no_go','defer_with_conditions'} else ('launch_narrow' if branch=='fresh_limited' else 'launch')
    submitted=h.submit(products,choice)
    generation_only=os.environ.get('W05_COMBO_GENERATION_ONLY')=='1'
    if generation_only:
        reader=create_installed_reader(h.store,h.auth,h.module.package.root,source_reader=h.adapter.source_reader,
            rule_provider=h.adapter.rule_provider,submission_rule_provider=h.adapter.submission_rule_provider,work_language=h.module.work_language)
        prepared=SubmissionEvaluator(reader,work_language=h.module.work_language,model_bytes=64000).evaluate(h.auth,submitted)
        assert len(prepared['reports'])==1
        report=prepared['reports'][0]
        assert not [r for r in h.store.view(h.auth).objects if r.ref.kind=='feedback']
    else:
        assert worker.run_once()
        rows=[r for r in h.store.view(h.auth).objects if r.ref.kind=='feedback']
        if not rows:
            from sqlalchemy import select
            from career_lab.jobs.repository import jobs
            with h.store.db.engine.connect() as conn:
                status=conn.execute(select(jobs.c.status,jobs.c.error)).all()
            from career_lab.storage.v2_store import references
            prepared=holder.get('prepared',{})
            ready=prepared.get('reports',())
            known={C.canonical(row.ref) for row in h.store.view(h.auth).objects}
            missing={ref.kind for report in ready for ref in references(report.model_dump(mode='json')) if C.canonical(ref) not in known and ref.kind not in h.store.reference_resolvers}
            grades={item.criterion:item.label for report in ready for item in report.rule_items}
            pytest.fail('feedback worker produced no record: '+str({'jobs':status,'prepared_reports':len(ready),'unregistered_dependency_kinds':sorted(missing),'rule_results':grades}))
        assert len(rows)==1
        report=C.FeedbackV2.model_validate(rows[0].content);by_id={x.criterion:x for x in report.rule_items}
    by_id={x.criterion:x for x in report.rule_items}
    assert len(report.items)==len(by_id)==14 and len(report.verified_facts)==2
    assert report.mode=='advisory' and all(x.source!='model_advice' for x in report.items)
    assert not any(x.label=='NOT_MET' for x in report.items if x.criterion in {'R1.target','R1.metrics','R6.alternatives'})
    for cid in ('R3.capacity','R3.resources'):
        assert by_id[cid].label==('NOT_APPLICABLE' if choice in {'no_go','defer_with_conditions'} else 'MET'),by_id[cid]
    expected={'ignored':('NOT_MET','NOT_MET'),'stale':('PARTIAL','INSUFFICIENT'),'fresh_limited':('MET','MET'),'fresh_approved':('MET','MET'),'no_go':('NOT_APPLICABLE','NOT_APPLICABLE'),'defer_with_conditions':('NOT_APPLICABLE','NOT_APPLICABLE')}[branch]
    assert (by_id['R4.staleness_test'].label,by_id['R5.adjustment'].label)==expected
    assert any(ref.kind=='config' for ref in by_id['R4.staleness_test'].citations) or choice in {'no_go','defer_with_conditions'}
    if branch=='fresh_approved':assert any(ref.kind=='business_decision' for ref in by_id['R3.capacity'].citations)
    before=C.digest(report)
    if not generation_only:
        assert not worker.run_once()
        assert C.digest(C.FeedbackV2.model_validate(h.store.read(h.auth,rows[0].ref).content))==before
    folder=Path(os.environ.get('W05_COMBO_EVIDENCE_DIR',str(tmp_path)));folder.mkdir(parents=True,exist_ok=True)
    record={'language':h.module.work_language,'branch':branch,'decision':choice,'scenario':h.module.bindings.scenario.model_dump(mode='json'),
        'evaluation':report.evaluation.model_dump(mode='json'),'submission':submitted.model_dump(mode='json'),'feedback':report.model_dump(mode='json'),
        'feedback_sha256':before,'source':'real FastAPI TestClient / Gateway / SQLite / worker; frozen W02 r9 actual material/config/policy/test/approval producers',
        'feedback_persisted':not generation_only,'history_boundary':'in-process exact capture after each actual command, not W14 production history reader','initial_answer_preserved':old['answer']}
    (folder/(h.module.work_language+'-'+branch+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
