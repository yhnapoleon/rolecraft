"""Actual W07 exporter/publication; W08 consumption is a separate process run."""
import json
from pathlib import Path
from career_lab.contracts.v2.data import DatasetMetadataV2
from career_lab.datasets.v3.fixture_pipeline import build_fixture_release


def test_fixture_release_is_published_and_audited_from_twelve_snapshots(tmp_path):
    report=build_fixture_release(tmp_path/'joint',workspace=Path(__file__).resolve().parents[2])
    root=Path(report['release_root']);manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['fixture'] and not manifest['training_ready'] and not manifest['confirmatory']
    assert manifest['readiness']['status']=='ready' and manifest['readiness']['scope']=='fixture'
    quality=json.loads((root/'quality-report.json').read_text())
    assert quality['evidence_supervision']['label_only_count']==2 and quality['evidence_supervision']['evaluable_count']==10
    assert manifest['records']==12 and manifest['splits']=={'train':6,'dev':6}
    assert manifest['source_snapshot_count']==12
    assert sum(not r['evidence_evaluable'] for r in report['expected_records'].values())==2
    for path in (root/'metadata').glob('*.json'):
        metadata=DatasetMetadataV2.model_validate_json(path.read_text())
        assert len(metadata.source_snapshots)==1 and metadata.bucket=='fixture'
        assert metadata.annotation_status=='accepted' and metadata.accepted_label_tier=='G0'
        payload=json.loads((root/'inputs'/path.name).read_text())
        assert not {'lineage','provenance','source_snapshots','language','bucket','final'} & payload.keys()
        assert metadata.capture_point.business_seq>=payload['evidence']['as_of']['business_seq']
