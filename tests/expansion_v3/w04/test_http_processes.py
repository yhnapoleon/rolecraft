"""Real HTTP blocked-port behavior, not a claim of full role integration."""
from pathlib import Path
import json,os,socket,subprocess,sys,time
import httpx


def test_actual_http_missing_trusted_role_port_fails_closed(tmp_path):
    evidence=Path(os.environ.get('W04_EVIDENCE_DIR',str(tmp_path))).resolve();evidence.mkdir(parents=True,exist_ok=True)
    db=evidence/'http-blocked.db';assert not db.exists(),'Use a new evidence directory'
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    url=f'http://127.0.0.1:{port}';script=Path(__file__).with_name('serve_fixture.py')
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[3]/'src')
    with (evidence/'process.log').open('w') as log:
        server=subprocess.Popen([sys.executable,str(script),'serve','--database','sqlite:///'+str(db),'--port',str(port)],stdout=log,stderr=subprocess.STDOUT,env=env)
        worker=None
        try:
            for _ in range(100):
                try:
                    if httpx.get(url+'/openapi.json',timeout=.2).status_code==200:break
                except httpx.TransportError:pass
                time.sleep(.05)
            worker=subprocess.Popen([sys.executable,str(script),'worker','--database','sqlite:///'+str(db)],stdout=log,stderr=subprocess.STDOUT,env=env)
            with httpx.Client(base_url=url,timeout=5) as client:
                session=client.post('/sessions',json={'schema_version':2,'scenario':'w04-unavailable-ports'}).json()
                body={'schema_version':2,'request_id':'blocked-turn','operation':'turns.create','expected_version':0,'expected_workspace_revision':0,
                      'payload':{'role_id':'tech_lead','text':'请继续上轮'}}
                response=client.post(f"/sessions/{session['session_id']}/turns",headers={'Authorization':'Bearer '+session['token']},json=body)
                assert response.status_code==200,response.text
                queued=response.json();job_id=queued['result']['queued_jobs'][0]
                headers={'Authorization':'Bearer '+session['token']}
                for _ in range(100):
                    job=client.get(f"/sessions/{session['session_id']}/jobs/{job_id}",headers=headers).json()
                    if job['status'] in {'completed','failed'}:break
                    time.sleep(.05)
                assert job['status']=='failed' and job['attempt']==1 and job['error']=='role_private_storage_unavailable',job
                assert job['result'] is None
                from career_lab.storage.v2_store import V2Store
                from career_lab.contracts.v2 import ObjectRef
                store=V2Store('sqlite:///'+str(db));auth=store.authenticate(session['session_id'],session['token'])
                turn=store.read(auth,ObjectRef.model_validate(queued['result']['turn']))
                assert turn.content['input']['text']==body['payload']['text']
                recovered=client.get(f"/sessions/{session['session_id']}/requests/blocked-turn",headers=headers).json()
                assert recovered['status']=='failed'
                assert recovered['response']['result']['question']==body['payload']['text']
                assert 'prompt_messages' not in json.dumps(recovered) and 'acceptable_conditions' not in json.dumps(recovered)
                (evidence/'http-evidence.json').write_text(json.dumps({'status':response.status_code,'queued':queued,'job':job,
                    'recovered':recovered,'original_question_preserved':turn.content['input']['text'],
                    'mode':'real-http-independent-worker-fail-closed','full_role_pipeline':False,
                    'reason':'official protected generation/audit port absent; no reply fabricated'},ensure_ascii=False,indent=2))
        finally:
            if worker is not None:
                worker.terminate()
                try:worker.wait(timeout=5)
                except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=5)
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
