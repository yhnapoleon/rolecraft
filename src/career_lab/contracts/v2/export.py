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
CONSUMERS['W06'] += ['DelegationJobCapacity','OperationAvailability']
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
CONSUMERS['W03'] += ['ImportedTaskSource','WorkspaceImportReceipt','WorkspaceProductRead','WorkspaceProductPage','WorkspaceSharePage']
CONSUMERS['W05'] += ['FeedbackReadBoundary']
CONSUMERS['W05'] += ['FeedbackReferenceCheck','FeedbackActivity','FeedbackActivityCount','FeedbackActivityWindow','VerifiedFactsSnapshot','HistoricalResponsibilityFinding','HistoricalResponsibilitiesSnapshot','FeedbackResponseRecord','FeedbackResponseCreate']
CONSUMERS['W04'] += ['RoleAuditScope','RoleAuditReceivedShare','RoleAuditMemory','RoleGenerationAudit']
for consumer in ('W04','W05','W06','W09','W14'):
    CONSUMERS[consumer] += ['JobRefreshRecord']

def integration_example(model):
    from career_lab.contracts.v2 import (ImportedTaskSource,WorkspaceImportReceipt,WorkspaceProductRead,WorkspaceProductPage,WorkspaceSharePage,WorkProductVersion,LegacyProvenance,ImportResult,ObjectRef,VersionPoint,Executor,digest)
    from career_lab.contracts.v2.examples import STAMP
    from career_lab.contracts.v2 import FeedbackReferenceCheck,VerifiedFactsSnapshot,FeedbackResponseRecord
    from career_lab.contracts.v2 import RoleAuditScope,RoleAuditReceivedShare,RoleAuditMemory,RoleGenerationAudit,DisclosedFragment,EvidenceRefV2,ProviderMessage
    scope=RoleAuditScope(capabilities=('read','act'),actor_id='learner',executor=Executor(id='human:example',kind='human'),credential_id='example')
    fragment=DisclosedFragment(ref=EvidenceRefV2(session_id='example',kind='product',object_id='product',version=1,observed_at_seq=0),text='Synthetic private receipt.',channel='received_share',verification='verified')
    if model is RoleAuditScope:return scope
    if model is RoleAuditReceivedShare:return model(share=ObjectRef(session_id='example',kind='share',object_id='share',version=1),product=ObjectRef(session_id='example',kind='product',object_id='product',version=1),role_id='tech_lead',received_at=sample_model(VersionPoint),fragment=fragment)
    if model is RoleAuditMemory:return model(fragment=fragment,role_id='tech_lead')
    if model is RoleGenerationAudit:
        message=ProviderMessage(role='system',content='Synthetic private prompt; no model call occurred.')
        return model(job_id='example-job',job_attempt=1,request=ObjectRef(session_id='example',kind='role_turn',object_id='turn',version=1),scope=scope,prompt_messages=(message,),prompt_hash=digest([{'role':message.role,'content':message.content}]),history_revision=digest('synthetic history'))
    from career_lab.contracts.v2 import FeedbackReadBoundary
    if model is FeedbackReadBoundary:return model(path='/business_response',content_hash=digest('Synthetic bounded text'),dependencies=(ObjectRef(session_id='example',kind='product',object_id='product',version=1),))
    from career_lab.contracts.v2 import DelegationJobCapacity,OperationAvailability
    if model is DelegationJobCapacity:return model(delegation_id='example',max_active_jobs=2,active_jobs=0,available_slots=2,observed_at=STAMP)
    if model is OperationAvailability:return model(name='example',installed=False,ready=False,unavailable_code='module_unavailable')
    if model is FeedbackReferenceCheck:return model(submitted_reference_hash=digest('synthetic missing reference'),status='unavailable')
    if model is VerifiedFactsSnapshot:return model(subject=ObjectRef(session_id='example',kind='product',object_id='product',version=1),status='unknown',as_of=None,requested_at=sample_model(VersionPoint),captured_at=sample_model(VersionPoint),source_snapshot_hash=digest('synthetic unverified snapshot'),summary=('Formation point is unknown.',))
    if model is FeedbackResponseRecord:return model(id='response',session_id='example',feedback=ObjectRef(session_id='example',kind='feedback',object_id='feedback',version=1),kind='objection',text='Please reconsider this interpretation.',recorded_at=sample_model(VersionPoint),executor=Executor(id='human:example',kind='human'))
    if model is WorkspaceProductRead:return model.model_validate(sample_model(WorkProductVersion).model_dump(mode='json')|{'visibility':None})
    if model is ImportedTaskSource:
        source=sample_model(LegacyProvenance).model_copy(update={'original_kind':'task'})
        return model(task=ObjectRef(session_id='example',kind='task',object_id='task',version=1),source=source)
    if model is WorkspaceImportReceipt:
        result=ImportResult(package_id='example',mode='apply',id_map={},unresolved=(),as_of=VersionPoint(business_seq=0,workspace_revision=1,storage_revision=1),applied=True)
        return model(id='receipt',session_id='example',package_id='example',package_hash=digest([]),source_schema='browser-v1',source_session_id='legacy',fingerprint=digest('synthetic-example'),result=result,executor=Executor(id='human:example',kind='human'),created_at=STAMP)
    if model is WorkspaceProductPage:return model(items=(),shares=(),sharing_complete=True,as_of=sample_model(VersionPoint))
    if model is WorkspaceSharePage:return model(items=(),sharing_complete=True,as_of=sample_model(VersionPoint))
    return sample_model(model)

