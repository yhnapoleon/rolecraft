"""Export a candidate freeze; the manifest's exact SHA256 is its revision."""
from pathlib import Path
import argparse,json,hashlib,inspect
from career_lab.contracts.v2.discovery import public_models,REQUEST_MODELS
from career_lab.contracts.v2.examples import sample_model

CONSUMERS={
 'W02':['ScenarioBundle','RoleSpecV2','FactV2','MaterialV2','SourceFragment','AssistantConfig','EffectiveConfig','TestRequestV2','TestResultV2','BusinessRequest','BusinessDecision','ActionInput','ObjectWrite','EventDraft','Command'],
 'W03':['WorkspaceTask','WorkProductVersion','ProductShare','WorkspaceImport','ImportResult','LegacyProductImport','TaskCreate','TaskPatch','ProductCreate','ProductEdit','ShareCreate','ShareUpdate','ObjectWrite','Command'],
 'W04':['RoleContext','DisclosureRecord','SourceFragment','JobContextSnapshot','TurnInput','ApprovalInput','BusinessRequest','BusinessDecision','ProductShare'],
 'W05':['EvidencePackageV2','FeedbackV2','ReviewRequest','RevisionCycle','SubmissionV2','ReviewInput','SubmitInput','BeginRevisionInput','EvaluationBundle','RuleBound','TerminalEvaluation','JobRequest','JobEnvelope'],
 'W06':['AuthContext','Executor','DelegationInput','DelegationGrant','DelegationRevoke','Observation','ToolSchema','Command','JobEnvelope','ResourcePage'],
 'W07':['DatasetRecordV2','AnnotationV2','AnnotationPass','LegacyAnnotation','SplitManifest','Lineage','Provenance','RelationInput','CriterionInput','TrajectoryInput','DecisionPointInput','SnapshotExport'],
 'W08':['ModelBundle','ModelPrediction','RuntimeBundle','EvaluationBundle','CandidateBundle','FileRef','SourceIdentity','TestCampaign'],
 'W09':['ActionProposal','Observation','BeliefState','RunManifest','Budget','ModelAttemptUsage','Trajectory','SnapshotExport','RestoreResult','JobContextSnapshot'],
 'W10':['ActionBoundary','BranchManifest','SnapshotExport','RestoreResult','Trajectory','Diagnosis','TerminalEvaluation'],
 'W11':['ScenarioBundle','SplitManifest','Lineage','TestCampaign','FileRef'],
 'W12':['DecisionRequest','DecisionResult','SkillSpec','SkillBundle','CandidateBundle','RuntimeBundle','EvaluationBundle','TestCampaign'],
 'W13':['EngineerPack','EngineerSubmission','RegressionReport','AssistantConfig','ObjectRef'],
 'W14':['Command','AuthContext','TransactionResult','ErrorResponse','V2Response'],
 'W15':['AnnotationV2','FeedbackV2','EvaluationBundle','Provenance'],
}

CONSUMERS['W02'] += ['BusinessBasis','ScenarioStateV2','MaterialMetadata','TestExecutionMetadata','RetrievedChunk','ExternalReference']
CONSUMERS['W03'] += ['ProductAdopt','TaskBatch','ImportConflict','ImportVersionMap','PublicTransactionResult']
CONSUMERS['W04'] += ['ObservedFragment','ProviderRequest','ProviderResult','ProviderCapabilities','ActualConsumption']
CONSUMERS['W06'] += ['StepResult','ObservedFragment','PublicState','PublicEvent','PublicTransactionResult','ActualConsumption']
CONSUMERS['W07'] += ['ExternalReference','ObservedFragment','ActualConsumption']
CONSUMERS['W08'] += ['ProviderRequest','ProviderReply','ProviderResult','ProviderCapabilities']
CONSUMERS['W09'] += ['StepResult','ProviderRequest','ProviderResult','ProviderCapabilities','ActualConsumption','PublicTransactionResult']
CONSUMERS['W10'] += ['ExternalReference','ObservedFragment']
CONSUMERS['W12'] += ['ProviderRequest','ProviderResult','ProviderCapabilities','ActualConsumption']
CONSUMERS['W13'] += ['TestExecutionMetadata','RetrievedChunk','BusinessBasis']
CONSUMERS['W14'] += ['PublicState','PublicEvent','PublicTransactionResult']

CONSUMERS['W04'] += ['PublicDisclosureSource','PublicDisclosureRecord']
CONSUMERS['W06'] += ['PublicDisclosureSource','PublicDisclosureRecord','RequestResultQuery','RequestJobResult','RequestResult']
CONSUMERS['W09'] += ['RequestResultQuery','RequestJobResult','RequestResult','ProviderReceipt']
CONSUMERS['W07'] += ['ProviderReceipt','DatasetMetadataV2','DatasetSnapshotMetadata']
CONSUMERS['W08'] += ['ProviderReceipt','DatasetMetadataV2','DatasetSnapshotMetadata']
CONSUMERS['W12'] += ['ProviderReceipt']
for consumer in ('W04','W05','W06','W09','W14'):
    CONSUMERS[consumer] += ['JobRefreshRecord']

