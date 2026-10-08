import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from career_lab.contracts.v2.core import digest, ProtocolError, PageRequest
from legacy_router_fixture import create_router
from conftest import command, do, product


def bundle(mode="preview", **extra):
    raws = [
        ("task", {"id": "task-a", "title": "我的调查", "note": "先测试", "priority": "later"}),
        (
            "test_set",
            {
                "id": "work-a",
                "taskId": "task-a",
                "kind": "test_set",
                "revision": 4,
                "title": "测试计划",
                "purpose": "测试计划",
                "body": "原文",
                "adopted": True,
                "cases": [
                    {
                        "id": "case-a",
                        "revision": 3,
                        "question": "政策？",
                        "expectation": "待验证",
                        "intent": "核对版本",
                        "refs": [{"id": "policy", "version": 2}],
                    }
                ],
                "draft": {"body": "未保存草稿"},
                "sourceHistory": [{"revision": 1, "body": "更早原文"}],
            },
        ),
    ]
    items = [
        {
            "source_schema": "browser-v1",
            "source_session_id": "legacy",
            "original_id": raw["id"],
            "original_kind": kind,
            "original_purpose": raw.get("purpose"),
            "raw": raw,
            "original_hash": digest(raw),
        }
        for kind, raw in raws
    ]
    from career_lab.contracts.v2.workspace import LegacyProvenance

    items = [LegacyProvenance.model_validate(i).model_dump(mode="json") for i in items]
    return {
        "package_id": "pkg-1",
        "mode": mode,
        "source_schema": "browser-v1",
        "source_session_id": "legacy",
        "items": items,
        "references": [],
        "package_hash": digest(items),
        **extra,
    }


def test_preview_has_no_effect_apply_is_atomic_and_repeatable(env):
    p = bundle()
    preview = do(env, "workspace_imports", p)
    assert not preview["applied"] and preview["unresolved"][0]["status"] == "foreign_session"
    assert env["service"].list(env["auth"], "product", PageRequest())["items"] == []
    p.update(mode="apply", preview_storage_revision=preview["as_of"]["storage_revision"])
    cmd = command(env, "workspace_imports", p, request_id="apply")
    result = env["service"].execute(env["auth"], cmd)
    assert result["applied"] and result["id_map"] == preview["id_map"]
    assert env["service"].execute(env["auth"], cmd) == result
    assert do(env, "workspace_imports", p) == result
    saved = env["service"].list(env["auth"], "product", PageRequest())["items"][0]
    assert saved["kind"] == "test_plan" and saved["adoption"]["status"] == "unadopted"
    assert saved["legacy"]["raw"]["draft"]["body"] == "未保存草稿"
    assert saved["legacy"]["raw"]["sourceHistory"][0]["body"] == "更早原文"
    assert saved["structured_payload"]["cases"][0]["run"] is None
    assert saved["structured_payload"]["cases"][0]["intent"] == "核对版本"
    assert saved["task"]["object_id"] == result["id_map"]["task-a"]["object_id"]
    assert (
        result["id_map"]["work-a@v1"]["version"] == 1
        and result["id_map"]["work-a@v4"]["version"] == 2
    )
    assert "work-a@v2" not in result["id_map"]
    assert {
        c["original_version"] for c in result["conflicts"] if c["reason"] == "missing_history"
    } == {2, 3}
    assert any(v["original_version"] == 2 and v["target"] is None for v in result["version_map"])
    assert env["service"].get_product(env["auth"], saved["product_id"], 1)["content"] == "更早原文"
    do(
        env,
        "work_products.shares.create",
        {
            "product_id": saved["product_id"],
            "product_version": saved["version"],
            "recipient_role": "tech_lead",
        },
    )
    role = env["auth"].model_copy(update={"actor_id": "tech_lead", "capabilities": ("read",)})
    shared = env["service"].get_product(role, saved["product_id"], saved["version"])
    assert shared["legacy"] is None and "未保存草稿" not in str(shared)
    assert shared["content_hash"] == saved["content_hash"]


def test_import_stale_preview_requires_user_repreview(env):
    p = bundle()
    preview = do(env, "workspace_imports", p)
    product(env)
    p.update(mode="apply", preview_storage_revision=preview["as_of"]["storage_revision"])
    with pytest.raises(ProtocolError, match="import preview stale"):
        do(env, "workspace_imports", p)
    assert len(env["service"].list(env["auth"], "product", PageRequest())["items"]) == 1


@pytest.mark.parametrize(
    "key", ["token", "session_token", "Authorization", "apiKey", "access-token", "password"]
)
def test_credentials_rejected_and_not_echoed(env, key):
    p = bundle()
    p["items"][1]["raw"][key] = "secret-value"
    with pytest.raises(ProtocolError, match="credentials not importable") as e:
        do(env, "workspace_imports", p)
    assert "secret-value" not in str(e.value)


