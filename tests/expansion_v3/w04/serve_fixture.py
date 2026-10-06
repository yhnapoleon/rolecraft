"""Standalone boundary-fixture app for HTTP/independent worker verification only."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

from career_lab.api.app import create_app
from career_lab.api.modules import Operation
from career_lab.api.approvals_v2 import ScenarioApprovalPort, NegotiationService
from career_lab.contracts.v2 import ActionInput, AssistantConfig, BusinessBasis, BusinessRequest, assistant_config_content_hash
from career_lab.jobs.worker import Worker
from career_lab.storage.role_memory import install_role_storage, object_write
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation

from test_runtime import build_runtime
from test_approvals import evaluate
from types import SimpleNamespace


def build_app(url):
    runtime=build_runtime(url)
    negotiation=NegotiationService(ScenarioApprovalPort.from_w02(
        SimpleNamespace(rules={"approval_limits":{"capacity":60}}),evaluate))
    def request_handler(view,command,auth):
        body=ActionInput.model_validate(command.payload)
        if body.tool!="request_business" or body.config is None:
            from career_lab.contracts.v2 import ProtocolError
            raise ProtocolError("fixture_action_unavailable")
        request=BusinessRequest(id="request-"+command.request_id,session_id=auth.session_id,version=1,
             basis=BusinessBasis(mode="proposed",config=body.config,content_hash=assistant_config_content_hash(body.config)),
             requested=body.terms,reason=body.reason,evidence_refs=body.evidence_refs,
             as_of=point(view.state),executor=auth.executor)
        write=object_write("business_request",request)
        return Mutation(writes=(write,),result={"request":write.ref.model_dump(mode="json")})
    runtime[1].register(negotiation.operation())
    runtime[1].register(Operation("actions","act",ActionInput,negotiation.actions(request_handler),
         action_field="tool",approval_policy=negotiation.approval_policy()))
    app=create_app(url,extensions=runtime[1]);install_role_storage(app.state.v2_store)
    return app


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("mode",choices=("serve","worker"))
    parser.add_argument("--database",required=True);parser.add_argument("--port",type=int,default=18782)
    args=parser.parse_args();app=build_app(args.database)
    if args.mode=="serve":
        import uvicorn
        uvicorn.run(app,host="127.0.0.1",port=args.port,log_level="warning")
    else:
        worker=Worker(app.state.jobs,app.state.handlers)
        while True:
            if not worker.run_once():time.sleep(.05)
