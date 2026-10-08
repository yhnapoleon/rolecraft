"""Offline candidate extraction at the real PM HTTP and engineer CLI boundaries."""

import json
from typing import Any

import pytest
from test_w13_pack import Session
from test_w13_pack import session as session


def create_plan(session: Session) -> dict[str, Any]:
    app, _, _, _, send, _, _, _, _ = session
    query = (
        "Can we change the pilot?"
        if app.state.scenario_v2.work_language == "en"
        else "能调整试点吗？"
    )
    return send(
        "work-products",
        "plan",
        "work_products.create",
        {
            "kind": "test_plan",
            "content": "Original plan",
            "structured_payload": {
                "type": "test_plan",
                "cases": [
                    {
                        "id": "case-a",
                        "query": query,
                        "intent": "Investigate scope",
                        "declared_category": "wish",
                        "declared_expected": "Everything succeeds",
                    }
                ],
            },
        },
    )["result"]["object"]


def test_plan_exports_intent_only(session: Session) -> None:
    app, client, sid, headers, _, _, cli, root, _ = session
    product = create_plan(session)
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    suite = (app.state.scenario_v2.package.root / "probes.json").read_bytes()
    result = cli(
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--output",
        str(root / "candidates"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((root / "candidates/candidates.json").read_text())
    candidate = manifest["candidates"][0]
    original = product["structured_payload"]["cases"][0]
    assert candidate["source_case"] == original
    assert candidate["original_text"] == original["query"]
    assert candidate["test_intent"]["declared_expected"] == "Everything succeeds"
    assert candidate["status"] == "pending_review" and candidate["truth_status"] == "unverified"
    assert candidate["training_eligible"] is False and candidate["optimization_eligible"] is False
    assert "expected" not in candidate and "result" not in candidate and "gold" not in candidate
    assert manifest["suite_published"] is False
    assert manifest["source"]["product_ref"]["version"] == 1
    assert manifest["source"]["work_language"] == app.state.scenario_v2.work_language
    assert manifest["source"]["structure_id"] == app.state.scenario_v2.package.bundle.structure_id
    assert manifest["source"]["split"] == app.state.scenario_v2.package.bundle.split
    assert json.loads((root / "candidates/source-product.json").read_text()) == product
    assert (app.state.scenario_v2.package.root / "probes.json").read_bytes() == suite
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_confirmed_free_text_remains_unverified(session: Session) -> None:
    app, _, _, _, send, _, cli, root, _ = session
    body = "Could this work?" if app.state.scenario_v2.work_language == "en" else "这样可行吗？"
    product = send(
        "work-products",
        "notes",
        "work_products.create",
        {"kind": "text", "content": "Prefix " + body + " suffix"},
    )["result"]["object"]
    result = cli(
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--span",
        f"7:{7 + len(body)}",
        "--confirm-extraction",
        "--output",
        str(root / "candidates"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads((root / "candidates/candidates.json").read_text())
    candidate = output["candidates"][0]
    assert candidate["original_text"] == body
    assert candidate["source_location"] == {"field": "content", "start": 7, "end": 7 + len(body)}
    assert candidate["confirmation"]["executor"] == output["executor"]
    assert candidate["confirmation"]["source_content_hash"] == product["content_hash"]
    assert candidate["status"] == "pending_review" and candidate["truth_status"] == "unverified"
    assert candidate["test_intent"]["declared_expected"] is None
    assert "result" not in candidate and "expected" not in candidate


@pytest.mark.parametrize(
    "damage", ["missing", "version", "zero", "empty_plan", "blank_query", "large_query"]
)
def test_invalid_plan_sources_fail(session: Session, damage: str) -> None:
    _, _, _, _, send, _, cli, root, _ = session
    if damage in {"empty_plan", "blank_query", "large_query"}:
        cases = (
            []
            if damage == "empty_plan"
            else [{"id": "invalid", "query": "x" * 4001 if damage == "large_query" else "  "}]
        )
        product = send(
            "work-products",
            "invalid-plan",
            "work_products.create",
            {"kind": "test_plan", "structured_payload": {"type": "test_plan", "cases": cases}},
        )["result"]["object"]
    else:
        product = create_plan(session)
    result = cli(
        "probes-from-plan",
        "--product",
        "missing" if damage == "missing" else product["product_id"],
        "--product-version",
        "99" if damage == "version" else "0" if damage == "zero" else "1",
        "--output",
        str(root / "candidates"),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "failed"
    assert not (root / "candidates").exists()


@pytest.mark.parametrize(
    "selection",
    [
        ["--span", "0:1"],
        ["--confirm-extraction"],
        ["--confirm-extraction", "--span=-1:2"],
        ["--confirm-extraction", "--span", "0:999"],
        ["--confirm-extraction", "--span", "1:1"],
        ["--confirm-extraction", "--span", "bad"],
        ["--confirm-extraction", "--span", "0:2", "--span", "1:3"],
        ["--confirm-extraction", "--span", "0:1", "--text-field", "body"],
        ["--confirm-extraction", "--span", "4:5"],
    ],
)
def test_free_text_requires_confirmed_valid_spans(session: Session, selection: list[str]) -> None:
    _, _, _, _, send, _, cli, root, _ = session
    product = send(
        "work-products",
        "text",
        "work_products.create",
        {"kind": "text", "content": "Text question"},
    )["result"]["object"]
    result = cli(
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        *selection,
        "--output",
        str(root / "candidates"),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["code"].startswith("engineer_")
    assert not (root / "candidates").exists()


def test_exact_product_versions_are_immutable(session: Session) -> None:
    app, _, _, _, send, _, cli, root, _ = session
    product = create_plan(session)
    args = ("probes-from-plan", "--product", product["product_id"])
    assert cli(*args, "--product-version", "1", "--output", str(root / "old")).returncode == 0
    frozen = {p.name: p.read_bytes() for p in (root / "old").iterdir()}
    suite = (app.state.scenario_v2.package.root / "probes.json").read_bytes()
    changed = send(
        "work-products/" + product["product_id"] + "/versions",
        "revised",
        "work_products.versions.create",
        {
            "product_id": product["product_id"],
            "expected_head": 1,
            "kind": "test_plan",
            "structured_payload": {
                "type": "test_plan",
                "cases": [{"id": "case-a", "query": "A different question?"}],
            },
        },
    )["result"]["object"]
    assert changed["version"] == 2
    for version, name in ((1, "old-version-again"), (2, "new")):
        result = cli(*args, "--product-version", str(version), "--output", str(root / name))
        assert result.returncode == 0, result.stdout + result.stderr
        exported = json.loads((root / name / "source-product.json").read_text())
        assert exported == (product if version == 1 else changed)
    assert {p.name: p.read_bytes() for p in (root / "old").iterdir()} == frozen
    assert (app.state.scenario_v2.package.root / "probes.json").read_bytes() == suite
    old = json.loads((root / "old/candidates.json").read_text())
    new = json.loads((root / "new/candidates.json").read_text())
    assert old["id"] != new["id"]


@pytest.mark.parametrize("restriction", ["object", "action", "revoked"])
def test_candidate_export_rechecks_current_authorization(
    session: Session, restriction: str
) -> None:
    from datetime import UTC, datetime, timedelta

    _, _, _, _, send, _, cli, root, credentials = session
    product = create_plan(session)
    payload: dict[str, Any] = {
        "agent_label": "candidate-reviewer",
        "capabilities": ["read"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    if restriction == "object":
        payload["allowed_objects"] = ["unrelated-product"]
    if restriction == "action":
        payload["allowed_actions"] = ["tests.list"]
    grant = send("delegations", "grant", "delegations.create", payload)["result"]["result"]
    original = json.loads(credentials.read_text())
    delegated = {**original, "token": grant["token"]}
    credentials.write_text(json.dumps(delegated))
    args = (
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--output",
        str(root / "candidates"),
    )
    if restriction == "revoked":
        assert cli(*args).returncode == 0
        original_files = {p.name: p.read_bytes() for p in (root / "candidates").iterdir()}
        output = json.loads((root / "candidates/candidates.json").read_text())
        assert output["executor"]["kind"] == "external_agent"
        did = grant["delegation"]["id"]
        send(
            "delegations/" + did,
            "revoke",
            "delegations.revoke",
            {"delegation_id": did},
            method="DELETE",
        )
    result = cli(*args)
    assert result.returncode == 1, result.stdout + result.stderr
    assert grant["token"] not in result.stdout + result.stderr
    if restriction == "revoked":
        assert {p.name: p.read_bytes() for p in (root / "candidates").iterdir()} == original_files
    else:
        assert not (root / "candidates").exists()


@pytest.mark.parametrize(
    "session",
    [
        {"language": "zh", "split": "test"},
        {"language": "en", "split": "test"},
    ],
    indirect=True,
    ids=["zh-test", "en-test"],
)
def test_candidate_split_is_not_overridable(session: Session) -> None:
    app, _, _, _, _, _, cli, root, _ = session
    product = create_plan(session)
    args = ("probes-from-plan", "--product", product["product_id"], "--product-version", "1")
    result = cli(*args, "--output", str(root / "relabelled"), "--split", "train")
    assert result.returncode != 0 and not (root / "relabelled").exists()
    assert cli(*args, "--output", str(root / "candidate")).returncode == 0
    output = json.loads((root / "candidate/candidates.json").read_text())
    assert output["source"]["split"] == app.state.scenario_v2.package.bundle.split == "test"
    assert all(
        row["allowed_usage"] == "review_only"
        and not row["training_eligible"]
        and not row["optimization_eligible"]
        for row in output["candidates"]
    )


def test_candidate_output_is_immutable(session: Session) -> None:
    _, _, _, _, _, _, cli, root, _ = session
    product = create_plan(session)
    args = (
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--output",
        str(root / "candidates"),
    )
    first = cli(*args)
    assert first.returncode == 0
    original = {p.name: p.read_bytes() for p in (root / "candidates").iterdir()}
    assert cli(*args).stdout == first.stdout
    assert {p.name: p.read_bytes() for p in (root / "candidates").iterdir()} == original
    report = root / "candidates/candidates.json"
    report.write_text('{"status":"approved","split":"train"}')
    changed = report.read_bytes()
    result = cli(*args)
    assert result.returncode == 1 and json.loads(result.stdout)["code"] == "engineer_pack_changed"
    assert report.read_bytes() == changed


def test_text_payload_body_requires_explicit_selection(session: Session) -> None:
    _, _, _, _, send, _, cli, root, _ = session
    product = send(
        "work-products",
        "body",
        "work_products.create",
        {
            "kind": "text",
            "content": "Other text",
            "structured_payload": {"type": "text", "body": "Question?"},
        },
    )["result"]["object"]
    result = cli(
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--text-field",
        "body",
        "--span",
        "0:9",
        "--confirm-extraction",
        "--output",
        str(root / "candidates"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    candidate = json.loads((root / "candidates/candidates.json").read_text())["candidates"][0]
    assert (
        candidate["original_text"] == "Question?"
        and candidate["source_location"]["field"] == "body"
    )


@pytest.mark.parametrize(
    "session",
    [{"language": "zh", "split": "test"}, {"language": "en", "split": "test"}],
    indirect=True,
    ids=["zh-test", "en-test"],
)
def test_published_split_fixture_rejects_changed_content(session: Session) -> None:
    app, _, _, _, _, _, cli, root, _ = session
    product = create_plan(session)
    path = app.state.scenario_v2.package.root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["lineage"].append("changed-after-publication")
    path.write_text(json.dumps(manifest))
    result = cli(
        "probes-from-plan",
        "--product",
        product["product_id"],
        "--product-version",
        "1",
        "--output",
        str(root / "rejected"),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["code"] == "release_content_mismatch"
    assert not (root / "rejected").exists()
