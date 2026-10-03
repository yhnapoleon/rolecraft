import json
import pytest
from career_lab.datasets.controlled import generate_controlled, build_controlled_release
from career_lab.contracts.evaluation import EvidencePackage
from career_lab.experiments.candidates import RuleCandidate, HybridCandidate
from career_lab.experiments.protocol import freeze_selection, verify_freeze


def test_rules_use_observed_text_not_authoring_metadata():
    rows=generate_controlled(1)
    candidate=RuleCandidate()
    for row in rows:
        if row['lineage']['family_id'] in ('capacity','resources'):
            item=EvidencePackage.model_validate(row['input'])
            decision=candidate.judge(item)
            assert decision.label==row['gold']['label']
            assert set(decision.evidence_ids) in [set(s) for s in row['gold']['acceptable_evidence_sets']]
    row=next(r for r in rows if r['gold']['label']=='SUPPORTED')
    item=EvidencePackage.model_validate(row['input'])
    assert candidate.judge(item.model_copy(update={'candidate_evidence':()})).label=='INSUFFICIENT'


def test_freeze_rejects_drift_and_cannot_overwrite(tmp_path):
    artifact=tmp_path/'model.json';artifact.write_text('{}')
    freeze=freeze_selection(tmp_path/'freeze.json', {'model':artifact}, {'selected':'linear','split':'dev'})
    verify_freeze(tmp_path/'freeze.json')
    with pytest.raises(ValueError):freeze_selection(tmp_path/'freeze.json',{'model':artifact},{})
    artifact.write_text('{"modified":true}')
    with pytest.raises(ValueError,match='drift'):verify_freeze(tmp_path/'freeze.json')
