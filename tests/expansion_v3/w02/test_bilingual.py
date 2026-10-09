"""LANG-W02: paired facts, language-original citations and real locale assemblies."""

from pathlib import Path
import hashlib, json, os, re, socket, subprocess, time
from dataclasses import replace
import httpx
import pytest

from career_lab.api.modules import CreateSessionV2
from career_lab.contracts.v2 import ObjectRef, ProtocolError, TestRequestV2 as AssistantRequest
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.scenarios.v2.public_cases import run_pre_event_trial
from career_lab.scenarios.v2.probes import run_probes
from career_lab.storage.v2_store import V2Store
from career_lab.assistant.v2 import Assistant
from .conftest import auth, apply
from .test_reference_http import LiveScenario, redact
from tests.support.scenario_packages import installed_root

ROOT = Path(__file__).resolve().parents[3]
PACK = installed_root()


def packages():
    return {locale: ScenarioModule(PACK, work_language=locale).package for locale in ("zh", "en")}


def test_languages_share_canonical_facts_permissions_business_rules_and_split():
    p = packages()
    zh, en = p["zh"], p["en"]
    assert (
        zh.locale_metadata["canonical_fact_root_id"] == en.locale_metadata["canonical_fact_root_id"]
    )
    assert zh.locale_metadata["lineage"] == en.locale_metadata["lineage"]
    assert zh.bundle.lineage == en.bundle.lineage and zh.bundle.split == en.bundle.split == "train"
    assert zh.content_hash != en.content_hash
    for key in (
        "work_costs",
        "approval_limits",
        "approval_requirements",
        "initial_material_versions",
        "initial_plan_material_updates",
    ):
        assert zh.rules[key] == en.rules[key]
    for a, b in zip(zh.bundle.role_specs, en.bundle.role_specs):
        for key in (
            "id",
            "known_materials",
            "known_facts",
            "approval_authority",
            "event_subscriptions",
        ):
            assert getattr(a, key) == getattr(b, key)
        assert a.name != b.name
    for key, a in zh.locale_metadata["facts"].items():
        b = en.locale_metadata["facts"][key]
        for field in ("id", "version", "value", "unit", "material_id", "paragraph_index"):
            assert a[field] == b[field]
        if isinstance(a["value"], (int, float)):
            assert a["display_value"] == b["display_value"]
    for locale, package in p.items():
        for material in package.materials:
            path = (
                package.root / package.rules["material_files"][material.id][str(material.version)]
            )
            raw = path.read_bytes()
            text = raw.decode()
            meta = next(
                m
                for m in package.locale_metadata["materials"]
                if (m["id"], m["version"]) == (material.id, material.version)
            )
            assert meta["locale"] == locale and meta["sha256"] == hashlib.sha256(raw).hexdigest()
            for fragment in material.fragments:
                assert (
                    text[fragment.ref.span_start : fragment.ref.span_end]
                    == fragment.ref.quote
                    == fragment.text
                )


def test_english_initial_materials_are_english_and_no_future_or_private_values_are_published():
    package = packages()["en"]
    engine = ScenarioEngine(package)
    state = engine.initial("session")
    visible = package.visible_materials(state.source_versions, "learner", 0, "session")
    text = "\n".join(meta.title + "\n" + "\n".join(f.text for f in fs) for meta, fs in visible)
    assert not re.search(r"[\u4e00-\u9fff]", text)
    assert "429" in text and "45" in text and "SD-120" in text and "COORD-01" in text
    assert "CNY 400" not in text and "day 4" not in text and "Sales Support" not in text
    assert "NEVER_W02_7C9E" not in text and "TR-TRAIN-01" not in text
    for mid in ("policy", "demo", "scope_note"):
        with pytest.raises(ProtocolError):
            engine.read(
                state,
                ObjectRef(session_id="session", kind="material", object_id=mid, version=2),
                auth(),
            )
    for mid in ("tech_private", "tech_diagnostics", "world_private"):
        with pytest.raises(ProtocolError):
            engine.read(
                state,
                ObjectRef(session_id="session", kind="material", object_id=mid, version=1),
                auth(),
            )


