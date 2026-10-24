"""The demo launcher's parsing and decisions: what it saves, shows and concludes."""

from scripts.demo import launcher

IMPORT_OUTPUT = """\
! IT ticket pilot (zh): scenario 06efaad4ad51 is not in runs/demo-stack/catalog.json

3DAF-17S8-AABE-SQCC-XXRS  知识助手试点（中文）：完整一局 + 修订  (pm_pilot_v2, zh, submitted)
T2NW-Y1QX-FE28-7S18-RHDH  Knowledge-assistant pilot (English): before submission (preview)  \
(pm_pilot_v2, en, active)
- Old run: already present (use --replace to overwrite); a new code is still issued
"""

WORKER_LOG = """\
career-lab model slot ROLES: provider=local model=none fingerprint=aaa
career-lab model slot JUDGE: provider=local model=none fingerprint=bbb
career-lab recognizer retrieval-e5: rule-fallback (not_configured)
career-lab model slot ROLES: provider=deepseek model=deepseek-chat fingerprint=ccc
career-lab model slot JUDGE: provider=deepseek model=deepseek-chat fingerprint=ddd
career-lab model slot SUPPORT: provider=deepseek model=deepseek-chat fingerprint=ddd
career-lab model slot ASSISTANT: provider=local model=none fingerprint=eee
career-lab recognizer retrieval-e5: loaded revision=unhashed
career-lab recognizer scope-mahalanobis-v1: rule-fallback (hash_mismatch)
{"event": "job_completed"}
"""


def test_env_file_keeps_configuration_and_drops_controlled_or_foreign_names():
    values, ignored = launcher.parse_env_file(
        "# models\n"
        "export CAREER_LAB_RECOGNIZERS='runs/local/recognizers'\n"
        'CAREER_LAB_ROLES_KEY_FILE="/keys/ds.txt"\n'
        "CAREER_LAB_CREDENTIAL_KEY=not-from-here\n"
        "PATH=/tmp\n"
        "not a line\n"
    )
    assert values == {
        "CAREER_LAB_RECOGNIZERS": "runs/local/recognizers",
        "CAREER_LAB_ROLES_KEY_FILE": "/keys/ds.txt",
    }
    assert ignored == ["CAREER_LAB_CREDENTIAL_KEY", "PATH", "not a line"]


def test_saved_configuration_never_holds_secret_values():
    shown = launcher.public_env(
        {
            "CAREER_LAB_ROLES_PROVIDER": "deepseek",
            "CAREER_LAB_ROLES_KEY_FILE": "/keys/ds.txt",
            "CAREER_LAB_API_KEY": "sk-should-not-appear",
            "CAREER_LAB_STUDY_TOKEN": "t0k3n",
            "CAREER_LAB_DATABASE_URL": "postgresql://u:p@h/db",
            "CAREER_LAB_CREDENTIAL_KEY": "controlled",
            "HOME": "/Users/someone",
        }
    )
    assert shown == {
        "CAREER_LAB_API_KEY": "(set)",
        "CAREER_LAB_ROLES_KEY_FILE": "/keys/ds.txt",
        "CAREER_LAB_ROLES_PROVIDER": "deepseek",
        "CAREER_LAB_STUDY_TOKEN": "(set)",
    }


def test_import_output_yields_codes_and_warnings():
    codes, warnings = launcher.parse_import_output(IMPORT_OUTPUT)
    assert [c["code"] for c in codes] == ["3DAF-17S8-AABE-SQCC-XXRS", "T2NW-Y1QX-FE28-7S18-RHDH"]
    assert codes[1] == {
        "code": "T2NW-Y1QX-FE28-7S18-RHDH",
        "label": "Knowledge-assistant pilot (English): before submission (preview)",
        "scenario": "pm_pilot_v2",
        "language": "en",
        "status": "active",
    }
    assert len(warnings) == 2 and warnings[0].startswith("! IT ticket pilot")


def test_worker_log_reports_the_last_start_only():
    parsed = launcher.parse_worker_log(WORKER_LOG)
    assert parsed["slots"]["ROLES"] == {"provider": "deepseek", "model": "deepseek-chat"}
    assert parsed["slots"]["ASSISTANT"]["provider"] == "local"
    assert parsed["recognizers"] == {
        "retrieval-e5": {"loaded": True, "revision": "unhashed"},
        "scope-mahalanobis-v1": {"loaded": False, "reason": "hash_mismatch"},
    }


def test_verdict_blocks_before_it_degrades_to_replay():
    ok = {"section": "services", "level": "ok", "text": ""}
    warn = {"section": "advice", "level": "warn", "text": ""}
    replay = {"section": "models", "level": "replay", "text": ""}
    block = {"section": "web", "level": "block", "text": ""}
    assert launcher.verdict([ok, warn]) == "full"
    assert launcher.verdict([ok, replay, warn]) == "replay"
    assert launcher.verdict([replay, block]) == "blocked"


def test_tree_fingerprint_follows_content_not_timestamps(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("one")
    (tmp_path / "index.html").write_text("<html>")
    before = launcher.tree_fingerprint(tmp_path, ["index.html", "src"])
    (tmp_path / "src" / "a.ts").write_text("one")
    assert launcher.tree_fingerprint(tmp_path, ["index.html", "src"]) == before
    (tmp_path / "src" / "a.ts").write_text("two")
    assert launcher.tree_fingerprint(tmp_path, ["index.html", "src"]) != before


def test_engine_cache_parameter_is_read_from_the_page():
    html = '<script src="/workbench-engine.js?v=20261014" defer></script>'
    assert launcher.engine_param(html) == "20261014"
    assert launcher.engine_param("<html></html>") is None
