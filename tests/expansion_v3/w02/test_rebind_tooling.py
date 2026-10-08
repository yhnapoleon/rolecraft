"""Release-tool migration is opt-in and cannot authorize business-runtime edits."""
import json
from pathlib import Path
import pytest
from career_lab.contracts.v2 import ProtocolError
from career_lab.scenarios.v2 import rebind as tool

ROOT = Path(__file__).resolve().parents[3]
BASELINE = '49141fa1eea5370d3ed5231f9fe6c5a40995284a'
SOURCE = ROOT / 'scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.5/pm_pilot'


def old_owned():
    return json.loads((SOURCE / 'runtime/source-files.json').read_text())['owned_code']


def test_unchanged_owned_source_needs_no_migration():
    current = tool.runtime_source_files(ROOT, 'zh')
    assert tool.verified_owned_input(ROOT, current, 'zh') == (current, None)


def test_tool_only_update_requires_explicit_baseline_and_records_actual_bytes():
    expected = old_owned()
    with pytest.raises(ProtocolError, match='owned code mismatch'):
        tool.verified_owned_input(ROOT, expected, 'zh')
    current, proof = tool.verified_owned_input(ROOT, expected, 'zh', BASELINE)
    changed = [p for p in current if current[p] != expected[p]]
    assert changed == ['src/career_lab/scenarios/v2/rebind.py']
    assert proof == {'baseline_commit': BASELINE, 'changed_files': changed,
                     'before_sha256': expected[changed[0]], 'after_sha256': current[changed[0]]}


def test_tool_migration_rejects_an_extra_runtime_edit(monkeypatch):
    current = tool.runtime_source_files(ROOT, 'zh')
    current['src/career_lab/scenarios/v2/engine.py'] = '0' * 64
    monkeypatch.setattr(tool, 'runtime_source_files', lambda *_: current)
    with pytest.raises(ProtocolError, match='runtime change not authorized'):
        tool.verified_owned_input(ROOT, old_owned(), 'zh', BASELINE)


@pytest.mark.parametrize('baseline', ['0' * 40, BASELINE])
def test_tool_migration_requires_original_bytes_at_real_commit(baseline):
    expected = old_owned()
    expected['src/career_lab/scenarios/v2/rebind.py'] = '0' * 64
    with pytest.raises(ProtocolError, match='tooling baseline'):
        tool.verified_owned_input(ROOT, expected, 'zh', baseline)
