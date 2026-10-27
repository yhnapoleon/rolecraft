"""SLOT-01..05, KEY-01..03: per-slot model configuration through the standard runtime.

Real loopback HTTP services stand in for providers (models ``qa-loopback-roles`` and
``qa-loopback-judge``); they prove wiring and request shape only, never answer quality.
SLOT-01 uses frozen main request bytes with explicit snapshots for intentional prompt
revisions; all requests still use the same driver and byte-level comparison.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.localization import message
from tests.support.model_slots import (
    assistant_generation,
    body_digests,
    colleague_turn,
    feedback_review,
    loopback,
    runtime_session,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/contracts/expansion_v3/fixtures/model_assembly"
SLOT01 = {
    case["language"]: case
    for case in json.loads((FIXTURES / "slot01-main-d163747.json").read_text())["cases"]
}
OVERFLOW = "完整模型输入超出已配置预算；未截断证据，规则结果保留。"


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in list(os.environ):
        if name.startswith("CAREER_LAB_") and name not in {
            "CAREER_LAB_CREDENTIAL_KEY",
            "CAREER_LAB_CREDENTIAL_KEY_ID",
        }:
            monkeypatch.delenv(name)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    return tmp_path


def key_file(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content)
    return path


def slots(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv("CAREER_LAB_" + name, value)


def one_request_per_input(calls) -> bool:
    inputs = [json.dumps(json.loads(call.body)["messages"][:2], sort_keys=True) for call in calls]
    return len(set(inputs)) == len(inputs)


def startup_lines(environment: dict[str, str], database: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.cli",
            "worker",
            "--once",
            "--database-url",
            "sqlite:///" + str(database),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_slot_01_unset_slot_variables_keep_shared_configuration_and_main_request_bytes(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    golden = SLOT01[language]
    key = "sk-" + "5" * 48  # the value recorded on main; a test credential, never deployed
    with loopback(language) as provider:
        slots(
            monkeypatch,
            KEY_FILE=str(key_file(clean_env, "provider.key", key)),
            BASE_URL=provider.url,
            MODEL="qa-loopback-shared",
        )
        with runtime_session(clean_env / "runtime.db", language, "openai") as session:
            role = colleague_turn(session)
            assistant = assistant_generation(session)
            review = feedback_review(session)
            digests = body_digests(provider.calls, session.session_id)
    assert [role["status"], assistant["status"]] == golden["statuses"]
    assert provider.kinds() == golden["kinds"]
    expected = list(golden["body_sha256"])
    # Recorded on b07ec765: cooperative-help-v3 and artifact-review-v2
    # (e9ba052f, 9b50d0f5, f3b67b9d), then the colleague-voice line in the role
    # prompt (dd9cb8f5). Reverting only those policy/review/voice inputs
    # reproduces the frozen role digests; all other request bytes are unchanged.
    role_digest, review_digest = {
        "zh": (
            "b3fc8d9164594125f480dead810e5334701b47e082853fecc4e211ed065f64bc",
            "be67a615da2a782035b3be8c1a18574d9585d4249924ff7dc7c30b4ca7a9c153",
        ),
        "en": (
            "398d928978e4120afcf19f05628447720b1a3f51e21a7be8e2e98542257eab5d",
            "1243e7692a8ec2718ee152a012d4c1fa18f15c91d30ceac14716ba5ba59b6c6e",
        ),
    }[language]
    expected[golden["kinds"].index("role")] = role_digest
    expected[golden["kinds"].index("role_review")] = review_digest
    # The judge and support prompts gained the shared claim-status guidance
    # (dd9cb8f5, generalized in 263559ad). Removing only that guidance reproduces
    # the frozen judge and support digests; their other request bytes are unchanged.
    judged = {
        "zh": (
            "da10de3492eb68b6b86096035c85db552cd4358dadb97c3275f7fdc677308cd2",
            "7c0dd39de4894ef12c595dbe352e7ec363fe4ee19fb630527aefc9bd3e379000",
            "9af8885b1eba137085b248450e8ae6e767297bd5d55bafc9b63e16e4c45e9496",
            "5f1ce669e81fe057504f057ab0f1fcec5f31232908c7e2b2d18c6943c295f35e",
            "1fe3e302ae103a32e7f7063d7d4a085c0aec013329259c1867bf99a29d495e99",
            "0214712b736e94b57f2deed2dc300aaa8084fa1b66c7058b8fce4cb3c7b7936a",
            "2d78bba931dd3b4d80ee3a54a124f02c68336464ce173a643bdcbba4bbb659f2",
            "335fe42e1379cf6d5edc2aaf504595cfe0ac63a7e6bf5ebbbe3e5578603ab794",
            "00898a1f12842b67bb80bf735065e1f87174c0d8cdd8d0709a29bf65eb14d4a4",
            "bd0a1edd152436de0cd10d6e1c608ef360fc35004560bafce2de8cbb36637ae5",
            "37df1125104abc3d0a0325f2d19fc12a234846d59bd1a4a2186335e10f536bab",
            "9665a83bc05cab7a41906760599220697efe05ba3233dbcb8d6825c130b53e4b",
            "bc5e997fd26e29f4ea2475750f515008f921ae461cec6b371b5dc75a557651d0",
            "6c94f113b769211885820526d0b89b59f58d1bf57d77b42693d42fa2ab0dee5d",
            "cf70af61f0a8ecc52232902ce84f28e3f3c141f93078e94baaf0d3725841db37",
            "d9e94eb094fea958d29f34404dc981e42cc052b67d3611046463cad81da82e26",
            "ae4809f4b58ae5b13c585e3e1aa9f63273b64197b07e5574524e0528b2731879",
            "b591cc1b05027ac129deaceb17c042e009bc38a5614d57455f12061c7155798b",
        ),
        "en": (
            "125e9adbe5c1a2a77f2f6b0cfde7d42a7f367326014feeaff7f1c1dc394265d4",
            "ef8701e9a36cf6041150ff1704a65ff68cd5b0b24c0fcb6b2dea652e15dd0e7d",
            "ac1efebd090b9eb518ad90d670c4aa886f52b41c8d5a45e56794999d9779494f",
            "5204ce6aca804416601c54a860fbbbd8d41a1c24381041685eb8836e3abafb4a",
            "8949c00237e99ccb2c4f2982bcf9c313c1d2036d19d18bd659ede6c8bc61b045",
            "72d83fa50a5282cb5807fea12835a72aa10576e9ea477601c8a0aa319b8147ac",
            "faaa78bea18d0f9bdfe878e590b778047811a2000cf61baffb292a964c0bebf6",
            "d5a3040ceaba3bcaa9fcaef5fdf11861ca259355611d34250f9590385642a647",
            "6102c5d22d04e2c4371265e2119e298b0d07385fcefd41cf0998480886d881ad",
            "1568c1d908d4f91ab7e0e8bef71c5a5568ce66488dafdfc6e04c64c93254bc84",
            "cf02d9841a1c1ca14c80d58a273da614e644b3721dbf2a5f81f99ba68028810b",
            "82f50a9f02f645d644323e2f1dd7934947f9cca53eb4ffdcb0cf7d8d741f3dfd",
            "d13931394370a48aa727e11799f4a97d568d2f5ad2d4229f732896117e196c2f",
            "2e2304c1998529220bd4393546b73d3679cb30c78076f5d0bad6ba92a6d7276a",
            "b334bce008667b28d71ce5c8bc5e1c6d57266ad16208f0dbd2860d12a006b178",
            "0fe1c80ad8432a5da179b08e6faaf113052f56b6000e72d7eda9a4b3c5e3f59a",
            "e480c6d3c79173d12ed478d3ec07d86ce42525edceb14a2b909e682ccacc3daa",
            "4185febfc138b048cfe21e7cdd37cac94aad8a7b821c57b88d605ee3ba80488d",
        ),
    }[language]
    positions = [i for i, kind in enumerate(golden["kinds"]) if kind in ("judge", "support")]
    for position, digest in zip(positions, judged, strict=True):
        expected[position] = digest
    # Generation v2 explicitly reports missing information; keep the frozen v1 fixture intact.
    expected[golden["kinds"].index("assistant")] = {
        "zh": "712a0b2c868aac47ee39ce000295e76fd4637b6696532e19f1bf77a7f1a15dba",
        "en": "545c5e6de9f836165cca8caceaf4c49df2bfc3efeb2808c2a5857fa6c4f2aa27",
    }[language]
    assert digests == expected
    assert {call.max_tokens for call in provider.calls} == {512}
    assert {call.model for call in provider.calls} == {"qa-loopback-shared"}
    assert all(call.authorization == "Bearer " + key for call in provider.calls)
    provenance = review["provenance"]
    assert (provenance["provider"], provenance["model"]) == ("openai", "qa-loopback-shared")
    assert "support_model" not in provenance and provenance["retries"] == 0
    assert "base_url" not in provenance  # shared configuration records what main records


@pytest.mark.parametrize("language", ["zh", "en"])
def test_slot_02_each_slot_reaches_its_own_provider_in_one_session(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    key = "qa-roles-" + secrets.token_hex(12)
    with loopback(language) as roles, loopback(language) as judge:
        slots(
            monkeypatch,
            ROLES_PROVIDER="openai_compatible",
            ROLES_BASE_URL=roles.url,
            ROLES_MODEL="qa-loopback-roles",
            ROLES_KEY_FILE=str(key_file(clean_env, "roles.key", key + "\n")),
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
            SUPPORT_PROVIDER="openai_compatible",
            SUPPORT_BASE_URL=judge.url,
            SUPPORT_MODEL="qa-loopback-support",
            ASSISTANT_PROVIDER="openai_compatible",
            ASSISTANT_BASE_URL=roles.url,
            ASSISTANT_MODEL="qa-loopback-assistant",
            ASSISTANT_KEY_FILE=str(clean_env / "roles.key"),
        )
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            role = colleague_turn(session)
            assistant = assistant_generation(session)
            review = feedback_review(session)
            semantic = session.get("/workbench").json()["result"]["result"]["semantic"]
            reread = (session.get("/requests/colleague").json(), session.get("/requests/review"))
            assert not session.run()
    assert role["status"] == assistant["status"] == "completed"
    assert [(c.kind, c.model) for c in roles.calls] == [
        ("role", "qa-loopback-roles"),
        ("role_review", "qa-loopback-roles"),
        ("assistant", "qa-loopback-assistant"),
    ]
    assert {c.kind for c in judge.calls} == {"judge", "support"}
    assert {c.model for c in judge.calls if c.kind == "judge"} == {"qa-loopback-judge"}
    assert {c.model for c in judge.calls if c.kind == "support"} == {"qa-loopback-support"}
    assert one_request_per_input(roles.calls) and one_request_per_input(judge.calls)
    assert {c.authorization for c in roles.calls} == {"Bearer " + key}
    assert {c.authorization for c in judge.calls} == {None}
    provenance = review["provenance"]
    assert (provenance["provider"], provenance["model"]) == (
        "openai_compatible",
        "qa-loopback-judge",
    )
    assert provenance["base_url"] == judge.url
    assert provenance["support_model"] == {
        "provider": "openai_compatible",
        "model": "qa-loopback-support",
        "base_url": judge.url,
    }
    generation = assistant["jobs"][0]["effect"]["result"]["generation"]
    assert (generation["mode"], generation["provider"]) == ("llm", "openai_compatible")
    assert semantic == {"roles": "model", "feedback": "model", "assistant": "model"}
    assert reread[0] == role and reread[1].status_code == 200
    # Startup prints each slot's provider, model and non-secret fingerprint to stderr.
    environment = {
        **{k: v for k, v in os.environ.items()},
        "CAREER_LAB_SCENARIO_ARCHIVE": str(clean_env / "cli-archive"),
    }
    first = startup_lines(environment, clean_env / "cli.db")
    again = startup_lines(environment, clean_env / "cli-again.db")
    assert first.returncode == 0, first.stderr
    lines = [line for line in first.stderr.splitlines() if line.startswith("career-lab model slot")]
    assert [line.split(" provider=")[0] for line in lines] == [
        "career-lab model slot ROLES:",
        "career-lab model slot JUDGE:",
        "career-lab model slot SUPPORT:",
        "career-lab model slot ASSISTANT:",
    ]
    assert "provider=openai_compatible model=qa-loopback-roles fingerprint=" in lines[0]
    assert "provider=openai_compatible model=qa-loopback-judge fingerprint=" in lines[1]
    assert "model=qa-loopback-support" in lines[2] and "model=qa-loopback-assistant" in lines[3]
    assert lines == [
        line for line in again.stderr.splitlines() if line.startswith("career-lab model slot")
    ]
    changed = startup_lines(
        environment | {"CAREER_LAB_JUDGE_MAX_TOKENS": "256"}, clean_env / "cli-changed.db"
    )
    other = [line for line in changed.stderr.splitlines() if line.startswith("career-lab model")]
    # SUPPORT has its own provider here, so it takes nothing from JUDGE.
    assert other[0] == lines[0] and other[2] == lines[2] and other[3] == lines[3]
    assert other[1] != lines[1]
    for output in (first, again, changed):
        assert key not in output.stderr + output.stdout
        assert roles.url not in output.stderr


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"JUDGE_PROVIDER": "anthropic"}, "model_slot_provider_invalid"),
        ({"JUDGE_PROVIDER": "openai_compatible"}, "model_slot_configuration_incomplete"),
        (
            {"ROLES_PROVIDER": "openai_compatible", "ROLES_BASE_URL": "http://127.0.0.1:9"},
            "model_slot_configuration_incomplete",
        ),
        ({"JUDGE_MAX_TOKENS": "0"}, "model_slot_value_invalid"),
        ({"SUPPORT_TIMEOUT": "never"}, "model_slot_value_invalid"),
        ({"JUDGE_INPUT_BYTES": "100"}, "model_slot_value_invalid"),
    ],
)
def test_slot_02_unknown_or_incomplete_slot_configuration_refuses_to_start(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, values: dict[str, str], code: str
) -> None:
    slots(monkeypatch, **values)
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(clean_env / "refused.db"), provider="local")
    assert refused.value.code == code


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("support", ["inherits", "local"])
def test_slot_03_support_falls_back_to_the_judge_slot(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str, support: str
) -> None:
    with loopback(language) as judge:
        slots(
            monkeypatch,
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
            JUDGE_MAX_TOKENS="300",
        )
        if support == "local":
            slots(monkeypatch, SUPPORT_PROVIDER="local")
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            review = feedback_review(session)
    kinds = judge.kinds()
    assert "judge" in kinds
    provenance = review["provenance"]
    assert provenance["model"] == "qa-loopback-judge"
    if support == "inherits":
        assert "support" in kinds
        assert {(c.model, c.max_tokens) for c in judge.calls} == {("qa-loopback-judge", 300)}
        assert "support_model" not in provenance
    else:
        assert "support" not in kinds
        assert provenance["support_model"] == {
            "provider": "not_configured",
            "model": "not_configured",
        }


@pytest.mark.parametrize("language", ["zh", "en"])
def test_slot_04_max_tokens_and_input_bytes_take_effect_per_slot(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with loopback(language) as roles, loopback(language) as judge:
        slots(
            monkeypatch,
            ROLES_PROVIDER="openai_compatible",
            ROLES_BASE_URL=roles.url,
            ROLES_MODEL="qa-loopback-roles",
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
            JUDGE_MAX_TOKENS="256",
            SUPPORT_MAX_TOKENS="300",
        )
        with runtime_session(clean_env / "tokens.db", language, "local") as session:
            colleague_turn(session)
            feedback_review(session)
        assert {c.max_tokens for c in roles.calls} == {512}
        assert {(c.kind, c.max_tokens) for c in judge.calls} == {("judge", 256), ("support", 300)}
        # Every support input exceeds 600 bytes: it is reported unsent, never truncated.
        judge.calls.clear()
        slots(monkeypatch, SUPPORT_INPUT_BYTES="600")
        with runtime_session(clean_env / "support.db", language, "local") as session:
            feedback_review(session)
        assert judge.kinds() and set(judge.kinds()) == {"judge"}
        judge.calls.clear()
        slots(monkeypatch, JUDGE_INPUT_BYTES="600")
        with runtime_session(clean_env / "judge.db", language, "local") as session:
            review = feedback_review(session)
        assert judge.calls == []
        overflow = message(language, OVERFLOW)
        assert any(item["explanation"] == overflow for item in review["items"])
        assert review["mode"] == "advisory"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_slot_05_real_calls_never_retry_and_send_one_request_per_input(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with loopback(language) as roles, loopback(language) as judge:
        roles.failure = judge.failure = "http"
        slots(
            monkeypatch,
            ROLES_PROVIDER="openai_compatible",
            ROLES_BASE_URL=roles.url,
            ROLES_MODEL="qa-loopback-roles",
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
        )
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            configured = session.app.state.model_slots
            role = colleague_turn(session)
            review = feedback_review(session)
            assert not session.run()
    assert all(
        getattr(model, "retries", 0) == 0
        for model in (configured.roles, configured.judge, configured.support)
    )
    assert role["status"] == "failed" and len(roles.calls) == 1
    assert judge.kinds() and set(judge.kinds()) == {"judge"}
    assert one_request_per_input(judge.calls)
    assert all(item["source"] != "model_advice" for item in review["items"])
    assert review["provenance"]["retries"] == 0


def test_key_01_keys_without_an_sk_prefix_are_read(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "qa-key-" + secrets.token_hex(16)
    content = "# provider credential for the loopback check\n\n  " + key + "  \n# trailing\n"
    with loopback("en") as roles:
        slots(
            monkeypatch,
            ROLES_PROVIDER="openai_compatible",
            ROLES_BASE_URL=roles.url,
            ROLES_MODEL="qa-loopback-roles",
            ROLES_KEY_FILE=str(key_file(clean_env, "roles.key", content)),
        )
        with runtime_session(clean_env / "runtime.db", "en", "local") as session:
            assert colleague_turn(session)["status"] == "completed"
        legacy = "sk-" + secrets.token_hex(20)
        slots(monkeypatch, ROLES_KEY_FILE=str(key_file(clean_env, "old.key", "KEY=" + legacy)))
        roles.calls.clear()
        with runtime_session(clean_env / "legacy.db", "en", "local") as session:
            colleague_turn(session)
    assert {call.authorization for call in roles.calls} == {"Bearer " + legacy}
    for content in ("short", "two words here", "# only a comment\n\n"):
        slots(monkeypatch, ROLES_KEY_FILE=str(key_file(clean_env, "bad.key", content)))
        with pytest.raises(C.ProtocolError) as refused:
            create_runtime_app("sqlite:///" + str(clean_env / "bad.db"), provider="local")
        assert refused.value.code == "model_slot_key_invalid"
        assert content.strip() not in str(refused.value) or not content.strip()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_key_02_keyless_slots_are_allowed_only_on_loopback(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    slots(
        monkeypatch,
        JUDGE_PROVIDER="openai_compatible",
        JUDGE_BASE_URL=f"http://{host}:9/v1",
        JUDGE_MODEL="qa-loopback-judge",
    )
    app = create_runtime_app("sqlite:///" + str(clean_env / "loopback.db"), provider="local")
    try:
        assert app.state.model_slots.judge.revision == "qa-loopback-judge"
    finally:
        app.state.store.close()
    for url in ("http://10.0.0.1:9/v1", "https://api.example.com/v1", "http://127.0.0.1.example:9"):
        slots(monkeypatch, JUDGE_BASE_URL=url)
        with pytest.raises(C.ProtocolError) as refused:
            create_runtime_app("sqlite:///" + str(clean_env / "remote.db"), provider="local")
        assert refused.value.code == "model_slot_key_required"
    for name in ("PROVIDER", "BASE_URL", "MODEL"):
        monkeypatch.delenv("CAREER_LAB_JUDGE_" + name)
    monkeypatch.chdir(clean_env)  # no ds.txt here: the hosted default key file is missing
    with pytest.raises(C.ProtocolError) as missing:
        create_runtime_app("sqlite:///" + str(clean_env / "deepseek.db"), provider="deepseek")
    assert missing.value.code == "model_slot_key_unreadable"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_key_03_keys_never_reach_logs_database_provenance_or_errors(
    clean_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
    language: str,
) -> None:
    roles_key = "qa-roles-" + secrets.token_hex(16)
    judge_key = "sk-" + secrets.token_hex(24)
    with loopback(language) as roles, loopback(language) as judge:
        slots(
            monkeypatch,
            ROLES_PROVIDER="openai_compatible",
            ROLES_BASE_URL=roles.url,
            ROLES_MODEL="qa-loopback-roles",
            ROLES_KEY_FILE=str(key_file(clean_env, "roles.key", roles_key)),
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
            JUDGE_KEY_FILE=str(key_file(clean_env, "judge.key", judge_key)),
        )
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            responses = [colleague_turn(session), feedback_review(session)]
            roles.failure = "http"
            session.send(
                "/turns",
                "failed-colleague",
                "turns.create",
                {"role_id": "tech_lead", "text": "Status?" if language == "en" else "进展？"},
            )
            session.run()
            responses.append(session.get("/requests/failed-colleague").json())
            responses.append(session.get("/timeline").json())
    assert {c.authorization for c in roles.calls} == {"Bearer " + roles_key}
    assert {c.authorization for c in judge.calls} == {"Bearer " + judge_key}
    assert responses[2]["status"] == "failed"
    captured = capfd.readouterr()
    haystacks = [json.dumps(responses, ensure_ascii=False), caplog.text, captured.out, captured.err]
    haystacks += [
        path.read_bytes().decode("utf-8", "replace")
        for path in clean_env.iterdir()
        if path.name.startswith("runtime.db")
    ]
    for key in (roles_key, judge_key):
        assert all(key not in text for text in haystacks)
        assert key[-12:] not in json.dumps(responses[1]["provenance"])
    slots(monkeypatch, ROLES_KEY_FILE=str(key_file(clean_env, "bad.key", "x " + roles_key)))
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(clean_env / "bad.db"), provider="local")
    assert roles_key not in str(refused.value) and roles_key not in repr(refused.value)


@pytest.fixture
def loopback_only(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refuse any provider request that would leave this machine; record attempted hosts."""
    real = httpx.post
    attempted: list[str] = []

    def guarded(url, *args, **kwargs):
        host = httpx.URL(url).host
        attempted.append(host)
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise AssertionError("a test provider request left the machine: " + host)
        return real(url, *args, **kwargs)

    monkeypatch.setattr(httpx, "post", guarded)
    return attempted


