"""Shared real-HTTP samples for the fixed parent response corpus."""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C

IMPORTS = {
    "test_case_revision_zero": {
        "id": "import-product",
        "kind": "test_set",
        "cases": [{"id": "case", "revision": 0, "question": "Question"}],
    },
    "investigation_block_revision_zero": {
        "id": "import-product",
        "kind": "investigation",
        "blocks": [{"id": "block", "type": "note", "revision": 0}],
    },
    "investigation_review_focus_invalid": {
        "id": "import-product",
        "kind": "investigation",
        "blocks": [],
        "review": {"focus": "invalid"},
    },
    "test_case_id_missing": {
        "id": "import-product",
        "kind": "test_set",
        "cases": [{"question": "Question"}],
    },
    "legacy_raw_purpose": {"id": "import-product", "kind": "text", "purpose": 7},
}
CASES = (
    *IMPORTS,
    "empty_pilot_plan",
    "invalid_object_version",
    "negative_configuration_participants",
    "unclassified_value",
    "unclassified_key",
    "unknown_scenario",
    "unknown_role",
)


def response_fields(response: httpx.Response) -> dict[str, object]:
    return {
        "status": response.status_code,
        "body": response.json(),
        "headers": dict(response.headers),
    }


def sample(directory: Path, case: str) -> dict[str, object]:
    app = create_runtime_app("sqlite:///" + str(directory / (case + ".db")), provider="local")

    @app.get("/value-error")
    def value_error() -> None:
        raise ValueError("parent validation text")

    @app.get("/key-error")
    def key_error() -> None:
        raise KeyError("parent lookup")

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            if case.startswith("unclassified_"):
                return response_fields(
                    client.get("/value-error" if case.endswith("value") else "/key-error")
                )
            if case == "unknown_scenario":
                return response_fields(client.post("/sessions", json={"scenario": "missing"}))
            v2 = case not in {"empty_pilot_plan", "unknown_role"}
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "zh"}
                if v2
                else {},
            ).json()
            sid = created["session_id"]
            headers = {"Authorization": "Bearer " + created["token"]}
            if case == "unknown_role":
                return response_fields(
                    client.post(
                        f"/sessions/{sid}/turns",
                        headers=headers,
                        json={
                            "role_id": "missing",
                            "text": "Question",
                            "request_id": "invalid-role",
                        },
                    )
                )
            if case in IMPORTS:
                raw = IMPORTS[case]
                item = C.LegacyProvenance(
                    source_schema="browser-v1",
                    source_session_id="browser-session",
                    original_id="import-product",
                    original_kind=raw["kind"],
                    raw=raw,
                    original_hash=C.digest(raw),
                )
                payload = C.WorkspaceImport(
                    package_id="import-input-probe",
                    mode="preview",
                    source_schema="browser-v1",
                    source_session_id="browser-session",
                    items=(item,),
                    package_hash=C.digest([item.model_dump(mode="json")]),
                )
                command = C.Command(
                    schema_version=2,
                    request_id="import-input-probe",
                    operation="workspace_imports",
                    expected_version=0,
                    expected_workspace_revision=0,
                    payload=payload.model_dump(mode="json"),
                )
                response = client.post(
                    f"/sessions/{sid}/workspace-imports",
                    headers=headers,
                    json=command.model_dump(mode="json"),
                )
            elif case == "empty_pilot_plan":
                response = client.post(
                    f"/sessions/{sid}/actions",
                    headers=headers,
                    json={
                        "tool": "update_pilot",
                        "arguments": {"plan": {}},
                        "request_id": "invalid-plan",
                        "expected_version": 0,
                    },
                )
            elif case == "invalid_object_version":
                response = client.get(f"/sessions/{sid}/objects/product/work/0", headers=headers)
            else:
                config = client.get(f"/sessions/{sid}/workbench", headers=headers).json()["result"][
                    "result"
                ]["timeline"]["workspace"]["config"]
                base = {
                    "session_id": sid,
                    "kind": "config",
                    "object_id": config["id"],
                    "version": config["version"],
                    "config_version": config["config_version"],
                }
                response = client.post(
                    f"/sessions/{sid}/configuration",
                    headers=headers,
                    json={
                        "schema_version": 2,
                        "request_id": "invalid-settings",
                        "expected_version": 0,
                        "expected_workspace_revision": 0,
                        "operation": "configuration.apply",
                        "payload": {"base": base, "settings": {"participants": -1}},
                    },
                )
            return response_fields(response)
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


