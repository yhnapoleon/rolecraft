"""Reject diagnostic releases at read time with the actual record ID and reason."""
import json
import pytest
from test_w08_models import release_fixture
from career_lab.contracts.v2.core import FileRef,digest
from career_lab.models.v3.bundle import json_bytes,sha
from career_lab.experiments.v3.training.data import ReleaseReader,RecordReadError


def rehash(root,manifest):
    manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'});(root/'manifest.json').write_bytes(json_bytes(manifest))
    return FileRef(path='manifest.json',sha256=sha((root/'manifest.json').read_bytes()))


def test_diagnostic_release_rejects_before_loading_training_data(tmp_path):
    root=tmp_path/'data';release,split=release_fixture(root);m=json.loads((root/'manifest.json').read_text());entry=next(e for e in json.loads((root/'split-manifest.json').read_text())['entries'] if e['split']=='train');rid=entry['record_id']
    m['readiness'].update(status='diagnostic',blockers=[{'record_id':rid,'reason':'input_missing'}]);reader=ReleaseReader(root,rehash(root,m),split,allow_fixture=True)
    with pytest.raises(RecordReadError) as exc:reader.load('train')
    assert exc.value.record_id==rid and exc.value.cause_code=='input_missing'
    assert not any(a['purpose'].endswith(':input') for a in reader.access_log)


def test_claimed_ready_incomplete_record_still_reports_identity(tmp_path):
    root=tmp_path/'data';release,split=release_fixture(root);m=json.loads((root/'manifest.json').read_text());s=json.loads((root/'split-manifest.json').read_text());entry=next(e for e in s['entries'] if e['split']=='train');rid=entry['record_id'];ip=root/entry['file']['path'];item=json.loads(ip.read_text());item['evidence']['completeness']='missing';item['evidence']['input_hash']=digest({k:v for k,v in item['evidence'].items() if k!='input_hash'});ip.write_bytes(json_bytes(item));entry['file']['sha256']=m['files'][entry['file']['path']]=sha(ip.read_bytes())
    # Keep source/annotation pairing honest enough to reach the completeness guard.
    mp=root/f'metadata/{rid}.json';meta=json.loads(mp.read_text());meta['input_hash']=digest(item);mp.write_bytes(json_bytes(meta));m['files'][mp.relative_to(root).as_posix()]=sha(mp.read_bytes());idx=json.loads((root/'record-metadata.json').read_text());idx['records'][rid]['sha256']=sha(mp.read_bytes());(root/'record-metadata.json').write_bytes(json_bytes(idx));m['metadata']['sha256']=m['files']['record-metadata.json']=sha((root/'record-metadata.json').read_bytes())
    (root/'split-manifest.json').write_bytes(json_bytes(s));m['files']['split-manifest.json']=sha((root/'split-manifest.json').read_bytes())
    reader=ReleaseReader(root,rehash(root,m),FileRef(path='split-manifest.json',sha256=m['files']['split-manifest.json']),allow_fixture=True)
    with pytest.raises(RecordReadError) as exc:reader.load('train')
    assert exc.value.record_id==rid and exc.value.cause_code=='input_missing'