@pytest.mark.parametrize("language", ["zh", "en"])
def test_key_04_a_shared_key_never_reaches_a_slot_with_its_own_provider(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: list[str], language: str
) -> None:
    shared = "sk-shared" + secrets.token_hex(16)
    with loopback(language) as qwen:
        slots(
            monkeypatch,
            KEY_FILE=str(key_file(clean_env, "ds.txt", shared)),
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=qwen.url + "/v1",
            JUDGE_MODEL="qa-loopback-qwen",
        )
        with runtime_session(clean_env / "runtime.db", language, "deepseek") as session:
            configured = session.app.state.model_slots
            review = feedback_review(session)
    assert qwen.calls and {call.authorization for call in qwen.calls} == {None}
    assert {call.model for call in qwen.calls} == {"qa-loopback-qwen"}
    assert set(loopback_only) == {"127.0.0.1"}
    assert configured.roles.base_url == "https://api.deepseek.com"
    assert configured.judge.base_url == qwen.url + "/v1"
    provenance = review["provenance"]
    assert (provenance["provider"], provenance["model"], provenance["base_url"]) == (
        "openai_compatible",
        "qa-loopback-qwen",
        qwen.url + "/v1",
    )
    assert "support_model" not in provenance
    assert shared not in json.dumps(review)