INTERNAL_CASES = (
    "persisted_sources_missing",
    "persisted_coordinate_missing",
    "persisted_state_invalid",
    "persisted_source_ref_invalid",
)


def internal_sample(directory: Path, case: str) -> dict[str, object]:
    import json

    from sqlalchemy import select, update

    from career_lab.api.feedback import feedback_id
    from career_lab.storage.database import sessions
    from career_lab.storage.v2_tables import v2_objects

    app = create_runtime_app("sqlite:///" + str(directory / (case + ".db")), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            v2 = case == "persisted_source_ref_invalid"
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "zh"}
                if v2
                else {},
            ).json()
            sid = created["session_id"]
            headers = {"Authorization": "Bearer " + created["token"]}
            if case == "persisted_state_invalid":
                with app.state.store.db.transaction() as connection:
                    connection.execute(
                        update(sessions).where(sessions.c.id == sid).values(state="{}")
                    )
                response = client.get(f"/sessions/{sid}", headers=headers)
            elif not v2:
                report = {"as_of_seq": 0}
                if case == "persisted_coordinate_missing":
                    report["sources"] = {"known": {"evidence": {}}}
                app.state.store.save_derived(
                    sid, "submission", "submission", {"model_revision": "fixture"}
                )
                app.state.store.save_derived(
                    sid, feedback_id(app.state.store, sid, "submission"), "feedback", report
                )
                response = client.get(
                    f"/sessions/{sid}/evidence/submission/known/evidence", headers=headers
                )
            else:
                request = {
                    "schema_version": 2,
                    "request_id": "source-test",
                    "operation": "tests.create",
                    "expected_version": 0,
                    "expected_workspace_revision": 0,
                    "payload": {"query": "Question", "config_version": 0},
                }
                response = client.post(f"/sessions/{sid}/tests", headers=headers, json=request)
                assert response.status_code == 200, response.text
                with app.state.v2_store.db.transaction() as connection:
                    row = (
                        connection.execute(
                            select(v2_objects).where(
                                v2_objects.c.session_id == sid, v2_objects.c.kind == "test"
                            )
                        )
                        .mappings()
                        .one()
                    )
                    record = json.loads(row["record"])
                    record["content"]["citations"] = [{"object_id": "damaged-source", "version": 1}]
                    connection.execute(
                        update(v2_objects)
                        .where(v2_objects.c.session_id == sid, v2_objects.c.kind == "test")
                        .values(record=json.dumps(record))
                    )
                raw = {
                    "id": "import-product",
                    "kind": "investigation",
                    "blocks": [
                        {
                            "id": "block",
                            "type": "source_check",
                            "material": {"id": "damaged-source", "version": 1},
                        }
                    ],
                }
                item = C.LegacyProvenance(
                    source_schema="browser-v1",
                    source_session_id=sid,
                    original_id="import-product",
                    original_kind="investigation",
                    raw=raw,
                    original_hash=C.digest(raw),
                )
                payload = C.WorkspaceImport(
                    package_id="import-input-probe",
                    mode="preview",
                    source_schema="browser-v1",
                    source_session_id=sid,
                    items=(item,),
                    package_hash=C.digest([item.model_dump(mode="json")]),
                )
                state = client.get(f"/sessions/{sid}", headers=headers).json()["state"]
                command = C.Command(
                    schema_version=2,
                    request_id="import-input-probe",
                    operation="workspace_imports",
                    expected_version=state["business_seq"],
                    expected_workspace_revision=state["workspace_revision"],
                    payload=payload.model_dump(mode="json"),
                )
                response = client.post(
                    f"/sessions/{sid}/workspace-imports",
                    headers=headers,
                    json=command.model_dump(mode="json"),
                )
            return response_fields(response)
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
