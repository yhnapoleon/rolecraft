"""Concurrent initial capture never bypasses archive identity verification."""

import errno
from pathlib import Path
import shutil
import pytest
from career_lab.api.scenario_history import ScenarioReadCatalog, HistoricalScenarioReader
from career_lab.scenarios.v2.seed import build_seed
from career_lab.scenarios.v2.module import ScenarioModule


@pytest.mark.parametrize("collision", [errno.EEXIST, errno.ENOTEMPTY], ids=["EEXIST", "ENOTEMPTY"])
def test_another_process_can_win_initial_archive_capture(tmp_path, monkeypatch, collision):
    module = ScenarioModule(build_seed(tmp_path / "scenario"))
    archive = tmp_path / "archive"
    original = Path.rename

    def simultaneous(path, target):
        if path.name == "content":
            shutil.copytree(path, target)
            raise OSError(collision, "concurrent directory already published")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", simultaneous)
    catalog = ScenarioReadCatalog(module, archive)
    stored = HistoricalScenarioReader(archive / module.package.content_hash)
    assert stored.bindings == module.bindings
    assert catalog.preserve(module.package.root) == archive / module.package.content_hash


def test_non_collision_io_failure_is_not_hidden(tmp_path, monkeypatch):
    module = ScenarioModule(build_seed(tmp_path / "scenario"))

    def no_space(path, target):
        raise OSError(errno.ENOSPC, "controlled no space")

    monkeypatch.setattr(Path, "rename", no_space)
    with pytest.raises(OSError) as error:
        ScenarioReadCatalog(module, tmp_path / "archive")
    assert error.value.errno == errno.ENOSPC
