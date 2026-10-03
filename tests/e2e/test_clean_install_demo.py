from pathlib import Path
import zipfile

from career_lab.demo import run_demo
from career_lab.packaging import package_release


def test_complete_local_demo_and_safe_package(tmp_path):
    result = run_demo(f"sqlite:///{tmp_path / 'demo.db'}", Path('scenarios/pm_pilot/v1/scenario.yaml'))
    assert result["state_status"] == "submitted"
    assert result["feedback"]["summary"]["status"] == "pending_review"
    assert result["replay_stable"]
    assert result["source_versions"]["policy"] == 2
    archive = package_release(Path.cwd(), tmp_path / 'release.zip')
    with zipfile.ZipFile(archive) as z:
        assert 'pyproject.toml' in z.namelist()
        assert 'scenarios/pm_pilot/v1/manifest.json' in z.namelist()
        assert all(not n.endswith(('openai.txt','ds.txt','.db')) for n in z.namelist())
        assert not any('/gold/test' in n for n in z.namelist())