def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def export(root:Path,output:Path):
    from career_lab.api.app import create_app
    output.mkdir(parents=True,exist_ok=True)
    models=public_models();entries={}
    for name,model in models.items():
        example=sample_model(model)
        dump(output/'schemas'/f'{name}.json',model.model_json_schema())
        dump(output/'examples'/f'{name}.json',example.model_dump(mode='json'))
        entries[name]={'owner':'W01','schema_version':2,'consumers':[wp for wp,names in CONSUMERS.items() if name in names] or ['shared-primitive'],'schema':f'schemas/{name}.json','schema_sha256':sha(output/'schemas'/f'{name}.json'),'example':f'examples/{name}.json','example_sha256':sha(output/'examples'/f'{name}.json'),'tests':['tests/contracts/expansion_v3/test_freeze.py::test_all_frozen_models_examples_and_openapi_agree']}
    (output/'examples/files').mkdir(exist_ok=True);(output/'examples/files/payload.json').write_text('{}')
    (output/'examples/labels').mkdir(exist_ok=True);(output/'examples/labels/example.json').write_text('{}')
    app=create_app('sqlite:///:memory:');dump(output/'openapi.json',app.openapi());app.state.store.close()
    # Only implementation files here: the complete source tree is identified by the delivery receipt.
    files=set((root/'src/career_lab/contracts').rglob('*.py'))
    files|={root/p for p in ['src/career_lab/api/app.py','src/career_lab/api/modules.py','src/career_lab/api/v2_routes.py','src/career_lab/storage/v2_tables.py','src/career_lab/storage/v2_store.py','src/career_lab/storage/v2_jobs.py','src/career_lab/storage/v2_snapshot.py','src/career_lab/storage/v2_lifecycle.py','src/career_lab/storage/v2_remap.py','src/career_lab/jobs/worker.py','src/career_lab/jobs/repository.py','src/career_lab/rubrics/registry.py']}
    source={str(p.relative_to(root)):sha(p) for p in sorted(files)}
    errors=[]
    import re
    for p in files:
        errors.extend(re.findall(r"ProtocolError\(['\"]([^'\"]+)",p.read_text()))
    errors.extend(['job_result_identity_conflict','job_execution_failed'])
    dump(output/'errors.json',{'schema_version':2,'codes':sorted(set(errors)),'http_policy':{'401':'missing/invalid authentication','403':'capability/scope denied','404':'not found or unauthorized object','409':'version/hash/identity conflict','422':'invalid request/business precondition','503':'uninstalled/unavailable module or invalid server result'}})
    manifest={'schema_version':1,'status':'frozen_candidate_pending_independent_review','owner':'rolecraft-032-foundation','base_commit':'80cf1f6189cd25610d609f44283ff9668582d759','input_contract_revision':'preflight','v1_dirty_included':False,'source_files':source,'schemas':entries,'consumer_interfaces':CONSUMERS,'request_payloads':REQUEST_MODELS,'openapi':{'path':'openapi.json','sha256':sha(output/'openapi.json')},'errors':{'path':'errors.json','sha256':sha(output/'errors.json')},'boundaries':['This is W01 common foundation, not implemented W02-W15 business modules.','v4 semantic engine, paid provider/model quality, full product QA and research results are not claimed.','Existing v1 remains separate; internal snapshot/restore never appears in learner routes.'],'documents':{name:{'path':name,'sha256':sha(output/name)} for name in ['compatibility.md','module-interfaces.md','consumer-request-resolution.json'] if (output/name).is_file()},'previous_draft':'draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e','changes_since_draft':['Command.schema_version and CreateSessionV2.schema_version are now required for explicit envelopes.','Added ModelPrediction; ModelBundle validates ordered task label vocabulary.','G2v compares evidence sets independent of ordering, requires reordered evidence only when more than one item exists.','API/storage/atomic job queue/isolated restore implementations and their public models are now included.','AssistantConfig adds finite min_score (initial 0.35, uncalibrated), freshness_guard none/warn/fallback and manual_domains; TestResultV2 requires execution metadata and exact config_ref.', 'BusinessRequest requires immutable proposed/applied BusinessBasis. ScenarioStateV2 is private transaction state, not an observation.', 'Observation.visible_sources now requires ObservedFragment with explicit learner acquisition/audience; catalog is separate. StepResult/ObservedStep bind actual request identities, points and executor.', 'AnnotationPass successful passes require actual invocation identity; G2v also requires separate context IDs, independence method/reason and truthful evidence order policy.', 'AuthContext/DelegationGrant adds explicit create_under_tasks; derived results remain tied to the actual executor, unrelated existing artifacts are not inherited.', 'SnapshotExport now includes immutable external source references; restore supports exact target/idempotency and structured action remapping. Regenerate draft snapshots under the new revision.', 'WorkProduct/import DTOs retain intent/refs, test_compare, review_focus distinct from direction, source return identity, adoption and version conflicts.', 'PublicTransactionResult is the HTTP/worker wire result; TransactionResult remains the internal authoritative record.']}
    manifest['previous_contract_revision']='expansion-v3-5a117a51493f5bb5d8f96f711d78466f82550935d803c312d277cfac045ff6a4'
    manifest['review_fixes']={
        'R01':'Actual WorkerClaim is passed and fenced at entry/commit; no lease borrowing.',
        'R02':'Fixed-subject derived FeedbackV2 may persist on submitted; ordinary writes stay forbidden.',
        'R03':'Model-directed remapping leaves arbitrary text and legacy provenance unchanged.',
        'R04':'Kind/namespace ID keys distinguish local and external objects; mapped graph is validated.',
        'R05':'PublicDisclosureRecord strips/rejects raw source quote/span and checks scope/time.',
        'R06':'Restore replay token must match a real usable saved owner credential.',
        'R07':'Built-in authenticated read-only request_id query returns real request/job/effect links.',
        'R08':'Received provider body/usage preserved independently of invalid/missing actual identity.',
        'R09':'Accepted single-pass G2 final equals that actual successful decision.'}
    manifest['review_fixes'].update({
        'C-W01-01':'Snapshot-bound asynchronous inputs; declared head/state freshness, actual claim and current authorization checked atomically. needs_context parks once; explicit idempotent refresh preserves original subject/command and immutable context history.',
        'C-W01-02':'RoleContext reads reject non-research learner and historical reserved role IDs; only a trusted matching role reader or internal research capability can read. Reserved role credentials cannot be minted. New writes remain private.',
        'C-W01-03':'Withdrawn route-deleting candidate is not included. Public integration must use Gateway slots; W03 adapter remains separate integration work.',
        'P2-related':'Stable worker error codes; scoped v2 jobs GET; reverse-order object/resolver collision rejected.',
    })
    manifest['review_fixes']['C-W01-04']='Ordinary jobs require an active open current cycle before handler and at commit. Explicit refresh preserves question/command while moving context to the current cycle; fixed-subject feedback remains allowed. Deterministic failures stop; parked reason/history is queryable; research writes denied.'
    manifest['publication_package']='W14'
    manifest['input_contract_revision']='draft-core-wiring-r6-20261007'
    manifest['previous_contract_revision']='expansion-v3-2e4b5f05138ae995320db1ae21ca6f5d7a8d63bf5ec3e19346a088510cb0515c'
    manifest['integration_changes']={'W02-S06':'Opt-in contextual resolver gets authoritative persisted-window ScenarioState; legacy four-argument behavior retained.','W02-S07':'Verified command/result references are atomically anchored for read-request recovery.','W03-GR02-partial':'Validated LegacyProvenance.raw remains inert during reference/time traversal; receipt and preview interfaces remain pending.'}
    manifest['boundaries'].append('W02 runtime is still pinned to r3; controlled source-port regressions do not close actual ScenarioModule HTTP acceptance. Consumers must migrate through coordinator-fixed inputs.')
    manifest['review_fixes']['031-W01-REPLAY-SCOPE-01']='execute, replay and request/job GET share current scope and visibility checks, including historical result-only/unanchored references; no handler/resolver rerun.'
    manifest['review_fixes']['W02-S09']='Recovery and idempotent replay select event projector only by persisted action and trusted installed registration; preserve safe fields without handler/resolver rerun.'
    manifest['previous_contract_revision']='expansion-v3-d5aa8ca0d6532afe1165511e1403455cde39026f7d555decdd1840038849e0bb'
    manifest['integration_changes']['W07-W08-data-slice']='Explicit fixture bucket; separate metadata projection with language/provenance/lineage/snapshot identities; paired pending/accepted tier checks and historical-evidence-time-v1 validation.'
    manifest['previous_contract_revision']='expansion-v3-722c39cc0906f1b1a8e741ad234321491ee85198e6714b5a52d99e1e9262dd37'
    manifest['integration_changes']['W07-W08-empty-joint-target']='Accepted evaluable conclusions require every acceptable evidence set nonempty unless label is INSUFFICIENT or NOT_APPLICABLE; non-evaluable cases remain valid without evidence.'
    dump(output/'manifest.json',manifest)
    revision='expansion-v3-'+sha(output/'manifest.json');(output/'revision.txt').write_text(revision+'\n')
    return {'models':len(models),'revision':revision,'manifest':str(output/'manifest.json')}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path.cwd());parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(export(args.root.resolve(),args.output.resolve()),ensure_ascii=False))
if __name__=='__main__':main()
