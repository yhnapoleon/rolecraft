"""Producer P2 boundaries; every source or annotation here is an explicit test fixture."""
from dataclasses import replace
import pytest
from test_w07_pipeline import make_case
from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.data import AnnotationDecision,DatasetRecordV2
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.release import publish_release,audit_release
from career_lab.datasets.v3.origin import binding
from career_lab.datasets.v3.temporal import validate_time_citations
from career_lab.datasets.v3.g0 import verify_numeric


@pytest.mark.parametrize('family,label',[('relation','SUPPORTED'),('relation','CONTRADICTED'),('relation','INSUFFICIENT'),('criterion','MET'),('criterion','NOT_APPLICABLE')])
def test_final_references_must_equal_one_legal_alternative(tmp_path,family,label):
    snapshot,units,_=make_case(tmp_path);row=export_snapshot(snapshot,[next(u for u in units if u.family==family)]).records[0]
    raw=dict(task_type=row.model_input.task_type,label=label,evidence_ids=['e1'],acceptable_evidence_sets=[['e2']],evidence_evaluable=True)
    with pytest.raises(ProtocolError,match='acceptable target'):validate_time_citations(row.model_input,AnnotationDecision(**raw))
    raw['acceptable_evidence_sets']=[['e2'],['e1']];validate_time_citations(row.model_input,AnnotationDecision(**raw))
    if label in ['INSUFFICIENT','NOT_APPLICABLE']:
        raw.update(evidence_ids=[],acceptable_evidence_sets=[[]]);validate_time_citations(row.model_input,AnnotationDecision(**raw))


@pytest.mark.parametrize('rewrite_descriptor',[False,True])
def test_removing_fixture_marker_cannot_launder_origin(tmp_path,rewrite_descriptor):
    snapshot,units,policies=make_case(tmp_path);result=export_snapshot(snapshot,units[:1]);row=result.records[0]
    row=DatasetRecordV2.model_validate(row.model_dump(mode='json') | {'bucket':'env_run','provenance':row.provenance.model_dump(mode='json') | {'transformations':[]}})
    snapshots=tuple(dict(s,origin='env_run') for s in result.source_snapshots) if rewrite_descriptor else result.source_snapshots
    forged=replace(result,records=(row,),origin='env_run',source_snapshots=snapshots)
    with pytest.raises(ProtocolError,match='origin'):
        publish_release(tmp_path/'bad',forged,source_root=tmp_path,policies=policies,allow_pending=True,
                        source_authority=lambda r,s,files:binding(r,s))
    assert not (tmp_path/'bad').exists()


def test_self_declared_business_origin_requires_independent_authority(tmp_path):
    snapshot,units,policies=make_case(tmp_path,origin='env_run');result=export_snapshot(snapshot,units[:1])
    with pytest.raises(ProtocolError,match='authoritative source reader'):
        publish_release(tmp_path/'bad',result,source_root=tmp_path,policies=policies,allow_pending=True)


def test_label_only_numeric_truth_recomputed_without_evidence_supervision(tmp_path):
    snapshot,units,policies=make_case(tmp_path);result=export_snapshot(snapshot,units[:1]);row=result.records[0]
    label=verify_numeric(row,evidence_evaluable=False)
    assert label.final.label=='SUPPORTED' and not label.final.evidence_ids and not label.final.acceptable_evidence_sets
    publish_release(tmp_path/'release',result,source_root=tmp_path,policies=policies,annotations=[label],fixture=True)
    assert audit_release(tmp_path/'release')['records']==1
    # False localization scope never makes an arbitrary semantic label valid.
    false=label.model_copy(update={'final':label.final.model_copy(update={'label':'CONTRADICTED'})})
    with pytest.raises(ProtocolError,match='consensus'):
        publish_release(tmp_path/'bad',result,source_root=tmp_path,policies=policies,annotations=[false],fixture=True)
