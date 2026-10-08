"""Narrow immutable-package rebind with verified public/code inputs and HTTP startup.

Does not install public files, change authored content, modify a source release,
register acceptance, or replace a running application's bindings.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import yaml
from career_lab.contracts.v2 import FileRef, ProtocolError, RuntimeBundle, ScenarioBundle, digest
from .loader import load_package
from .module import ScenarioModule
from .localization import runtime_source_files


def sha(raw):return hashlib.sha256(raw).hexdigest()


def verified_public_input(repo,expected_revision):
    path=repo/'docs/contracts/expansion-v3/manifest.json';raw=path.read_bytes()
    if expected_revision!='expansion-v3-'+sha(raw):raise ProtocolError('rebind_public_manifest_mismatch',status=409)
    data=json.loads(raw);checked={}
    from career_lab.contracts.v2.compatibility import without_provenance
    from career_lab.contracts.v2.discovery import public_models

    models = public_models()
    for name, entry in data['schemas'].items():
        source = path.parent / entry['schema']
        actual = sha(source.read_bytes())
        if actual != entry['schema_sha256']:
            raise ProtocolError('rebind_public_source_mismatch', status=409)
        if without_provenance(models[name].model_json_schema()) != json.loads(source.read_text()):
            raise ProtocolError('rebind_public_protocol_mismatch', status=409)
        checked[str(source.relative_to(repo))] = actual
    if not checked:
        raise ProtocolError('rebind_public_sources_missing')
    return sha(raw),checked


def verified_owned_input(repo, expected, locale, tooling_baseline=None):
    """An explicit migration may change only this release tool, never runtime logic.

    Every original owned file must match the supplied full immutable Git commit;
    every current file except this tool must still match those original bytes.
    """
    current = runtime_source_files(repo, locale)
    if current == expected:
        return current, None
    tool = 'src/career_lab/scenarios/v2/rebind.py'
    import re
    if tooling_baseline is None or re.fullmatch(r'[0-9a-f]{40}', tooling_baseline) is None:
        raise ProtocolError('rebind_owned_code_mismatch', status=409)
    if set(current) != set(expected) or {p for p in current if current[p] != expected[p]} != {tool}:
        raise ProtocolError('rebind_runtime_change_not_authorized', status=409)
    for path, expected_hash in expected.items():
        result = subprocess.run(['git', 'show', tooling_baseline + ':' + path], cwd=repo, capture_output=True)
        if result.returncode:
            raise ProtocolError('rebind_tooling_baseline_unavailable', status=409)
        raw = result.stdout
        if sha(raw) != expected_hash:
            raise ProtocolError('rebind_tooling_baseline_mismatch', status=409)
    return current, {'baseline_commit': tooling_baseline, 'changed_files': [tool],
                     'before_sha256': expected[tool], 'after_sha256': current[tool]}


def rebind(
    source: Path, destination: Path, *, contract_revision: str, scenario_revision: str,
    runtime_revision: str, tooling_baseline: str | None = None, protocol: str | None = None,
) -> dict[str, object]:
    if protocol is not None:
        from .release import PROTOCOL
        from .release_migration import migrate

        if protocol != PROTOCOL:
            raise ProtocolError("release_protocol_unsupported", status=409)
        return migrate(
            source, destination, contract_revision=contract_revision,
            scenario_revision=scenario_revision, runtime_revision=runtime_revision,
        )
    repo=Path(__file__).resolve().parents[4]
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):raise ProtocolError('rebind_destination_not_fresh',status=409)
    package=load_package(source)
    contract_hash,public_files=verified_public_input(repo,contract_revision)
    previous=RuntimeBundle.model_validate_json((source/'runtime/bundle.json').read_bytes())
    overlay=json.loads((source/'runtime/source-files.json').read_bytes())
    code,tooling_update=verified_owned_input(repo,overlay['owned_code'],package.locale,tooling_baseline)
    if previous.source.source_digest!=digest(overlay['owned_code']):
        raise ProtocolError('rebind_owned_code_mismatch',status=409)
    if not scenario_revision or scenario_revision==package.bundle.revision or not runtime_revision or runtime_revision==previous.revision:
        raise ProtocolError('rebind_new_revisions_required')
    before={ref.path:sha((source/ref.path).read_bytes()) for ref in package.bundle.files}
    destination.mkdir(parents=True)
    for ref in package.bundle.files:
        target=destination/ref.path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/ref.path,target)
    rules=yaml.safe_load((destination/'scenario.yaml').read_bytes());rules['revision']=scenario_revision
    (destination/'scenario.yaml').write_text(yaml.safe_dump(rules,allow_unicode=True,sort_keys=True))
    overlay['foundation_contract_sha256']=contract_hash
    overlay['owned_code']=code
    (destination/'runtime/source-files.json').write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n')
    runtime=previous.model_copy(update={'revision':runtime_revision,'source':previous.source.model_copy(update={
        'source_digest':digest(code),'overlay':FileRef(path='runtime/source-files.json',sha256=sha((destination/'runtime/source-files.json').read_bytes()))})})
    (destination/'runtime/bundle.json').write_text(runtime.model_dump_json(indent=2)+'\n')
    files=tuple(ref.model_copy(update={'sha256':sha((destination/ref.path).read_bytes())}) for ref in package.bundle.files)
    bundle=package.bundle.model_copy(update={'revision':scenario_revision,'files':files})
    (destination/'manifest.json').write_text(bundle.model_dump_json(indent=2)+'\n')
    changed=sorted(path for path,value in before.items() if sha((destination/path).read_bytes())!=value)
    if set(changed)-{'scenario.yaml','runtime/source-files.json','runtime/bundle.json'}:
        raise ProtocolError('rebind_authored_content_changed',status=409)
    verified_public_input(repo,contract_revision)
    module=ScenarioModule(destination)
    if any(sha((source/path).read_bytes())!=value for path,value in before.items()):
        raise ProtocolError('rebind_source_changed',status=409)
    return {'source_scenario_hash':package.content_hash,'target_scenario_hash':module.package.content_hash,
        'source_contract_hash':json.loads((source/'runtime/source-files.json').read_bytes())['foundation_contract_sha256'],
        'target_contract_revision':contract_revision,'verified_public_files':public_files,
        'tooling_update':tooling_update,'owned_source_digest':digest(code),'changed_generated_files':changed+['manifest.json'],
        'authored_content_unchanged':True,'source_unchanged':True,'constructor':'passed',
        'work_language':module.work_language,'output':str(destination),'accepted':False}


def smoke_http(root,database,report_dir):
    from career_lab.api.modules import CreateSessionV2
    root=Path(root).resolve();database=Path(database).resolve();report_dir=Path(report_dir).resolve()
    if database.exists():raise ProtocolError('rebind_smoke_database_exists',status=409)
    module=ScenarioModule(root);language=module.work_language
    report_dir.mkdir(parents=True,exist_ok=True);database.parent.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    command=[sys.executable,'-m','career_lab.cli','serve','--database-url','sqlite:///'+str(database),'--provider','local','--port',str(port)]
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','CAREER_LAB_SCENARIO_CATALOG','CAREER_LAB_SCENARIO_V2','CAREER_LAB_SCENARIO_ARCHIVE'}}
    env.update(PYTHONDONTWRITEBYTECODE='1',CAREER_LAB_SCENARIO_V2=str(root),CAREER_LAB_SCENARIO_ARCHIVE=str(report_dir/'archive'))
    log=(report_dir/'startup-server.log').open('w');process=subprocess.Popen(command,cwd=Path(__file__).resolve().parents[4],env=env,stdout=log,stderr=subprocess.STDOUT)
    steps=[]
    def request(method,path,payload=None,token=None):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        try:
            connection.request(method,path,body=json.dumps(payload) if payload is not None else None,headers=headers)
            response=connection.getresponse();data=json.loads(response.read());steps.append({'method':method,'path':path,'status':response.status})
            if response.status!=200:raise RuntimeError(f'{method} {path}: {response.status} {data}')
            return data
        finally:connection.close()
    try:
        for _ in range(150):
            if process.poll() is not None:raise RuntimeError('startup process exited')
            try:request('GET','/health');break
            except (ConnectionError,OSError):time.sleep(.05)
        else:raise RuntimeError('startup timeout')
        payload={'schema_version':2,'scenario':module.package.bundle.id+'_v2'}
        if 'work_language' in CreateSessionV2.model_fields:payload['work_language']=language
        created=request('POST','/sessions',payload);sid=created['session_id'];token=created['token']
        if created['binding']['workLanguage']!=language or created['binding']['scenarioHash']!=module.package.content_hash:
            raise RuntimeError('startup scenario/language binding mismatch')
        query='会议室预约入口' if language=='zh' else 'Where can I book a meeting room?'
        state=created['state']
        tested=request('POST',f'/sessions/{sid}/tests',{'schema_version':2,'request_id':'startup-c0','operation':'tests.create',
            'expected_version':state['business_seq'],'expected_workspace_revision':state['workspace_revision'],
            'payload':{'query':query,'config_version':0}},token)
        result=tested['result']['test']
        if result['config_ref']['config_version']!=0:raise RuntimeError('startup c0 mismatch')
        return {'mode':'real_loopback_HTTP_Gateway_SQLite','work_language':language,'steps':steps,
            'c0_status':result['status'],'c0_citations':result['citations'],'database':str(database),
            'worker_or_ui_qa':False,'token_saved':False}
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Rebind an unchanged W02 release to exact verified public input.')
    for name in ('source','output','contract-revision','scenario-revision','runtime-revision'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--smoke-database',required=True)
    parser.add_argument('--tooling-baseline',help='Full Git commit for an explicitly authorized rebind-tool-only migration')
    parser.add_argument("--protocol", choices=["scenario-release-v1"])
    args=parser.parse_args(argv)
    try:
        result=rebind(args.source,args.output,contract_revision=args.contract_revision,scenario_revision=args.scenario_revision,runtime_revision=args.runtime_revision,tooling_baseline=args.tooling_baseline,protocol=args.protocol)
        evidence=Path(args.output).parent/(Path(args.output).name+'-verification');evidence.mkdir()
        result['http_startup']=smoke_http(args.output,args.smoke_database,evidence)
        (evidence/'rebind.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ProtocolError,ValueError,OSError,RuntimeError) as error:
        print(json.dumps({'ok':False,'code':getattr(error,'code','rebind_failed'),'detail':str(error)}));return 1


if __name__=='__main__':raise SystemExit(main())
