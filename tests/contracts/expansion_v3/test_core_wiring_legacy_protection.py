"""Preserve v1 bytes using the base tree, not newly inherited v2 scenario files."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
BASE='80cf1f6189cd25610d609f44283ff9668582d759'


def test_original_v1_scenarios_contracts_and_research_bytes_are_preserved():
    # The inherited W01 test enumerates current tracked scenarios, which now also
    # contains W02 v2 files absent at BASE. Keep that upstream test unchanged;
    # this integration check enumerates the exact original protected tree.
    original=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'--','scenarios'],cwd=ROOT,text=True).splitlines()
    assert original and all('/v1/' in path for path in original)
    original+=['src/career_lab/contracts/actions.py','src/career_lab/contracts/base.py','src/career_lab/contracts/scenario.py','src/career_lab/contracts/evaluation.py','src/career_lab/contracts/deliverables.py','docs/reports/controlled-v2-freeze.json']
    for rel in original:
        expected=subprocess.check_output(['git','show',BASE+':'+rel],cwd=ROOT)
        assert (ROOT/rel).read_bytes()==expected,rel
