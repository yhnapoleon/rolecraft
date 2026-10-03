import hashlib
import itertools
import json
import random
from pathlib import Path

from career_lab.contracts.evaluation import CandidateEvidence, EvidencePackage, GoldAnnotation
from career_lab.datasets.release import build_release, write_jsonl
from career_lab.datasets.scenario_matrix import TEMPLATES, FIELDS, evaluate, variables, expression_text
from career_lab.evidence.serializer import seal_input
from career_lab.storage.sessions import digest

LABEL = {True:'SUPPORTED', False:'CONTRADICTED', None:'INSUFFICIENT'}
BOOLEAN = {'approved','dependency','risk_test','allowed','blocked','dynamic','realtime','consent','private','manual','narrowed','extension'}


def render_claim(template,style):
    condition=expression_text(template.expression)
    if style==0:return f'核验要求：{template.description}。条件为{condition}。该条件成立。'
    if style==1:return f'按{condition}核验，结论是条件成立。核验要求：{template.description}。'
    raise ValueError('unsupported rendering style')


def sufficient_sets(expr, facts):
    value = evaluate(expr, facts)
    if value is None: return [()]
    keys = sorted(facts)
    accepted = []
    for size in range(1,len(keys)+1):
        for subset in itertools.combinations(keys,size):
            if any(set(a)<=set(subset) for a in accepted): continue
            if evaluate(expr,{k:facts[k] for k in subset}) is value:
                accepted.append(subset)
    return accepted


def _sample(template, rng, truth):
    for _ in range(10000):
        facts = {k:rng.randint(0,1) if k in BOOLEAN else rng.randint(1,12) for k in sorted(variables(template.expression))}
        if evaluate(template.expression,facts) is truth: return facts
    raise ValueError('cannot construct satisfiable template')


def generate_controlled(roots_per_template=8, seed=5002):
    if roots_per_template < 1: raise ValueError('positive roots required')
    rows=[]
    for t in TEMPLATES:
        for root_index in range(roots_per_template):
            root=f'{t.id}-root-{root_index:03d}'
            rng=random.Random(int(digest([seed,root])[:16],16))
            positive,negative=_sample(t,rng,True),_sample(t,rng,False)
            unknown=positive.copy()
            order=list(unknown);rng.shuffle(order)
            for key in order:
                del unknown[key]
                if evaluate(t.expression,unknown) is None: break
            for mode,facts in enumerate((positive,negative,unknown)):
                for style in range(2):
                    iid=digest([root,mode,style])[:24]
                    evidence=[];field_ids={}
                    ids=rng.sample(range(1,100),8)
                    for key in sorted(facts):
                        eid=f'e{ids.pop()}'
                        field_ids[key]=eid
                        text=f'{FIELDS[key]}：{facts[key]}。' if style==0 else f'记录中的{FIELDS[key]}为{facts[key]}。'
                        evidence.append(CandidateEvidence(id=eid,version=1,text=text))
                    while len(evidence)<8:
                        number=len(evidence)
                        evidence.append(CandidateEvidence(id=f'e{ids.pop()}',version=1,text=f'办公记录{number}：会议室编号为{rng.randint(1,50)}，本周例会在周三。'))
                    rng.shuffle(evidence)
                    claim=render_claim(t,style)
                    item=seal_input(EvidencePackage(item_id=iid,task_type='relation',criterion=t.family,claim=claim,
                        as_of_seq=0,candidate_evidence=tuple(evidence),completeness='complete'))
                    minimal=sufficient_sets(t.expression,facts)
                    value=evaluate(t.expression,facts)
                    missing=sorted(variables(t.expression)-facts.keys())
                    gold=GoldAnnotation(item_id=iid,label=LABEL[value],label_tier='G0',
                        acceptable_evidence_sets=tuple(tuple(field_ids[k] for k in subset) for subset in minimal),
                        missing_requirement='、'.join(FIELDS[k] for k in missing) if value is None else None,
                        annotation_version='controlled-v2',verifier_id='three-valued-v2')
                    rows.append(dict(input=item.model_dump(mode='json'),gold=gold.model_dump(mode='json'),
                        lineage=dict(item_id=iid,template_id=t.id,root_case_id=root,parent_id=None,split=t.split,language='zh',
                                     source='controlled-synthetic-g0-v2',source_split=t.split,family_id=t.family,variant=mode,style=style),
                        authoring=dict(template_id=t.id,facts=facts,field_ids=field_ids,seed=seed)))
    return rows


