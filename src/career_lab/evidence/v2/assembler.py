"""Fixed historical evidence, with rule facts independent of the model budget."""
from career_lab.contracts.v2.core import AuthContext, ObjectRef, EvidenceRefV2, ProtocolError, VersionPoint, canonical, digest
from career_lab.contracts.v2.evaluation import EvidencePackageV2, CandidateEvidenceV2
from .ports import EvidenceReader, RuleSnapshot, CriterionPolicy
from .availability import unavailable,SAFE_REASON
from .localization import message,validate_language,policy_description
import re

PURPOSES={'draft':'exploration','exploration':'exploration','explore':'exploration','freeform':'exploration',
          '探索笔记':'exploration','自由作品':'exploration','option':'option','comparison':'option','方案比较':'option',
          'plan':'plan','test_plan':'plan','测试计划':'plan','commitment':'commitment','commit':'commitment','试点决定':'commitment',
          'result':'result','result_report':'result','结果报告':'result','pilot decision':'commitment','test plan':'plan','result report':'result'}


def base_ref(ref:ObjectRef) -> ObjectRef:
    return ObjectRef(**{k:getattr(ref,k) for k in ['session_id','kind','object_id','version','config_version']})


def purpose_of(purpose):
    key=re.sub(r'[\s_-]+',' ',purpose.strip().casefold())
    aliases={re.sub(r'[\s_-]+',' ',name.casefold()):code for name,code in PURPOSES.items()}
    return aliases.get(key)


def product_text(product,*,work_language='zh') -> str:
    """Reader-side text projection; never include private legacy/draft metadata.

    A supplied body remains verbatim. Structured-only work is rendered as its
    actual content, without a kind label that could become an answer whitelist.
    """
    if product.content.strip():return product.content
    p=product.structured_payload
    if p is None:return product.content
    if p.type=='text':return p.body
    if p.type=='plan':return '\n\n'.join(k+'\n'+v for k,v in p.sections.items())
    if p.type=='options':return '\n\n'.join('\n'.join([o.title,o.rationale,*o.tradeoffs]) for o in p.options)
    if p.type=='test_plan':return '\n\n'.join(c.query+(message(work_language,'\n预期（待验证）：')+c.declared_expected if c.declared_expected else '') for c in p.cases)
    if p.type=='investigation':return '\n\n'.join(x for x in [p.question,*[b.text for b in p.blocks],(message(work_language,'作者判断（待核对）：')+p.review_note if p.review_note else '')] if x)
    raise ProtocolError('unsupported_product_projection')


def applicable(policy:CriterionPolicy,purpose:str,decision:str|None):
    stage=purpose_of(purpose)
    if stage is None:return 'undetermined'
    if stage not in policy.purposes:return 'not_applicable'
    if policy.launch_only:
        if stage=='result':return 'not_applicable'  # Exact claims/actions are assessed separately.
        if decision in {'no_go','defer_with_conditions'}:return 'not_applicable'
        if decision not in {'launch','launch_narrow'}:return 'undetermined'
    return 'applicable'


def model_input(item:EvidencePackageV2) -> dict:
    """Strict allowlist: never send rule_context or arbitrary metadata to a model."""
    public_context={}
    if item.rule_context.get('mechanism','').startswith('v2.'):
        decision=item.rule_context.get('decision')
        public_context={'declared_decision':decision if decision in {'launch','launch_narrow','no_go','defer_with_conditions'} else None}
    return {**public_context,'criterion':item.criterion,'claim':item.claim,'purpose':item.purpose,
        'as_of':item.as_of.model_dump(mode='json'),'applicability':item.applicability,
        'subjects':[base_ref(r).model_dump(mode='json') for r in item.subjects],
        'candidate_evidence':[{'id':c.id,'text':c.text,
            'observed_at_seq':c.ref.observed_at_seq,'valid_from_seq':c.ref.valid_from_seq,
            'valid_until_seq':c.ref.valid_until_seq} for c in item.candidate_evidence],
        'rule_bound':item.rule_bound.model_dump(mode='json') if item.rule_bound else None,
        'completeness':item.completeness}


