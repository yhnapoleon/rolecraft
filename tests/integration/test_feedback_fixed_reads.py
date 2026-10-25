"""Repeated criterion reads retain exact historical identity and live authorization."""

import pytest
from test_engineer_session import Eng
from test_engineer_session import eng as eng

from career_lab.api.evaluation_runtime import ScenarioEvidencePort
from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ref_for


def test_fixed_record_reuses_projection_and_rechecks_authorization(eng: Eng, monkeypatch):
    store = eng.app.state.v2_store
    auth = store.authenticate(eng.sid, eng.token)
    module = eng.app.state.scenario_v2
    port = ScenarioEvidencePort(store, module)
    ref = ref_for("config", module.package.baseline(eng.sid))
    at = C.VersionPoint.model_validate(
        {k: eng.state()[k] for k in ("business_seq", "workspace_revision", "storage_revision")}
    )
    query = store.query_at
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[1])
        return query(*args, **kwargs)

    monkeypatch.setattr(store, "query_at", counted)
    first = port.record(auth, ref, at)
    assert port.record(auth, ref, at) == first
    assert len(calls) == 1
    eng.advance_world()
    new_at = C.VersionPoint.model_validate(
        {k: eng.state()[k] for k in ("business_seq", "workspace_revision", "storage_revision")}
    )
    assert port.record(auth, ref, new_at) == first
    assert len(calls) == 2

    def revoked(*args, **kwargs):
        raise C.ProtocolError("credential_revoked_or_invalid", status=403)

    monkeypatch.setattr(store, "authorize", revoked)
    with pytest.raises(C.ProtocolError, match="credential revoked"):
        port.record(auth, ref, at)


def test_failed_fixed_reads_are_not_cached(eng: Eng, monkeypatch):
    store = eng.app.state.v2_store
    auth = store.authenticate(eng.sid, eng.token)
    port = ScenarioEvidencePort(store, eng.app.state.scenario_v2)
    ref = C.ObjectRef(session_id=eng.sid, kind="product", object_id="missing", version=1)
    at = C.VersionPoint.model_validate(
        {k: eng.state()[k] for k in ("business_seq", "workspace_revision", "storage_revision")}
    )
    query = store.query_at
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return query(*args, **kwargs)

    monkeypatch.setattr(store, "query_at", counted)
    for _ in range(2):
        with pytest.raises(C.ProtocolError):
            port.record(auth, ref, at)
    assert len(calls) == 2