def verify_row(row):
    t=next(t for t in TEMPLATES if t.id==row['authoring']['template_id'])
    lineage=row['lineage'];item=EvidencePackage.model_validate(row['input']);gold=GoldAnnotation.model_validate(row['gold'])
    if item.claim!=render_claim(t,lineage['style']) or item.input_hash!=seal_input(item).input_hash:return False
    if lineage['template_id']!=t.id or lineage['split']!=t.split or lineage['family_id']!=t.family or item.criterion!=t.family:return False
    if not lineage['root_case_id'].startswith(t.id+'-root-') or item.item_id!=digest([lineage['root_case_id'],lineage['variant'],lineage['style']])[:24]:return False
    if item.item_id!=gold.item_id or item.item_id!=lineage['item_id'] or gold.label_tier!='G0':return False
    facts,ids=row['authoring']['facts'],row['authoring']['field_ids']
    if set(facts)!=set(ids) or not set(facts)<=variables(t.expression): return False
    evidence={e['id']:e['text'] for e in row['input']['candidate_evidence']}
    for k,v in facts.items():
        if evidence.get(ids[k]) not in (f'{FIELDS[k]}：{v}。',f'记录中的{FIELDS[k]}为{v}。'): return False
    value=evaluate(t.expression,facts)
    missing='、'.join(FIELDS[k] for k in sorted(variables(t.expression)-facts.keys())) if value is None else None
    expected={frozenset(ids[k] for k in subset) for subset in sufficient_sets(t.expression,facts)}
    observed={frozenset(x) for x in row['gold']['acceptable_evidence_sets']}
    return row['gold']['label']==LABEL[value] and expected==observed and gold.missing_requirement==missing


def build_controlled_release(output, rows=None):
    rows=generate_controlled() if rows is None else rows
    if not all(verify_row(row) for row in rows): raise ValueError('invalid controlled proof')
    path=build_release(Path(output),rows)
    root=path.parent
    metadata=json.loads(path.read_text(encoding='utf-8'))
    metadata.update(version='controlled-v2',human_validation='pending',synthetic_only=True,
                    generator_revision='controlled-v2',verifier_revision='three-valued-v2',templates=len({r['lineage']['template_id'] for r in rows}))
    card=root/'data_card.md'
    card.write_text('# Controlled G0 v2\n\n'+f'{len(rows)}中文受控合成relation项；6能力族、24结构模板（子集按manifest统计）。每个事实根含支持/矛盾/缺失及两种表达；8条候选材料，证据编号与次序打乱。按模板划分，改写不增加独立样本数。规则条件直接给定，不代表开放文本推理。\n\n人工双标pending；不能称G1或真实用户验证。原v1保留。测试只可在冻结后评价。三值逻辑验证器与规则上界同源，规则成绩不构成独立泛化证据。\n',encoding='utf-8')
    metadata['files']['data_card.md']=hashlib.sha256(card.read_bytes()).hexdigest()
    # Proofs are authoring artifacts; gold/proofs are never included in model inputs.
    for split in ('train','dev','test'):
        target=root/'proofs'/f'{split}.jsonl'
        write_jsonl(target,[dict(item_id=r['input']['item_id'],**r['authoring']) for r in rows if r['lineage']['split']==split])
        metadata['files'][target.relative_to(root).as_posix()]=hashlib.sha256(target.read_bytes()).hexdigest()
    path.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    return path
