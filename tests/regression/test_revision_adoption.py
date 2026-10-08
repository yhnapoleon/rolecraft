"""Gateway adoption and parent-version snapshot compatibility after opening a revision."""

import json
from pathlib import Path

from pydantic import JsonValue

from career_lab.api.modules import ExtensionRegistry, Gateway
from career_lab.contracts import v2 as C
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.v2_store import V2Store
from career_lab.workspace.extension import install_workspace_operations
from tests.contracts.expansion_v3.conftest import command
from tests.contracts.expansion_v3.conftest import foundation as foundation
from tests.contracts.expansion_v3.test_review_r6 import revise, submit

Foundation = tuple[V2Store, C.AuthContext, str, C.SessionBindings, C.AssistantConfig]


def adopt_after_revision(store: V2Store, owner: C.AuthContext) -> dict[str, JsonValue]:
    registry = ExtensionRegistry()
    install_workspace_operations(registry, roles=("supervisor", "business_lead", "tech_lead"))
    gateway = Gateway(store, registry)

    def dispatch(operation: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        envelope = command(store.view(owner), operation, operation).model_copy(
            update={"payload": payload}
        )
        return gateway.dispatch(owner, operation, envelope.model_dump(mode="json"))

    created = dispatch("work_products.create", {"kind": "text", "content": "Original work"})
    original = created["result"]["object"]
    ref = C.ObjectRef.model_validate(created["result"]["ref"])
    before = store.read(owner, ref)
    submitted = submit(store, owner)
    revise(store, owner, submitted)
    adopted = dispatch(
        "work_products.adopt",
        {
            "product_id": original["product_id"],
            "product_version": 1,
            "expected_head": 1,
            "status": "adopted",
        },
    )["result"]["object"]
    assert adopted["version"] == 2
    assert adopted["adoption"]["status"] == "adopted"
    assert adopted["cycle"] == original["cycle"]
    assert adopted["content"] == original["content"]
    assert store.read(owner, ref) == before
    assert adopted["cycle"]["object_id"] != store.view(owner).state.cycle_id
    return adopted


def test_gateway_adopts_old_cycle_product_after_revision_opens(foundation: Foundation) -> None:
    store, owner, *_ = foundation
    adopt_after_revision(store, owner)


def test_restore_accepts_parent_snapshot_with_old_cycle_adoption(foundation: Foundation) -> None:
    store, *_ = foundation
    saved = json.loads(
        Path(__file__).with_name("fixtures").joinpath("prior-cycle-adoption.json").read_text()
    )
    assert saved["producer_commit"] == "b33bd6a6bbbaf7075a97bc0d00d6b19811c7e560"
    snapshot = C.SnapshotExport.model_validate(saved["snapshot"])
    restored, token = SnapshotService(store).restore(snapshot, session_id="adoption-restored")
    owner = store.authenticate(restored.session_id, token)
    products = [row for row in store.view(owner).objects if row.ref.kind == "product"]
    adopted = next(row for row in products if row.ref.version == 2)
    original = next(row for row in products if row.ref.version == 1)
    assert adopted.content["adoption"]["status"] == "adopted"
    assert adopted.content["content"] == original.content["content"]
    assert adopted.content["cycle"] == original.content["cycle"]
    assert adopted.content["cycle"]["object_id"] != restored.state.cycle_id


def test_contract_export_preserves_recorded_error_codes(tmp_path: Path) -> None:
    from career_lab.contracts.v2.export import export

    root = Path(__file__).resolve().parents[2]
    export(root, tmp_path)
    frozen = json.loads((root / "docs/contracts/expansion-v3/errors.json").read_text())
    generated = json.loads((tmp_path / "errors.json").read_text())
    assert set(frozen["codes"]) <= set(generated["codes"])
    assert "product_cycle_closed" not in generated["codes"]
    assert "revision_cycle_closed" not in generated["codes"]
