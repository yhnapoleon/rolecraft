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
        try:
            for _ in range(100):
                try:
                    if httpx.get(url+'/openapi.json',timeout=.2).status_code==200:break
                except httpx.TransportError:pass
                time.sleep(.05)
            with httpx.Client(base_url=url,timeout=5) as client:
                session=client.post('/sessions',json={'schema_version':2,'scenario':'w04-unavailable-ports'}).json()
                body={'schema_version':2,'request_id':'blocked-turn','operation':'turns.create','expected_version':0,'expected_workspace_revision':0,
                      'payload':{'role_id':'tech_lead','text':'请继续上轮'}}
                response=client.post(f"/sessions/{session['session_id']}/turns",headers={'Authorization':'Bearer '+session['token']},json=body)
                assert response.status_code==409,response.text
                assert 'role_snapshot_unavailable' in response.text
                assert 'prompt_messages' not in response.text and 'acceptable_conditions' not in response.text
                (evidence/'http-evidence.json').write_text(json.dumps({'status':response.status_code,'response':response.json(),
                    'mode':'real-http-fail-closed','full_role_pipeline':False,'reason':'official private role projection/audit port absent'},ensure_ascii=False,indent=2))
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
