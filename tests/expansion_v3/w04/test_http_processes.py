"""Real sockets and independently initialized worker; no in-process ASGI transport."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time

import httpx

from career_lab.contracts.v2 import AssistantConfig
from career_lab.storage.v2_store import V2Store
from career_lab.storage.role_memory import install_role_storage, read_replies


def test_real_http_worker_two_shares_counter_accept_and_restart(tmp_path):
    evidence=Path(os.environ.get("W04_EVIDENCE_DIR",str(tmp_path)))
    evidence.mkdir(parents=True,exist_ok=True)
    db_path=(evidence/"http-worker.db").resolve()
    assert not db_path.exists(), "Use a fresh evidence directory; prior databases are retained"
    database="sqlite:///"+str(db_path)
    with socket.socket() as s:s.bind(("127.0.0.1",0));port=s.getsockname()[1]
    url=f"http://127.0.0.1:{port}";script=Path(__file__).with_name("serve_fixture.py")
    env=os.environ.copy();env.pop("PYTHONPATH",None)
    log=(evidence/"http-processes.log").open("w")
    def start(mode):
        return subprocess.Popen([sys.executable,str(script),mode,"--database",database,"--port",str(port)],
                                stdout=log,stderr=subprocess.STDOUT,env=env)
    server=start("serve");worker=None;transcript=[]
    def ready():
        for _ in range(100):
            try:
                if httpx.get(url+"/openapi.json",timeout=.2).status_code==200:return
            except httpx.TransportError:pass
            time.sleep(.05)
        raise AssertionError("HTTP fixture failed to start; see process log")
    try:
        ready()
        # Initialize SQLite/schema once before the separately initialized worker.
        worker=start("worker")
        with httpx.Client(base_url=url,timeout=5) as client:
            created=client.post("/sessions",json={"schema_version":2,"scenario":"w04-boundary-fixture"}).json()
            sid=created["session_id"];headers={"Authorization":"Bearer "+created["token"]}
            root=f"/sessions/{sid}";state=created["state"]
            def post(path,key,operation,payload):
                nonlocal state
                body={"schema_version":2,"request_id":key,"operation":operation,
                      "expected_version":state["business_seq"],"expected_workspace_revision":state["workspace_revision"],"payload":payload}
                r=client.post(root+path,headers=headers,json=body);assert r.status_code==200,r.text
                data=r.json();state=data["state"]
                transcript.append({"path":path,"request":body,"status":r.status_code,"response":data})
                return data
            def wait(data):
                nonlocal state
                jid=data["result"]["queued_jobs"][0]
                for _ in range(100):
                    r=client.get(root+"/jobs/"+jid,headers=headers);job=r.json()
                    if job["status"] in {"completed","failed"}:break
                    time.sleep(.05)
                assert job["status"]=="completed",job
                state=job["result"]["state"]
                transcript.append({"job_id":jid,"job":job})
                return job["result"]["result"]
            product=post("/work-products","p1","work_products.create",{"kind":"text","content":"方案v1：计划扩大试点；资源未申请"})["result"]["product"]
            share=post(f"/work-products/{product['object_id']}/shares","s1","work_products.shares.create",
                       {"product_id":product["object_id"],"product_version":1,"recipient_role":"tech_lead"})["result"]["share"]
            first=wait(post("/turns","t1","turns.create",{"role_id":"tech_lead","text":"请先质疑这份方案","shares":[share]}))
            assert "方案v1" in first["text"]
            post(f"/work-products/{product['object_id']}/versions","p2","work_products.versions.create",
                 {"product_id":product["object_id"],"expected_head":1,"kind":"text","content":"方案v2：增加容量对照测试，保留人工兜底"})
            share2=post(f"/work-products/{product['object_id']}/shares","s2","work_products.shares.create",
                 {"product_id":product["object_id"],"product_version":2,"recipient_role":"tech_lead"})["result"]["share"]
            second=wait(post("/turns","t2","turns.create",{"role_id":"tech_lead","text":"请继续上轮","shares":[share2]}))
            assert "我保留上轮讨论记录" in second["text"] and "方案v2" in second["text"]
            config=AssistantConfig(id="proposed",session_id=sid,domains=("faq",),participants=50).model_dump(mode="json")
            request=post("/actions","business","request_business",{"tool":"request_business","config":config,
                  "terms":{"capacity":100},"reason":"支持选定的50人试点"})["result"]["request"]
            offer=post("/approvals/resolve","offer","approvals.resolve",{"request":request,"expected_request_revision":1})
            assert offer["result"]["decision"]["status"]=="countered"
            oracle=V2Store(database);install_role_storage(oracle);auth=oracle.authenticate(sid,created["token"])
            assert oracle.view(auth).state.resources["capacity"]==30
            accepted=post("/actions","accepted","accept_counteroffer",{"tool":"accept_counteroffer","request":offer["result"]["request"]})
            assert accepted["result"]["decision"]["granted"]=={"capacity":60}
            assert oracle.view(auth).state.resources["capacity"]==60
            old=read_replies(oracle.view(auth))[0].model_dump(mode="json")
            server.terminate();server.wait(timeout=5);server=start("serve");ready()
            restored=client.get(root+"/requests/t1",headers=headers);assert restored.status_code==200,restored.text
            assert restored.json()["jobs"][0]["effect"]["result"]["text"]==first["text"]
            assert read_replies(oracle.view(auth))[0].model_dump(mode="json")==old
            transcript.append({"restart_request_result":restored.json(),"resource_capacity_after_accept":60})
        (evidence/"http-worker-evidence.json").write_text(json.dumps({"mode":"real-http-independent-worker-controlled-scenario",
            "production_w02_w03_integrated":False,"real_model_quality_verified":False,
            "database":database,"requests":transcript},ensure_ascii=False,indent=2))
    finally:
        for process in (server,worker):
            if process is None:continue
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
