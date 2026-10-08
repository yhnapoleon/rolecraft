"""Loopback-only synthetic native component fixture; never installed in production."""
import argparse
from pathlib import Path
import uvicorn
from fastapi.testclient import TestClient
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration
from career_lab.contracts import v2 as C
from career_lab.workspace.extension import install_workspace_operations


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True);parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    registry=ExtensionRegistry();f=C.FileRef(path='controlled-native-fixture.json',sha256='1'*64)
    registry.register_scenario('native-w03-fixture',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),C.AssistantConfig(id='config',session_id='fixture',domains=('faq',)),{}))
    install_workspace_operations(registry,roles=('supervisor','tech_lead','business_lead'))
    app=create_app('sqlite:///'+str(args.database.resolve()),extensions=registry)
    @app.post('/__w03_native_test__/bootstrap')
    def bootstrap():
        with TestClient(app) as client:
            return client.post('/sessions',json={'schema_version':2,'scenario':'native-w03-fixture'}).json()
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='warning')


if __name__=='__main__':main()
