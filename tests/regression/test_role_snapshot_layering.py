"""The stored role execution boundary does not require the HTTP layer."""

import subprocess
import sys

from scripts.regression.published import ROOT


def test_store_role_input_validation_runs_without_http_layer() -> None:
    script = """
import importlib.abc
import sys
from types import SimpleNamespace

class NoHttpLayer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'career_lab.api' or fullname.startswith('career_lab.api.'):
            raise AssertionError('storage role execution must not import HTTP: ' + fullname)
        return None

sys.meta_path.insert(0, NoHttpLayer())
from career_lab.storage.v2_store import V2Store
from career_lab.contracts.v2 import ProtocolError
store = V2Store('sqlite://')
command = SimpleNamespace(payload={'subject': {
    'session_id': 'session', 'kind': 'product', 'object_id': 'work', 'version': 1,
}})
envelope = SimpleNamespace(command=command, operation='v2.role_turn')
try:
    try:
        store.begin_role_execution(None, envelope, None, None, None, max_context_chars=100)
    except ProtocolError as error:
        assert error.code == 'role_subject_invalid'
    else:
        raise AssertionError('invalid role subject must still be rejected')
finally:
    store.db.engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_old_role_snapshot_imports_forward_to_the_same_adapter() -> None:
    from career_lab.api import role_snapshot as legacy
    from career_lab.runtime import role_snapshot as runtime

    assert legacy.FixedRoleSnapshotPort is runtime.FixedRoleSnapshotPort
    assert legacy.activated_catalog is runtime.activated_catalog
    assert legacy.activated_reference is runtime.activated_reference
    assert legacy._before is runtime._before
    assert {name for name in vars(legacy) if not name.startswith("_")} == {
        "FixedRoleSnapshotPort",
        "activated_catalog",
        "activated_reference",
    }
