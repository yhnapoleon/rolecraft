"""Executable loopback fixture for native UI + actual API/worker persistence.

Synthetic scenario and no semantic provider. This wiring is for verification;
032 owns the corresponding production app/worker registration.
"""
import argparse,threading
from pathlib import Path
from uuid import uuid4
import uvicorn
from fastapi.testclient import TestClient
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation,JobRequest
from career_lab.storage.v2_lifecycle import record_submission,begin_revision
from career_lab.workspace.extension import install_workspace_operations
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.rubrics.v4.rubric_v2 import policies
from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator,submission_feedback_plan,submission_plan_with_feedback
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker,ClaimedHandler


def make_app(database,work_language="zh"):
    registry=ExtensionRegistry();f=C.FileRef(path='controlled-native-feedback.json',sha256='1'*64)
    registry.register_scenario('native-feedback-fixture',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),C.AssistantConfig(id='config',session_id='fixture',domains=('faq',)),{}))
    install_workspace_operations(registry,roles=('supervisor','tech_lead','business_lead'));install_feedback_recovery(registry)
    registry.register(Operation('submissions.create','submit',C.SubmitInput,lambda v,c,a:submission_plan_with_feedback(v,c,a,job_name='v2.w05-native-feedback'),action_name='submit'))
    registry.register(Operation('revision_cycles','act',C.BeginRevisionInput,begin_revision,action_name='begin_revision'))
    holder={}
    def process(view,envelope,auth):
        store=holder['app'].state.v2_store;subject=C.FeedbackInput.model_validate(envelope.command.payload).subject
        submission=C.SubmissionV2.model_validate(view.get(subject).content)
        reader=StoreEvidenceReader(store,auth,policies=policies(work_language=work_language))
        prepared=SubmissionEvaluator(reader,work_language=work_language).evaluate(auth,submission)
        return submission_feedback_plan(view,envelope.command,auth,prepared)
    registry.register_job('v2.w05-native-feedback',process)
    app=create_app('sqlite:///'+str(database.resolve()),extensions=registry);holder['app']=app
    fixture={}
    @app.get('/__w05_native_test__/dark-style')
    def dark_style():
        from fastapi.responses import Response
        css=(Path(__file__).resolve().parents[2]/'apps/web/src/app/styles.css').read_text()
        return Response(css.replace('@media (prefers-color-scheme: dark)','@media all'),media_type='text/css')
    @app.post('/__w05_native_test__/bootstrap')
    def bootstrap():
        if fixture:
            auth=app.state.v2_store.authenticate(fixture['session_id'],fixture['token']);view=app.state.v2_store.view(auth)
            latest=[r for r in view.objects if r.ref.kind=='submission'];saved=max(latest,key=lambda r:r.created_storage_revision) if latest else None
            return {**fixture,'status':view.state.status,'reports':[r.content for r in view.objects if r.ref.kind=='feedback'],
                'submission':{'ref':saved.ref.model_dump(mode='json'),'products':saved.content['products'],'decision':saved.content['decision']} if saved else None}

        with TestClient(app) as client:
            created=client.post('/sessions',json={'schema_version':2,'scenario':'native-feedback-fixture'}).json();sid=created['session_id'];fixture.update(created)
            client.headers['Authorization']='Bearer '+created['token'];auth=app.state.v2_store.authenticate(sid,created['token'])
            def product(title,text,evidence=()):
                state=app.state.v2_store.view(auth).state
                body=C.Command(schema_version=2,request_id=uuid4().hex,expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,operation='work_products.create',payload={'kind':'text','title':title,'content':text,'evidence_refs':list(evidence)})
                response=client.post(f'/sessions/{sid}/work-products',json=body.model_dump(mode='json'));response.raise_for_status();return response.json()['result']['ref']
            source=product('受控原始记录','本地验证：当前资料需要核对版本与覆盖范围。')
            evidence=C.EvidenceRefV2(**source,observed_at_seq=0,quote='当前资料需要核对版本与覆盖范围。').model_dump(mode='json')
            product('试点决定与后续核验','先补齐版本核对和测试，再决定是否推进。',(evidence,))
            fixture['evidence']=[evidence];fixture['work_language']=work_language
        return fixture
    return app,registry


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--language',choices=('zh','en'),default='zh');args=parser.parse_args()
    app,registry=make_app(args.database,args.language);gateway=app.state.gateway;queue=JobRepository(app.state.v2_store.db)
    worker=Worker(queue,{'v2.w05-native-feedback':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.w05-native-feedback',payload,claim=claim))})
    stop=threading.Event()
    def loop():
        while not stop.is_set():
            if not worker.run_once():stop.wait(.05)
    thread=threading.Thread(target=loop,daemon=True);thread.start()
    try:uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='warning')
    finally:stop.set();thread.join(2)


if __name__=='__main__':main()