@pytest.mark.parametrize(
    "url", ["https://vllm.example.org/v1", "http://10.0.0.8:8000/v1", "http://qwen.internal/v1"]
)
def test_key_04_an_external_openai_compatible_slot_needs_its_own_key(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    slots(
        monkeypatch,
        KEY_FILE=str(key_file(clean_env, "ds.txt", "sk-shared" + secrets.token_hex(16))),
        JUDGE_PROVIDER="openai_compatible",
        JUDGE_BASE_URL=url,
        JUDGE_MODEL="qa-remote-qwen",
    )
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(clean_env / "refused.db"), provider="deepseek")
    assert refused.value.code == "model_slot_key_required"
    slots(monkeypatch, JUDGE_KEY_FILE=str(key_file(clean_env, "qwen.key", "qa-qwen-key-0001")))
    app = create_runtime_app("sqlite:///" + str(clean_env / "keyed.db"), provider="deepseek")
    try:
        assert app.state.model_slots.judge.base_url == url
    finally:
        app.state.store.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_key_04_a_support_provider_takes_nothing_from_the_judge_slot(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: list[str], language: str
) -> None:
    support_key = "sk-support" + secrets.token_hex(16)
    with loopback(language) as qwen:
        qwen.insufficient = True  # the Judge cites nothing, so the hosted verifier is never called
        slots(
            monkeypatch,
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=qwen.url,
            JUDGE_MODEL="qa-loopback-qwen",
            SUPPORT_PROVIDER="deepseek",
            SUPPORT_KEY_FILE=str(key_file(clean_env, "support.key", support_key)),
        )
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            configured = session.app.state.model_slots
            review = feedback_review(session)
    assert (configured.support.provider, configured.support.base_url) == (
        "deepseek",
        "https://api.deepseek.com",
    )
    assert configured.support.revision == "deepseek-chat"
    assert set(qwen.kinds()) == {"judge"} and set(loopback_only) == {"127.0.0.1"}
    assert {call.authorization for call in qwen.calls} == {None}
    assert review["provenance"]["support_model"] == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    }
    assert review["provenance"]["base_url"] == qwen.url
    slots(
        monkeypatch, BASE_URL="http://127.0.0.1:9/v1", MODEL="qa-shared", ROLES_PROVIDER="deepseek"
    )
    slots(monkeypatch, ROLES_KEY_FILE=str(clean_env / "support.key"))
    app = create_runtime_app(
        "sqlite:///" + str(clean_env / "roles.db"), provider="openai_compatible"
    )
    try:
        roles = app.state.model_slots.roles
        assert (roles.base_url, roles.revision) == ("https://api.deepseek.com", "deepseek-chat")
        assistant = app.state.model_slots.assistant
        assert (assistant.base_url, assistant.revision) == ("http://127.0.0.1:9/v1", "qa-shared")
    finally:
        app.state.store.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_slot_06_support_inherits_the_whole_judge_slot_and_provenance_matches_requests(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    key = "qa-judge-" + secrets.token_hex(12)
    with loopback(language) as judge:
        slots(
            monkeypatch,
            KEY_FILE=str(key_file(clean_env, "shared.key", "sk-shared" + secrets.token_hex(16))),
            JUDGE_PROVIDER="openai_compatible",
            JUDGE_BASE_URL=judge.url,
            JUDGE_MODEL="qa-loopback-judge",
            JUDGE_KEY_FILE=str(key_file(clean_env, "judge.key", key)),
            JUDGE_MAX_TOKENS="300",
        )
        with runtime_session(clean_env / "runtime.db", language, "local") as session:
            configured = session.app.state.model_slots
            review = feedback_review(session)
    assert configured.support is configured.judge
    assert {"judge", "support"} <= set(judge.kinds())
    assert {(c.model, c.max_tokens, c.authorization) for c in judge.calls} == {
        ("qa-loopback-judge", 300, "Bearer " + key)
    }
    provenance = review["provenance"]
    recorded = (provenance["provider"], provenance["model"], provenance["base_url"])
    assert recorded == ("openai_compatible", "qa-loopback-judge", judge.url)
    assert "support_model" not in provenance


@pytest.mark.parametrize(
    "values",
    [
        {"SUPPORT_MODEL": "qa-support"},
        {"SUPPORT_BASE_URL": "http://127.0.0.1:9"},
        {"SUPPORT_KEY_FILE": "support.key"},
        {"JUDGE_MODEL": "qa-judge"},
        {"ROLES_BASE_URL": "http://127.0.0.1:9"},
        {"ASSISTANT_KEY_FILE": "assistant.key"},
    ],
)
def test_slot_06_identity_variables_need_their_own_slot_provider(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, values: dict[str, str]
) -> None:
    slots(monkeypatch, **values)
    with pytest.raises(C.ProtocolError) as refused:
        create_runtime_app("sqlite:///" + str(clean_env / "refused.db"), provider="local")
    assert refused.value.code == "model_slot_provider_required"