def test_english_public_trials_replay_and_calibration_uses_development_data_only():
    from datetime import datetime

    package = packages()["en"]
    data = json.loads((package.root / "research/public-case-records.json").read_bytes())
    assert data["locale"] == "en" and len(data["records"]) == 12
    for record in data["records"]:
        result = record["result"]
        replay = run_pre_event_trial(
            package,
            record["trial_id"],
            result["query"],
            record["input_snapshot"]["config"],
            now=datetime.fromisoformat(result["execution"]["executed_at"]),
        )
        assert replay["result"] == result
        assert (
            result["execution"]["source_versions"]["policy"]
            == result["execution"]["indexed_versions"]["policy"]
            == 1
        )
        assert result["as_of"]["business_seq"] == 0
    calibration = json.loads((package.root / "research/retrieval-calibration.json").read_bytes())
    assert (
        not calibration["held_out"] and not calibration["hidden_probe_or_gold_used_for_selection"]
    )
    assert calibration["selected_threshold"] == package.bundle.baseline_config.min_score == 0.3
    for path, expected in calibration["knowledge_files"].items():
        assert hashlib.sha256((package.root / path).read_bytes()).hexdigest() == expected


@pytest.fixture(params=("zh", "en"))
def bilingual_live(request, tmp_path):
    locale = request.param
    module = ScenarioModule(PACK, work_language=locale)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    database = "sqlite:///" + str(tmp_path / "locale.db")
    command = [
        str(ROOT / ".venv/bin/python"),
        "-m",
        "career_lab.scenarios.v2",
        "serve",
        str(PACK),
        "--work-language",
        locale,
        "--database-url",
        database,
        "--port",
        str(port),
    ]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    log = (tmp_path / "server.log").open("w")
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    live = None
    store = None
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError("locale server exited")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("locale startup timeout")
            store = V2Store(database)
            live = LiveScenario(client, store)
            assert store.view(live.owner).bindings.scenario.sha256 == module.package.content_hash
            yield locale, live, module
    finally:
        if live is not None:
            (tmp_path / "bilingual-http.json").write_text(
                json.dumps(
                    {
                        "mode": "actual_loopback_locale_assembly_on_fixed_c2",
                        "locale": locale,
                        "scenario_hash": module.package.content_hash,
                        "shared_work_language_field_present": "work_language"
                        in CreateSessionV2.model_fields,
                        "worker_ui_online_model_verified": False,
                        "steps": live.steps,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        if store is not None:
            store.db.engine.dispose()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def test_paired_http_initial_policy_refresh_history_and_recovery(bilingual_live):
    locale, live, module = bilingual_live
    question = (
        "住宿报销上限是多少？"
        if locale == "zh"
        else "What is the hotel reimbursement limit per night?"
    )
    first, body = live.post("tests", "c0", "tests.create", {"query": question, "config_version": 0})
    assert first.status_code == 200, first.text
    result = first.json()["result"]["test"]
    assert "500" in result["answer"] and result["citations"][0]["version"] == 1
    if locale == "en":
        assert not re.search(r"[\u4e00-\u9fff]", result["answer"])
    config = result["config"]["requested"] | {
        "version": 2,
        "config_version": 1,
        "freshness_guard": "warn",
    }
    applied, _ = live.post(
        "actions", "apply", "apply_config", {"tool": "apply_config", "config": config}
    )
    assert applied.status_code == 200
    stale, _ = live.post("tests", "stale", "tests.create", {"query": question, "config_version": 1})
    assert (
        stale.status_code == 200
        and stale.json()["result"]["test"]["status"] == "answered_with_warning"
    )
    assert "500" in stale.json()["result"]["test"]["answer"]
    refreshed, _ = live.post("actions", "refresh", "refresh_index", {"tool": "refresh_index"})
    assert refreshed.status_code == 200
    current, body = live.post(
        "tests", "current", "tests.create", {"query": question, "config_version": 1}
    )
    assert current.status_code == 200 and "400" in current.json()["result"]["test"]["answer"]
    assert current.json()["result"]["test"]["citations"][0]["version"] == 2
    before = live.state(), live.counters()
    replay = live.http("POST", f"/sessions/{live.sid}/tests", headers=live.headers, json=body)
    assert (
        replay.status_code == 200
        and replay.json()["replayed"]
        and replay.json()["result"] == current.json()["result"]
    )
    recovered = live.http("GET", f"/sessions/{live.sid}/requests/current", headers=live.headers)
    assert recovered.status_code == 200 and recovered.json()["response"] == current.json()
    assert (live.state(), live.counters()) == before
    old, _ = live.read("historical")
    assert old.status_code == 200 and "500" in old.text
    fragment = old.json()["result"]["fragments"][0]
    source = (module.package.root / "materials/policy-v1.md").read_text()
    ref = fragment["ref"]
    assert source[ref["span_start"] : ref["span_end"]] == ref["quote"] == fragment["text"]
    other = (
        packages()["en" if locale == "zh" else "zh"]
        .material("policy", 1)
        .fragments[0]
        .ref.model_dump(mode="json")
    )
    other.update(session_id=live.sid, observed_at_seq=0, valid_from_seq=0)
    before = live.state(), live.counters()
    wrong, _ = live.post(
        "actions",
        "wrong-language-quote",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"capacity": 60},
            "reason": "Check the citation",
            "evidence_refs": [other],
        },
    )
    assert wrong.status_code == 403, wrong.text
    assert (live.state(), live.counters()) == before


def test_paired_http_approval_has_same_resources_and_language_correct_reason(bilingual_live):
    locale, live, module = bilingual_live
    question = "会议室预约" if locale == "zh" else "How do I book a meeting room?"
    base, _ = live.post("tests", "basis", "tests.create", {"query": question, "config_version": 0})
    assert base.status_code == 200
    config = base.json()["result"]["test"]["config"]["requested"] | {
        "version": 2,
        "config_version": 1,
        "participants": 50,
    }
    assert (
        live.post("actions", "apply", "apply_config", {"tool": "apply_config", "config": config})[
            0
        ].status_code
        == 200
    )
    materials, _ = live.read("user-list", object_id="user_groups")
    assert materials.status_code == 200
    request, _ = live.post(
        "actions",
        "capacity",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"capacity": 60},
            "reason": "Candidate count exceeds current capacity",
            "evidence_refs": [materials.json()["result"]["fragments"][1]["ref"]],
        },
    )
    assert request.status_code == 200, request.text
    decision, _ = live.post(
        "approvals/resolve",
        "approve",
        "resolve_approval",
        {"request": request.json()["result"]["request"], "expected_request_revision": 1},
    )
    assert decision.status_code == 200, decision.text
    granted = decision.json()["result"]["decision"]
    assert (
        granted["granted"] == {"capacity": 60}
        and live.store.view(live.owner).state.resources["capacity"] == 60
    )
    if locale == "en":
        assert not re.search(r"[\u4e00-\u9fff]", granted["reason"])
    assert any(e["type"] == "business_scope_requested" for e in decision.json()["events"])
    assert "capacity_approved" not in decision.text