def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def export(root:Path,output:Path):
    from career_lab.api.app import create_app
    output.mkdir(parents=True,exist_ok=True)
    models=public_models();entries={}
    for name,model in models.items():
        example=integration_example(model)
        dump(output/'schemas'/f'{name}.json',model.model_json_schema())
        dump(output/'examples'/f'{name}.json',example.model_dump(mode='json'))
        entries[name]={'owner':'W01','schema_version':2,'consumers':[wp for wp,names in CONSUMERS.items() if name in names] or ['shared-primitive'],'schema':f'schemas/{name}.json','schema_sha256':sha(output/'schemas'/f'{name}.json'),'example':f'examples/{name}.json','example_sha256':sha(output/'examples'/f'{name}.json'),'tests':['tests/contracts/expansion_v3/test_freeze.py::test_all_frozen_models_examples_and_openapi_agree']}
    (output/'examples/files').mkdir(exist_ok=True);(output/'examples/files/payload.json').write_text('{}')
    (output/'examples/labels').mkdir(exist_ok=True);(output/'examples/labels/example.json').write_text('{}')
    app=create_app('sqlite:///:memory:');dump(output/'openapi.json',app.openapi());app.state.store.close()
    # Only implementation files here: the complete source tree is identified by the delivery receipt.
    files=set((root/'src/career_lab/contracts').rglob('*.py'))
    files|={root/p for p in ['src/career_lab/api/app.py','src/career_lab/api/workspace_integration.py','src/career_lab/api/feedback_integration.py','src/career_lab/api/role_snapshot.py','src/career_lab/api/private_roles.py','src/career_lab/api/modules.py','src/career_lab/api/v2_routes.py','src/career_lab/storage/v2_tables.py','src/career_lab/storage/v2_store.py','src/career_lab/storage/v2_jobs.py','src/career_lab/storage/v2_snapshot.py','src/career_lab/storage/v2_lifecycle.py','src/career_lab/storage/v2_remap.py','src/career_lab/jobs/worker.py','src/career_lab/jobs/repository.py','src/career_lab/rubrics/registry.py']}
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
    manifest['previous_contract_revision']='expansion-v3-81f4855d5cdf8c601c6b09d7b350b11dcda5ed156e2d801d8e542fa197718c85'
    manifest['integration_changes']['W07-W08-semantic-consensus']='Only independent-pass consensus uses semantic_decision_key; G2/G2v final remains bound by the full normalized decision_key to the actual selected pass.'
    manifest['previous_contract_revision']='expansion-v3-deb8023ca664946f45c52692c65e3524703d77194c5100e0ee42939ae26cff4b'
    manifest['integration_changes']['W04-S02-P0']='Legacy role_reply audit fields are denied to learner/Agent on common reads and replay; new public spoken evidence remains readable; research audit preserves history. No role generation activation is implied.'
    manifest['previous_contract_revision']='expansion-v3-3f2ca36e4275f2ff8d8e074e91231509116c054df8750d157682e8486354a9de'
    manifest['integration_changes']['W03-common-import-sharing']='Read-only import preview and atomic receipt; operation-local reference checks; exact-version share pages; trusted removal cascade without scope expansion; queued share reads rechecked.'
    manifest['integration_changes']['W02-projector-registration']='Conflicting declared public action/projector registrations are rejected before installation.'
    manifest['boundaries']=[x for x in manifest['boundaries'] if not x.startswith('W02 runtime is still pinned')]
    manifest['boundaries'].append('W02 owned b821 remains exact c2; coordinator rebind required for cumulative business runtime. W03 owner must adopt removal_cascade port for restricted removals; role private generation and native UI remain pending.')
    manifest['previous_contract_revision']='expansion-v3-0aa98d5ebec838fd0e2b56a9eed2f32a51c6ec94dff526712083a589d858e510'
    manifest['integration_changes']['W05-factual-persistence']='Optional typed factual/history/rule sections persist in FeedbackV2; legacy absent means not recorded. Exact feedback follow-ups append immutable objects without changing submitted/paused business state; new reviews link prior responses and explicit decisions.'
    manifest['boundaries'].append('W05 evaluator-to-trusted-source adapter and native feedback UI remain pending. Controlled persistence tests do not prove actual production history or model quality.')
    manifest['previous_contract_revision']='expansion-v3-d6277a2b850369a86d4f1c169464ea521587066071d899fd2d43326d178bd076'
    manifest['integration_changes']['W04-fixed-role-read']='Private audit DTOs and exact recorded job-window role projection; receipt/source history checked; ordinary view has no authority; private generation sink/activation still unavailable.'
    manifest['integration_changes']['W05-W03-remapping']='FeedbackResponseCreate.feedback_id and ResourcePage feedback/response/import identities remap by declared kind, leaving text and historical opaque provenance unchanged.'
    manifest['boundaries'].append('Role snapshot tests use controlled catalogs/audits. No production private writer, failure-attempt sink, event-reference persistence or full role generation is claimed.')
    manifest['previous_contract_revision']='expansion-v3-d6277a2b850369a86d4f1c169464ea521587066071d899fd2d43326d178bd076'
    manifest['integration_changes']['031-C8-01']='Store read/query/view/job-view and cached request/replay share feedback subject authorization and transient support projection; hidden quote/title/ID/derived prose removed; original records unchanged.'
    manifest['integration_changes']['original-source-protection']='test_freeze enumerates only BASE existing scenarios; no v2 baseline rewrite and no test exclusion needed.'
    manifest['integration_changes']['W03-product-cycle-replay']='Only an exact saved authorized product DTO cycle field is structural metadata. Explicit cycle sources, direct cycle objects and unproven DTOs retain scope checks; no scope grant is widened.'
    manifest['previous_contract_revision']='expansion-v3-5edc886f3e862b53b11c19dbcf9955042d02c7ff18dd4ecf51fee8bb3d7c108c'
    manifest['previous_contract_revision']='expansion-v3-3d096f2715f31fc99d48862be10e9f78e414199d241f12f6dbf84d8443038d49'
    manifest['integration_changes']['W04-private-writer']='Actual worker-bound private port, atomic public reply/private audit, fenced internal attempt journal, original Agent attribution without scope expansion; factory stays closed by default pending repaired W04 input.'
    manifest['integration_changes']['W04-private-reply-whitelist']='Public/historical RoleReply fields are restricted to the pinned public DTO regardless of permissive registrations; private carrier and unknown fields remain unreadable to learner/Agent.'
    manifest['integration_changes']['role-event-references']='Actual event provenance is scope/audience/window validated and remapped in the event namespace; no parallel event store.'
    manifest['boundaries'].append('Successful generation checks use controlled non-network models and catalog. W04 new private-ID fix and real business cumulative acceptance are still required; no production activation implied.')
    manifest['previous_contract_revision']='expansion-v3-ffa9cb25c4a9d74c670c8cd03aac284cb6a23c6bea04192dc0c6d3da6391532a'
    manifest['integration_changes']['feedback-segment-scope']='Server-only complete input traces bind exact content hashes and dependencies per segment; fully authorized finite-scope readers retain proved text, missing or hidden dependencies degrade only affected parts.'
    manifest['integration_changes']['submitted-evidence-status']='New response evidence is explicitly user_submitted_unverified (or none_submitted); legacy absence stays unknown. Linking never claims quote or semantic verification.'
    manifest['previous_contract_revision']='expansion-v3-41a21baa9f86c9e7ee7d17b07aa0c55eb5b0dd24b6f04c8a402ec65f72ddf05c'
    manifest['integration_changes']['W06-public-queue-capacity']='Persisted per-credential 1–2 job policy; existing jobs counted in locked transactions for public enqueue/refresh, not process memory. Native repository enqueue/failed retry still requires coordinator scope release.'
    manifest['integration_changes']['operation-readiness']='Installed and ready are distinct; closed registered operations return stable unavailable before public dispatch. Auth/delegation capabilities remain independent.'
    dump(output/'manifest.json',manifest)
    revision='expansion-v3-'+sha(output/'manifest.json');(output/'revision.txt').write_text(revision+'\n')
    return {'models':len(models),'revision':revision,'manifest':str(output/'manifest.json')}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path.cwd());parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(export(args.root.resolve(),args.output.resolve()),ensure_ascii=False))
if __name__=='__main__':main()