def test_module_router_scoped_errors_and_persistent_crud(env):
    app = FastAPI()
    current = {"auth": env["auth"]}
    app.include_router(create_router(env["service"], lambda: current["auth"]))
    client = TestClient(app)
    cmd = command(env, "work_products.create", {"kind": "text", "content": "私密正文"})
    response = client.post("/sessions/s/work-products", json=cmd.model_dump(mode="json"))
    assert response.status_code == 200
    p = response.json()["object"]
    assert client.get("/sessions/other/work-products").status_code == 404
    assert (
        client.get(f"/sessions/s/work-products/{p['product_id']}/versions/1").json()["content"]
        == "私密正文"
    )
    invalid = command(
        env,
        "work_products.create",
        {"kind": "text", "executor": {"kind": "human"}, "content": "不能出现在错误详情"},
    ).model_dump(mode="json")
    bad = client.post("/sessions/s/work-products", json=invalid)
    assert bad.status_code == 422 and "不能出现在错误详情" not in bad.text
    current["auth"] = env["auth"].model_copy(
        update={"actor_id": "tech_lead", "capabilities": ("read",)}
    )
    hidden = client.get(f"/sessions/s/work-products/{p['product_id']}/versions/1")
    assert hidden.status_code == 404 and "私密" not in hidden.text
    assert client.get("/sessions/s/work-products").json()["items"] == []
    assert client.get("/sessions/s/work-items?limit=101").status_code == 422
    assert client.get("/sessions/s/work-items?cursor=-1").status_code == 422


def test_import_rolls_back_all_objects_and_retries_original_command(env):
    p = bundle()
    preview = do(env, "workspace_imports", p)
    p.update(mode="apply", preview_storage_revision=preview["as_of"]["storage_revision"])
    cmd = command(env, "workspace_imports", p)
    env["authority"].fail_after_advance = True
    with pytest.raises(RuntimeError):
        env["service"].execute(env["auth"], cmd)
    assert env["service"].list(env["auth"], "product", PageRequest())["items"] == []
    assert env["service"].list(env["auth"], "task", PageRequest())["items"] == []
    env["authority"].fail_after_advance = False
    result = env["service"].execute(env["auth"], cmd)
    assert result["id_map"] == preview["id_map"]


def test_package_reuse_with_changed_content_is_conflict(env):
    p = bundle()
    preview = do(env, "workspace_imports", p)
    do(
        env,
        "workspace_imports",
        {**p, "mode": "apply", "preview_storage_revision": preview["as_of"]["storage_revision"]},
    )
    p["items"][1]["raw"]["body"] = "不同的内容"
    p["items"][1]["original_hash"] = digest(p["items"][1]["raw"])
    p["package_hash"] = digest(p["items"])
    with pytest.raises(ProtocolError, match="import package conflict"):
        do(env, "workspace_imports", p)


def test_formal_legacy_investigation_keeps_blocks_focus_and_unresolved_links(env):
    from career_lab.contracts.v2.workspace import LegacyProvenance

    raw = {
        "id": "investigation",
        "kind": "investigation",
        "revision": 1,
        "title": "调查",
        "purpose": "探索笔记",
        "question": "哪一版有问题？",
        "body": "原调查正文",
        "blocks": [
            {"id": "n", "type": "note", "title": "假设", "text": "可能是索引"},
            {"id": "compare", "type": "test_compare", "testIds": ["old-test"]},
            {
                "id": "source",
                "type": "source_check",
                "testId": "old-test",
                "material": {"id": "policy", "version": 2},
            },
            {"id": "retry", "type": "retest", "testId": "old-test"},
        ],
        "review": {"focus": "index", "note": "先核对版本"},
    }
    item = LegacyProvenance(
        source_schema="browser-v1",
        source_session_id="old-session",
        original_id=raw["id"],
        original_kind="investigation",
        original_purpose=raw["purpose"],
        raw=raw,
        original_hash=digest(raw),
    ).model_dump(mode="json")
    p = {
        "package_id": "investigation-pack",
        "mode": "preview",
        "source_schema": "browser-v1",
        "source_session_id": "old-session",
        "items": [item],
        "package_hash": digest([item]),
    }
    preview = do(env, "workspace_imports", p)
    p.update(mode="apply", preview_storage_revision=preview["as_of"]["storage_revision"])
    result = do(env, "workspace_imports", p)
    saved = env["service"].get_product(env["auth"], result["id_map"]["investigation"]["object_id"])
    assert saved["legacy"]["raw"] == raw
    structure = saved["structured_payload"]
    assert structure["review_focus"] == "index" and structure["review_direction"] == "unknown"
    assert [b["type"] for b in structure["blocks"]] == [
        "note",
        "test_compare",
        "source_check",
        "retest",
    ]
    assert (
        structure["blocks"][1]["test_refs"] == [] and structure["blocks"][2]["source_ref"] is None
    )
    assert any(
        r["original_id"] == "old-test" and r["status"] == "foreign_session"
        for r in result["unresolved"]
    )
