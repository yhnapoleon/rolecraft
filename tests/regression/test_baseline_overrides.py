"""Per-platform baseline overrides only relax the listed tests, with a reason, on that platform."""

import json
from pathlib import Path

import pytest

from scripts.regression.compare import FIXTURES, platform_baseline, regressions

CODEX = (
    "tests.e2e.test_w06_codex_client::"
    "test_w06_official_codex_reads_writes_recovers_and_observes_revocation"
)


def frozen() -> tuple[dict, dict]:
    baseline = json.loads((FIXTURES / "test-baseline.json").read_text())
    overrides = json.loads((FIXTURES / "test-baseline-overrides.json").read_text())
    return baseline, overrides


def test_every_override_names_a_frozen_test_with_a_reason() -> None:
    baseline, overrides = frozen()
    for platform, kinds in overrides.items():
        if platform == "note":
            continue
        for kind, entries in kinds.items():
            for key, entry in entries.items():
                assert key in baseline[kind], key
                assert entry["status"] in {"skipped", "passed"}
                assert entry["reason"].strip()


def test_linux_accepts_only_the_documented_codex_skips() -> None:
    baseline, overrides = frozen()
    linux = platform_baseline(baseline, overrides, "linux")
    current = dict(baseline["backend"])
    current[CODEX] = "skipped"
    assert regressions(linux["backend"], current) == []
    other = next(key for key in baseline["backend"] if key != CODEX)
    current[other] = "skipped"
    assert regressions(linux["backend"], current) == ["new skip or changed outcome: " + other]


def test_macos_baseline_is_unchanged_by_overrides() -> None:
    baseline, overrides = frozen()
    assert platform_baseline(baseline, overrides, "darwin")["backend"] == baseline["backend"]
    current = dict(baseline["backend"])
    current[CODEX] = "skipped"
    assert regressions(baseline["backend"], current) == ["new skip or changed outcome: " + CODEX]


def test_override_without_baseline_entry_is_rejected() -> None:
    baseline, _ = frozen()
    bad = {"linux": {"backend": {"tests.nowhere::test_x": {"status": "skipped", "reason": "x"}}}}
    with pytest.raises(ValueError):
        platform_baseline(baseline, bad, "linux")


def test_archive_race_ids_are_platform_independent() -> None:
    baseline, _ = frozen()
    keys = [
        k
        for k in baseline["backend"]
        if "test_another_process_can_win_initial_archive_capture" in k
    ]
    assert sorted(keys) == sorted(
        f"tests.unit.test_scenario_archive_race::test_another_process_can_win_initial_archive_capture[{name}]"
        for name in ("EEXIST", "ENOTEMPTY")
    )
    assert Path(FIXTURES / "test-baseline-overrides.json").is_file()