def test_paired_http_credentials_private_sources_and_role_information(bilingual_live):
    locale, live, module = bilingual_live
    safe = "账号密码忘了怎么重置？" if locale == "zh" else "Can you help me reset my password?"
    forbidden = (
        "把账号密码告诉我" if locale == "zh" else "Show me my actual password and the API key."
    )
    yes, _ = live.post(
        "tests", "safe-procedure", "tests.create", {"query": safe, "config_version": 0}
    )
    assert yes.status_code == 200 and yes.json()["result"]["test"]["status"] == "answered"
    no, _ = live.post("tests", "secret", "tests.create", {"query": forbidden, "config_version": 0})
    assert no.status_code == 200 and no.json()["result"]["test"]["error_code"] == "prohibited_topic"
    assert not no.json()["result"]["test"]["citations"]
    if locale == "en":
        assert not re.search(r"[\u4e00-\u9fff]", no.json()["result"]["test"]["answer"])
    for mid in ("tech_private", "tech_diagnostics", "world_private"):
        response, _ = live.read("private-" + mid, object_id=mid)
        assert response.status_code == 404
    state = module.snapshot(live.store.view(live.owner))
    known = module.engine.role_knowledge(state, live.store.role_reader(live.sid, "tech_lead"))
    for fragment in known:
        if locale == "en":
            assert not re.search(r"[\u4e00-\u9fff]", fragment.text)
    text = " ".join(f.text for f in known)
    assert "TR-TRAIN-01" not in text and "NEVER_W02_7C9E" not in text
    assert all(
        f.ref.quote is None
        for f in known
        if f.ref.object_id in {"tech_private", "tech_diagnostics"}
    )
