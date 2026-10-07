from pathlib import Path
import hashlib,json,subprocess
from career_lab.api.app import create_app
from career_lab.contracts.v2.discovery import public_models,REQUEST_MODELS
ROOT=Path(__file__).resolve().parents[3]
FREEZE=ROOT/'docs/contracts/expansion-v3'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def test_all_frozen_models_examples_and_openapi_agree():
    manifest=json.loads((FREEZE/'manifest.json').read_text());models=public_models()
    assert set(manifest['schemas'])==set(models)
    for name,entry in manifest['schemas'].items():
        assert sha(FREEZE/entry['schema'])==entry['schema_sha256']
        assert sha(FREEZE/entry['example'])==entry['example_sha256']
        assert json.loads((FREEZE/entry['schema']).read_text())==models[name].model_json_schema()
        assert models[name].model_validate_json((FREEZE/entry['example']).read_text())
        assert entry['owner']=='W01' and entry['consumers'] and entry['tests']
    for path,expected in manifest['source_files'].items():assert sha(ROOT/path)==expected,path
    app=create_app('sqlite:///:memory:')
    assert app.openapi()==json.loads((FREEZE/'openapi.json').read_text())
    assert set(REQUEST_MODELS)==set(manifest['request_payloads'])
    api=app.openapi()
    def refs(node):
        if isinstance(node,dict):
            if '$ref' in node:
                value=api
                for part in node['$ref'].split('/')[1:]:value=value[part]
            for x in node.values():refs(x)
        elif isinstance(node,list):
            for x in node:refs(x)
    refs(api)
    for names in manifest['consumer_interfaces'].values():assert all(n in models for n in names)
    assert (FREEZE/'revision.txt').read_text().strip()=='expansion-v3-'+sha(FREEZE/'manifest.json')
    app.state.store.close()

def test_v1_scenarios_contracts_and_old_research_freeze_bytes_unchanged():
    protected=['src/career_lab/contracts/actions.py','src/career_lab/contracts/base.py','src/career_lab/contracts/scenario.py','src/career_lab/contracts/evaluation.py','src/career_lab/contracts/deliverables.py','docs/reports/controlled-v2-freeze.json']
    protected += subprocess.check_output(['git','ls-tree','-r','--name-only','80cf1f6189cd25610d609f44283ff9668582d759','--','scenarios'],cwd=ROOT,text=True).splitlines()
    for rel in protected:
        old=subprocess.check_output(['git','show','80cf1f6189cd25610d609f44283ff9668582d759:'+rel],cwd=ROOT)
        assert (ROOT/rel).read_bytes()==old,rel
