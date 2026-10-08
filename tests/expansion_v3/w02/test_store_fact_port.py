"""W02/W05 feedback from real persisted windows, without a test capture ledger."""
from pathlib import Path
import importlib.util,json,os
import pytest
from career_lab.scenarios.v2.evidence_ports.store import create_store_fact_adapter
from career_lab.scenarios.v2.module import point

ROOT=Path(__file__).resolve().parents[3]
pytestmark=pytest.mark.skipif(not os.environ.get('W05_W02_COMBO_ROOT'),reason='requires installed W02/W05 bundle')
spec=importlib.util.spec_from_file_location('w05_persisted_combo',ROOT/'tests/integration/test_w05_frozen_w02.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
combined=base.combined

@pytest.mark.parametrize('branch',['ignored','stale','fresh_limited','fresh_approved','no_go','defer_with_conditions'])
def test_persisted_authorized_history_drives_fourteen_rules(combined,branch,tmp_path):
    h,worker,queue,holder=combined
    h.adapter=create_store_fact_adapter(h.store,h.module,h.gateway.registry)
    h.windows.clear();h.events.clear()
    h.capture=lambda result=None:point(h.store.view(h.auth).state)
    base.test_w05_frozen_w02_full_feedback(combined,branch,tmp_path)
    assert not h.windows and not h.events
    out=Path(os.environ.get('W05_COMBO_EVIDENCE_DIR',str(tmp_path)))/(h.module.work_language+'-'+branch+'.json')
    record=json.loads(out.read_text())
    record.update(source='real W02 / W05 / FastAPI TestClient / Gateway / SQLite / worker',
        history_boundary='existing authorized query_at, public_event_history and persisted snapshot points',
        capture_windows=0,capture_events=0,normal_v4_verified=False,
        fact_adapter_factory='career_lab.scenarios.v2.evidence_ports.store.create_store_fact_adapter')
    out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