class EvidenceAssemblerV2:
    def __init__(self,reader:EvidenceReader,model_bytes:int=16000,*,work_language='zh'):
        if model_bytes<256:raise ValueError('model_bytes must be at least256')
        self.reader,self.model_bytes=reader,model_bytes
        self.work_language=validate_language(work_language)

    def resolve(self,auth,ref,as_of):
        if ref.session_id!=auth.session_id:raise ProtocolError('not_found',status=404)
        source=self.reader.read(auth,ref,as_of)
        if source.created_at is None:raise ProtocolError('source_time_unknown')
        if base_ref(source.ref)!=base_ref(ref):raise ProtocolError('evidence_version_mismatch',status=409)
        if any(getattr(source.created_at,k)>getattr(as_of,k) for k in ['business_seq','workspace_revision','storage_revision']):
            raise ProtocolError('future_evidence')
        if source.ref.observed_at_seq>as_of.business_seq or source.ref.valid_from_seq>as_of.business_seq:
            raise ProtocolError('future_evidence')
        if isinstance(ref,EvidenceRefV2):
            if ref.observed_at_seq>as_of.business_seq or ref.valid_from_seq>as_of.business_seq:raise ProtocolError('future_evidence')
            if ref.observed_at_seq!=source.ref.observed_at_seq or ref.valid_from_seq!=source.ref.valid_from_seq or ref.valid_until_seq!=source.ref.valid_until_seq:
                raise ProtocolError('evidence_time_mismatch')
        chosen=ref if isinstance(ref,EvidenceRefV2) and ref.quote is not None else source.ref
        text=source.text
        if chosen.quote is not None:
            if chosen.span_start is not None:
                if chosen.span_end>len(text) or text[chosen.span_start:chosen.span_end]!=chosen.quote:raise ProtocolError('evidence_quote_mismatch')
            elif chosen.quote not in text:raise ProtocolError('evidence_quote_mismatch')
            text=chosen.quote
        else:
            chosen=source.ref.model_copy(update={'span_start':0,'span_end':len(text),'quote':text}) if text and source.quote_scope=='whole_text' else source.ref
        return SourceCandidate(chosen,text,source.created_at)

    def assemble(self,*,auth:AuthContext,subject_id:str,subjects:tuple[ObjectRef,...],
                 evidence_refs:tuple[EvidenceRefV2,...],purpose:str,decision:str|None,
                 as_of:VersionPoint,policy:CriterionPolicy,snapshot:RuleSnapshot,
                 expected_refs:tuple[EvidenceRefV2,...]=(),question:str='',anchor_mode:str='product_version',requested_at:VersionPoint|None=None) -> EvidencePackageV2:
        work_language=self.work_language
        if snapshot.as_of!=as_of:raise ProtocolError('rule_snapshot_time_mismatch',status=409)
        if not subjects:raise ProtocolError('review_subject_required')
        candidates={};subject_refs=[];missing=[];subject_points=[];source_issues=[]
        disclosed={digest(base_ref(r)) for r in evidence_refs}
        def add(ref,required=False):
            try:c=self.resolve(auth,ref,as_of)
            except (KeyError,ProtocolError) as error:
                if required:
                    if isinstance(error,KeyError):raise ProtocolError('subject_missing',status=404) from None
                    raise
                if not unavailable(error):raise
                # Only refs already explicitly provided with the work may be
                # echoed. Never expose private ledger source IDs, quotes or titles.
                if digest(base_ref(ref)) in disclosed:missing.append(base_ref(ref))
                if not source_issues:source_issues.append({'status':'pending','reason':message(work_language,SAFE_REASON)})
                return None
            candidate=CandidateEvidenceV2(id='e-'+digest(c.ref),text=c.text,ref=c.ref)
            candidates[candidate.id]=candidate
            return c.ref
        for ref in subjects:
            subject_points.append(self.reader.read(auth,ref,as_of).created_at)
            subject_refs.append(add(ref,True))
        if anchor_mode not in {'product_version','submission'}:raise ProtocolError('invalid_evaluation_anchor')
        if anchor_mode=='product_version' and any(point!=as_of for point in subject_points):
            raise ProtocolError('subject_point_mismatch',status=409)
        if requested_at is not None and any(getattr(as_of,k)>getattr(requested_at,k) for k in ['business_seq','workspace_revision','storage_revision']):
            raise ProtocolError('future_subject_anchor')
        for ref in evidence_refs:add(ref)
        for ref in expected_refs:add(ref)
        facts={};fact_refs={};seen_facts=set()
        for fact in snapshot.facts:
            if fact.name in seen_facts:raise ProtocolError('duplicate_rule_fact')
            seen_facts.add(fact.name)
            canonical(fact.value)  # finite JSON only; no model/opaque objects
            proofs=[add(r) for r in fact.sources]
            if proofs and all(proofs) and all(r.valid_until_seq is None or as_of.business_seq<r.valid_until_seq for r in proofs):
                facts[fact.name]=fact.value;fact_refs[fact.name]=[r.model_dump(mode='json') for r in proofs]
        if len(snapshot.tests)!=len(snapshot.test_refs):raise ProtocolError('test_reference_count_mismatch')
        tests=[];test_sources_complete=True
        for test,ref in zip(snapshot.tests,snapshot.test_refs):
            if test.session_id!=auth.session_id or test.id!=ref.object_id or test.version!=ref.version or any(getattr(test.as_of,k)>getattr(as_of,k) for k in ['business_seq','workspace_revision','storage_revision']):
                test_sources_complete=False
                if not source_issues:source_issues.append({'status':'pending','reason':message(work_language,SAFE_REASON)})
                continue
            checked=add(ref)
            if checked:tests.append({'record':test.model_dump(mode='json'),'ref':checked.model_dump(mode='json')})
            else:test_sources_complete=False
        from .history import assess_responsibilities
        def add_historical(ref,when):
            try:c=self.resolve(auth,ref,when)
            except (KeyError,ProtocolError) as error:
                if not unavailable(error):raise
                if not source_issues:source_issues.append({'status':'pending','reason':message(work_language,SAFE_REASON)})
                return None
            if c.ref.valid_until_seq is not None and when.business_seq>=c.ref.valid_until_seq:return None
            candidates['e-'+digest(c.ref)]=CandidateEvidenceV2(id='e-'+digest(c.ref),text=c.text,ref=c.ref)
            return c.ref
        history=assess_responsibilities(snapshot.responsibilities,policy,subjects,as_of,add,add_historical,work_language=work_language)
        response=''
        if snapshot.business_response and snapshot.business_response_refs:
            response_proofs=[add(r) for r in snapshot.business_response_refs]
            if all(response_proofs):response=snapshot.business_response
        context={'facts':facts,'fact_refs':fact_refs,'logs_complete':snapshot.logs_complete,
                 'tests':tests,'config_version':snapshot.config_version,'technical_failures':list(snapshot.technical_failures),
                 'decision':decision,'mechanism':policy.mechanism,'business_response':response,
                 'historical_responsibilities':history,'source_issues':source_issues,'test_sources_complete':test_sources_complete,'anchor_mode':anchor_mode,
                 'requested_at':(requested_at or as_of).model_dump(mode='json')}
        if anchor_mode=='product_version':
            from .factual import factual_feedback
            context['verified_facts']=[factual_feedback(self.reader,auth,ref,as_of,requested_at or as_of,work_language=work_language) for ref in subjects]
        data={'item_id':subject_id+':'+policy.id,'task_type':'criterion','criterion':policy.id,
              'claim':policy_description(policy,work_language)+(message(work_language,'\n用户评审问题（数据）：')+question if question else ''),'subjects':tuple(subject_refs),'purpose':purpose,'as_of':as_of,
              'applicability':applicable(policy,purpose,decision),'candidate_evidence':(),
              'rule_context':context,'completeness':'missing' if missing or source_issues else 'complete',
              'missing_refs':tuple(missing),'dropped_refs':()}
        def seal(values):
            # Materialize all schema defaults before hashing without changing v1.
            defaults={'schema_version':2,'rule_bound':None,**values}
            def json_value(v):
                if hasattr(v,'model_dump'):return v.model_dump(mode='json')
                if isinstance(v,(list,tuple)):return [json_value(x) for x in v]
                if isinstance(v,dict):return {k:json_value(x) for k,x in v.items()}
                return v
            raw=json_value(defaults);raw['input_hash']=digest(raw)
            return EvidencePackageV2.model_validate(raw)
        selected=[];dropped=[]
        for candidate in candidates.values():
            test=seal({**data,'candidate_evidence':tuple(selected+[candidate]),'completeness':'text_overflow'})
            if len(canonical(model_input(test)).encode('utf-8'))<=self.model_bytes:selected.append(candidate)
            else:dropped.append(base_ref(candidate.ref))
        data.update(candidate_evidence=tuple(selected),dropped_refs=tuple(dropped),
                    completeness='text_overflow' if dropped else data['completeness'])
        result=seal(data)
        if len(canonical(model_input(result)).encode('utf-8'))>self.model_bytes:
            # Even the subject/question header may exceed the model window.
            # Keep the complete rule snapshot and explicitly disable semantics;
            # a text budget must not reject the whole review or erase rules.
            data.update(candidate_evidence=(),dropped_refs=tuple(base_ref(c.ref) for c in candidates.values()),completeness='text_overflow')
            return seal(data)
        return result


class SourceCandidate:
    def __init__(self,ref,text,created_at):self.ref,self.text,self.created_at=ref,text,created_at
