from pathlib import Path

import pytest

from career_lab.scenarios.loader import load_scenario


def pytest_configure(config):
    # pytest creates basetemp itself but does not create a missing parent.
    if config.option.basetemp:
        Path(config.option.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def spec():
    return load_scenario(Path(__file__).resolve().parents[1] / "scenarios/pm_pilot/v1/scenario.yaml")

