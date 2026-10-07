"""No fitting: bilingual metrics over explicitly synthetic fixed predictions."""
from dataclasses import replace
import pytest
from test_w08_models import examples
from career_lab.models.v3.core import Prediction, LABELS
from career_lab.experiments.v3.training.metrics import grade, paired_cluster_delta
from career_lab.experiments.v3.training.languages import bilingual_report, validate_translation_index
from career_lab.contracts.v2.core import ProtocolError


def test_bilingual_metrics_keep_joint_separate_from_label():
    rows=[replace(r,language='zh' if i%2 else 'en') for i,r in enumerate(examples('dev'))]
    evaluations={}
    for name in ('linear','candidate'):
        grades=[];predictions=[]
        for r in rows:
            gold=r.annotation.final
            p=Prediction('relation',r.annotation.input_hash,'synthetic-no-fit','ok',gold.label,tuple(float(x==gold.label) for x in LABELS['relation']),tuple(gold.evidence_ids) if name=='candidate' else ('e1','e2'))
            grades.append(grade(r,p));predictions.append({'record_id':r.record_id,'prediction':p.as_dict()})
        evaluations[name]={'rows':grades,'predictions':predictions}
    report=bilingual_report([],rows,evaluations,{}, {'fixture':True},'relation')
    assert report['scope']=='synthetic_mechanical_only' and not report['quality_validated']
    for lang in ('zh','en'):
        assert report['languages'][lang]['dev_records']==3
        assert report['languages'][lang]['models']['candidate']['metrics']['joint_correctness']==1
        assert report['paired_model_comparisons'][lang]['candidate']['joint']['delta']==1
        assert report['paired_model_comparisons'][lang]['candidate']['label']['delta']==0


def test_missing_language_is_not_quality_pass():
    report=bilingual_report([],examples('dev'),{}, {}, {'fixture':True},'relation')
    assert report['languages']['zh']['data_status']=='blocked_missing_language_data'
    assert report['languages']['zh']['dev_records']==0
    assert not report['formal_bilingual_evaluation_complete']


def test_joint_delta_excludes_label_only_and_rejects_eligibility_mismatch():
    a=[{'record_id':'one','input_hash':'fixed','component_id':'one','joint_correct':None,'label_correct':True}]
    assert paired_cluster_delta(a,a)['excluded_record_ids']==['one']
    with pytest.raises(ProtocolError,match='paired metric eligibility mismatch'):
        paired_cluster_delta(a,[a[0]|{'joint_correct':True}])


def test_translation_metadata_rejects_cross_split_before_body():
    from types import SimpleNamespace
    entries=[SimpleNamespace(record_id='zh',split='train',structure_id='same',component_id='same'),SimpleNamespace(record_id='en',split='test',structure_id='same',component_id='same')]
    pair={'id':'pair','original':{'record_id':'zh','language':'zh'},'translated':{'record_id':'en','language':'en'},'split':'train'}
    with pytest.raises(ProtocolError,match='translation cross split'):
        validate_translation_index({'protocol':'w07-translation-metadata-v1','pairs':[pair]},entries)
