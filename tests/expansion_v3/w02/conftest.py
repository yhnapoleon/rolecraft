"""Local policy fixtures, NOT a credential resolver or real API/worker."""

import pytest

from career_lab.contracts.v2.core import AuthContext, Command, Executor
from career_lab.scenarios.v2 import ScenarioEngine, load_package
from tests.support.scenario_packages import LEGACY_ROOT


@pytest.fixture
def package():
    return load_package(LEGACY_ROOT)


@pytest.fixture
def engine(package):
    return ScenarioEngine(package)


def auth(sid="session", actor="learner", *, capabilities=("read", "act"), objects=None):
    return AuthContext(
        session_id=sid,
        actor_id=actor,
        executor=Executor(id=actor, kind="system" if actor == "supervisor" else "human"),
        capabilities=capabilities,
        credential_id="unit-fixture",
        allowed_objects=objects,
    )


def command(snapshot, tool, key, **payload):
    return Command(
        schema_version=2,
        request_id=key,
        expected_version=snapshot.world.business_seq,
        expected_workspace_revision=snapshot.world.workspace_revision,
        operation=tool,
        payload=payload if tool == "resolve_approval" else {"tool": tool, **payload},
    )


def apply(engine, snapshot, **changes):
    cfg = snapshot.config.model_copy(
        update={
            **changes,
            "version": snapshot.config.version + 1,
            "config_version": snapshot.config.config_version + 1,
        }
    )
    return engine.plan(
        snapshot,
        command(
            snapshot,
            "apply_config",
            f"cfg-{cfg.config_version}",
            config=cfg.model_dump(mode="json"),
        ),
        auth(snapshot.world.session_id),
    )
