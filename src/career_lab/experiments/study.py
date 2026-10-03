import json
import platform
from pathlib import Path

from career_lab.contracts.evaluation import EvidencePackage
from career_lab.datasets.release import audit_release, read_jsonl, write_jsonl
from career_lab.evals.runner import ConstantCandidate, RunnerConfig, run_eval
from career_lab.evals.metrics import paired_diff
from career_lab.evidence.serializer import seal_input
from career_lab.models.training import load_candidate
from career_lab.registry.models import register_candidate, verify_record
from career_lab.storage.sessions import digest
from career_lab.experiments.candidates import RuleCandidate, HybridCandidate
from career_lab.experiments.protocol import freeze_selection, verify_freeze, sha


def _save(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def candidates(models):
    result={name:load_candidate(Path(models)/f'{name}.json') for name in ('linear','encoder','ensemble')}
    result.update(constant=ConstantCandidate(),rules=RuleCandidate(),hybrid=HybridCandidate(result['ensemble']))
    return result


def details(report):
    rows=read_jsonl(Path(report.manifest_path).parent/'predictions.jsonl')
    labels=('SUPPORTED','CONTRADICTED','INSUFFICIENT')
    matrix={g:{p:sum(r['gold_label']==g and (r['predicted_label'] or 'NO_PREDICTION')==p for r in rows) for p in (*labels,'NO_PREDICTION')} for g in labels}
    per_class={}
    for label in labels:
        tp=matrix[label][label];support=sum(matrix[label].values());predicted=sum(matrix[g][label] for g in labels)
        per_class[label]={'support':support,'precision':tp/predicted if predicted else 0,'recall':tp/support if support else 0,
                          'f1':2*tp/(support+predicted) if support+predicted else 0}
    scores=[r['evidence_score'] for r in rows if r['evidence_score'] is not None]
    abstain=sum((r.get('decision') or {}).get('reason_code')=='RULE_ABSTAIN' for r in rows)
    extra=json.loads((Path(report.manifest_path).parent/'metrics.json').read_text(encoding='utf-8'))
    return report.model_dump(mode='json')|dict(confusion_matrix=matrix,per_class=per_class,
        mean_evidence_f1=sum(scores)/len(scores) if scores else None,answer_coverage=1-abstain/len(rows),
        abstentions=abstain,accuracy_ci=extra['accuracy_ci'],trial_count=len(rows))


def _run(manifest,models,output,split):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    all_candidates=candidates(models);results={}
    for name,candidate in all_candidates.items():
        config=RunnerConfig(suite='controlled-v2-e1',dataset_manifest=str(Path(manifest).resolve()),candidate=candidate.revision,
            prompt_version='controlled-v2',input_mode='oracle',decode={},seeds=[5002],concurrency=1,
            output_dir=str(output/'evals'),split=split,confirmatory=split=='test')
        results[name]=details(run_eval(config,candidate))
    retrieval={}
    for name in ('ensemble','hybrid'):
        config=RunnerConfig(suite='controlled-v2-e5',dataset_manifest=str(Path(manifest).resolve()),candidate=all_candidates[name].revision,
            prompt_version='controlled-v2',input_mode='retrieved',decode={},seeds=[5002],concurrency=1,
            output_dir=str(output/'evals'),split=split,confirmatory=split=='test')
        retrieval[name]=details(run_eval(config,all_candidates[name]))
    lineage={r['item_id']:r for r in read_jsonl(Path(manifest).parent/'lineage.jsonl')}
    name='test.inputs' if split=='test' else 'dev'
    inputs={i.item_id:i for i in (EvidencePackage.model_validate(r) for r in read_jsonl(Path(manifest).parent/f'splits/{name}.jsonl'))}
    robustness={};perturbations=[]
    for name in ('linear','encoder','ensemble','hybrid'):
        rows=read_jsonl(Path(results[name]['manifest_path']).parent/'predictions.jsonl')
        grouped={}
        invariant=0
        for row in rows:
            info=lineage[row['item_id']]
            grouped.setdefault(info['root_case_id'],{})[(info['variant'],info['style'])]=row
            item=inputs[row['item_id']]
            changed=seal_input(item.model_copy(update={'candidate_evidence':tuple(reversed(item.candidate_evidence))}))
            prediction=all_candidates[name].judge(changed)
            invariant+=prediction.label==row['predicted_label']
            perturbations.append(dict(candidate=name,item_id=item.item_id,input_hash=changed.input_hash,transformation='reverse_evidence',
                                      original_label=row['predicted_label'],prediction=prediction.model_dump(mode='json')))
        pairs=[(group[(v,0)],group[(v,1)]) for group in grouped.values() for v in range(3)]
        contrasts=[(group[(0,0)],group[(1,0)]) for group in grouped.values()]
        robustness[name]=dict(style_and_order_agreement=sum(a['predicted_label']==b['predicted_label'] for a,b in pairs)/len(pairs),
            style_pair_joint_accuracy=sum(a['label_correct'] and b['label_correct'] for a,b in pairs)/len(pairs),
            opposite_fact_pair_joint_accuracy=sum(a['label_correct'] and b['label_correct'] for a,b in contrasts)/len(contrasts),
            pure_order_invariance=invariant/len(rows),pairs=len(pairs),roots=len(grouped),
            note='style pairs also change distractor wording/order; contrast pairs may change multiple facts; bag-of-ngram models are order invariant by construction')
    write_jsonl(output/f'robustness-{split}.jsonl',perturbations)
    pairs={}
    a=read_jsonl(Path(results['linear']['manifest_path']).parent/'predictions.jsonl')
    for name in ('encoder','ensemble','hybrid'):
        pairs[name]=paired_diff(a,read_jsonl(Path(results[name]['manifest_path']).parent/'predictions.jsonl'))
    return dict(split=split,e1=results,e5=retrieval,e6=robustness,paired_vs_linear=pairs,
        human_validation='pending',scope='controlled_synthetic_G0_only',seed=5002,
        hardware=dict(system=platform.system(),python=platform.python_version(),device='CPU'),
        limitations=['single training seed','six evaluation templates per split','explicit logical grammar','rules share generator verifier','human annotation pending'])


def run_development(manifest,models,output):
    output=Path(output)
    if (output/'freeze.json').exists():raise ValueError('study already frozen; development is closed')
    report=_run(manifest,models,output,'dev')
    report['training']=json.loads((Path(models)/'training-report.json').read_text(encoding='utf-8'))
    records=[]
    for name in ('linear','encoder','ensemble'):
        records.append(register_candidate(Path(models)/f'{name}.json',report['e1'][name]['manifest_path'],rubric_hash='relation-only-no-product-rubric'))
    _save(output/'registry.json',records)
    source={str(p.resolve()):sha(p) for p in Path('src/career_lab').rglob('*.py')}
    artifacts={str(p.resolve()):sha(p) for p in [*Path(models).glob('*.json'),*Path(models).glob('*.joblib')]}
    results={}
    for section in ('e1','e5'):
        for entry in report[section].values():
            directory=Path(entry['manifest_path']).parent
            results.update({str(p.resolve()):sha(p) for p in directory.rglob('*') if p.is_file()})
    results[str((output/'robustness-dev.jsonl').resolve())]=sha(output/'robustness-dev.jsonl')
    results[str((output/'registry.json').resolve())]=sha(output/'registry.json')
    report['provenance']=dict(manifest=str(Path(manifest).resolve()),dataset_hash=sha(manifest),
        models=str(Path(models).resolve()),source=source,artifacts=artifacts,results=results)
    _save(output/'development.json',report)
    return report


def freeze_study(manifest,models,output):
    output=Path(output);manifest=Path(manifest);models=Path(models)
    report=json.loads((output/'development.json').read_text(encoding='utf-8'))
    provenance=report['provenance']
    if provenance['manifest']!=str(manifest.resolve()) or provenance['dataset_hash']!=sha(manifest) or provenance['models']!=str(models.resolve()):
        raise ValueError('development provenance mismatch')
    for category in ('source','artifacts','results'):
        if any(not Path(p).is_file() or sha(p)!=h for p,h in provenance[category].items()):raise ValueError('development provenance drift')
    if provenance['source']!={str(p.resolve()):sha(p) for p in Path('src/career_lab').rglob('*.py')}:raise ValueError('source provenance drift')
    current=candidates(models)
    for section in ('e1','e5'):
        for name,entry in report[section].items():
            run=json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8'))
            metrics=json.loads((Path(entry['manifest_path']).parent/'metrics.json').read_text(encoding='utf-8'))['overall']
            if run['dataset_hash']!=sha(manifest) or run['config']['candidate']!=current[name].revision or run['config']['split']!='dev' or metrics!=entry['metrics']:
                raise ValueError('evaluation provenance mismatch')
    for record in json.loads((output/'registry.json').read_text(encoding='utf-8')):
        verify_record(record,'relation-only-no-product-rubric')
    names=('linear','encoder','ensemble','hybrid')
    selected=max(names,key=lambda n:(report['e1'][n]['metrics']['macro_f1'],-names.index(n)))
    decision=dict(selected=selected,selection_split='dev',manifest=str(manifest.resolve()),models=str(models.resolve()),
        primary_metric='macro_f1',thresholds=dict(macro_f1=.8,false_deduction=.1,joint_correctness=.6),
        human_validation_required=True,post_training=False)
    files={str(p):p for p in [manifest,output/'development.json',output/'registry.json',*models.glob('*.json'),*models.glob('*.joblib'),*Path('src/career_lab').rglob('*.py')]}
    files.update({str(p):p for p in (Path('pyproject.toml'),Path('uv.lock'))})
    files.update({p:Path(p) for p in provenance['results']})
    # Dataset manifest pins every split; verify it before the first test run.
    audit_release(manifest)
    return freeze_selection(output/'freeze.json',files,decision)


def run_confirmatory(output):
    output=Path(output)
    if not (output/'freeze.json').exists():raise ValueError('freeze required before test')
    frozen=verify_freeze(output/'freeze.json');decision=frozen['decision']
    audit_release(Path(decision['manifest']))
    target=output/'confirmatory.json'
    if target.exists():
        report=json.loads(target.read_text(encoding='utf-8'))
        if report['freeze_id']!=frozen['id'] or report['report_hash']!=digest({k:v for k,v in report.items() if k!='report_hash'}):raise ValueError('confirmatory report drift')
        return report
    report=_run(decision['manifest'],decision['models'],output,'test')
    metrics=report['e1'][decision['selected']]['metrics'];thresholds=decision['thresholds']
    numeric=metrics['macro_f1']>=thresholds['macro_f1'] and metrics['false_deduction']<=thresholds['false_deduction'] and metrics['joint_correctness']>=thresholds['joint_correctness']
    report.update(freeze_id=frozen['id'],selected=decision['selected'],deployment=dict(eligible=False,numeric_gate_passed=numeric,
        human_gate_passed=False,mode='shadow_relation_only',reason='G0 synthetic only; no human semantic validation; never substitute criterion scoring'))
    report['report_hash']=digest(report)
    _save(target,report)
    return report
