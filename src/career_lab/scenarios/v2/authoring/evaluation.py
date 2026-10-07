"""Compose a fresh W02 bundle with exact, locally installed W05 evaluation files.

This offline authoring tool never mutates a source bundle, session or feedback.
Runtime source hashes still describe runtime-consumed W02 files; the complete
Git delivery digest additionally pins this build tool and inherited W05 inputs.
"""
from pathlib import Path
import hashlib,json
import yaml
from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.rebind import verified_public_input


def install_evaluation(source,destination,*,revision,w05_source_manifest,expected_manifest_sha256):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists() or destination==source:raise C.ProtocolError('evaluation_destination_not_fresh')
    if not revision:raise C.ProtocolError('new_revision_required')
    module=ScenarioModule(source);package=module.package
    if revision==package.bundle.revision:raise C.ProtocolError('new_revision_required')
    repo=Path(__file__).resolve().parents[5]
    raw=Path(w05_source_manifest).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_manifest_sha256:raise C.ProtocolError('evaluation_source_manifest_mismatch')
    frozen=json.loads(raw)
    required=('src/career_lab/evidence/v2/','src/career_lab/rubrics/v4/')
    checked={p:row for p,row in frozen.items() if p.startswith(required)}
    if not all(any(p.startswith(prefix) for p in checked) for prefix in required):raise C.ProtocolError('evaluation_source_manifest_incomplete')
    for path,row in checked.items():
        if hashlib.sha256((repo/path).read_bytes()).hexdigest()!=row['sha256']:raise C.ProtocolError('evaluation_source_mismatch')
    foundation=(repo/'docs/contracts/expansion-v3/manifest.json').read_bytes()
    contract='expansion-v3-'+hashlib.sha256(foundation).hexdigest();verified_public_input(repo,contract)
    # The only files copied are the source's already validated manifest members.
    source_hashes={ref.path:hashlib.sha256((source/ref.path).read_bytes()).hexdigest() for ref in package.bundle.files}
    destination.mkdir(parents=True)
    for ref in package.bundle.files:
        p=destination/ref.path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((source/ref.path).read_bytes())
    from career_lab.rubrics.v4.rubric_v2 import install_candidate,load_installed_policies,RUBRIC_REVISION,RULES_REVISION,policies as candidate_policies
    refs=install_candidate(destination/'evaluation')
    refs={key:ref.model_copy(update={'path':'evaluation/'+ref.path}) for key,ref in refs.items()}
    def put(path,value):
        p=destination/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        return C.FileRef(path=path,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    protocol=put('runtime/evaluation-protocol.json',{'mode':'advisory','installed':True,'owner':'W05',
        'semantic_status':'waiting_for_model','model_retries':0,'source_manifest_sha256':expected_manifest_sha256,
        'source_files':{**{path:row['sha256'] for path,row in checked.items()},
            **{str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'src/career_lab/scenarios/v2/evidence_ports').glob('*.py')}},
        'policies':[policy.to_dict() for policy in candidate_policies(work_language=package.locale)],
        'fact_adapter':'career_lab.scenarios.v2.evaluation_facts.ScenarioFactAdapter',
        'fact_adapter_factory':'career_lab.scenarios.v2.evidence_ports.store.create_store_fact_adapter'})
    evaluation=C.EvaluationBundle(id='w05-rubric-v2',revision=revision,rubric=refs['rubric'],rules=refs['rules'],graders=(),protocol=protocol,mode='advisory')
    evaluation_ref=put('runtime/evaluation.json',evaluation.model_dump(mode='json'))
    policies=load_installed_policies(destination,evaluation_ref,work_language=package.locale)
    if len(policies)!=14:raise C.ProtocolError('fourteen_policies_required')
    # Status changes only after real candidate files have loaded as 14 policies.
    put('rubric-reference.json',{'rules_revision':RULES_REVISION,'rubric_revision':RUBRIC_REVISION,'provider':'W05',
        'status':'installed_advisory_definitions','w02_produces_scores':False,'normal_v4_validated':False,
        'semantic_status':'waiting_for_model','criteria':[p.id for p in policies]})
    rules=dict(package.rules);rules['revision']=revision
    (destination/'scenario.yaml').write_text(yaml.safe_dump(rules,allow_unicode=True,sort_keys=True))
    runtime=C.RuntimeBundle.model_validate_json((destination/'runtime/bundle.json').read_bytes())
    put('runtime/bundle.json',runtime.model_copy(update={'revision':'evaluation-installed-'+revision+'-'+package.locale}).model_dump(mode='json'))
    paths=set(source_hashes)|{ref.path for ref in refs.values()}
    files=tuple(C.FileRef(path=p,sha256=hashlib.sha256((destination/p).read_bytes()).hexdigest(),media_type='text/markdown' if p.endswith('.md') else 'application/json') for p in sorted(paths))
    bundle=package.bundle.model_copy(update={'revision':revision,'files':files,'private_files':tuple(sorted(set(package.bundle.private_files)|{ref.path for ref in refs.values()}))})
    (destination/'manifest.json').write_text(bundle.model_dump_json(indent=2)+'\n')
    installed=ScenarioModule(destination)
    if any(hashlib.sha256((source/p).read_bytes()).hexdigest()!=sha for p,sha in source_hashes.items()):raise C.ProtocolError('evaluation_source_bundle_changed')
    changed=[p for p,sha in source_hashes.items() if hashlib.sha256((destination/p).read_bytes()).hexdigest()!=sha]
    allowed={'scenario.yaml','runtime/bundle.json','runtime/evaluation.json','runtime/evaluation-protocol.json','rubric-reference.json'}
    if set(changed)-allowed:raise C.ProtocolError('evaluation_authored_content_changed')
    return {'source_scenario_hash':package.content_hash,'installed_scenario_hash':installed.package.content_hash,'locale':package.locale,
        'output':str(destination),'evaluation':installed.bindings.evaluation.model_dump(mode='json'),
        'criteria':[p.id for p in policies],'rubric_revision':RUBRIC_REVISION,'rules_revision':RULES_REVISION,
        'verified_w05_files':checked,'source_manifest_sha256':expected_manifest_sha256,'contract_revision':contract,
        'authored_content_unchanged':True,'source_unchanged':True,'changed_files':changed,'added_files':[ref.path for ref in refs.values()],
        'worker_persistence_validated':False,'normal_v4_validated':False,'online_model':False}
