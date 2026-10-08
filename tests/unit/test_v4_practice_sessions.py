"""One practice choice yields exactly one new practice, recoverable by retrying the same request."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from career_lab.api.modules import ScenarioRegistration
from career_lab.api.v4_extensions import _practice_session
from career_lab.contracts import v2 as C
from career_lab.runtime.context_v2 import ScenarioKnowledge
from career_lab.scenarios.v2.loader import load_package
from career_lab.storage.v2_store import V2Store

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def world(tmp_path):
    package = load_package(ROOT / "scenarios/pm_pilot/v2")
    knowledge = ScenarioKnowledge.from_package(package)
    fixture = C.FileRef(path="practice-fixture.json", sha256=C.digest("practice-fixture"))
    bindings = C.SessionBindings(scenario=knowledge.binding, runtime=fixture, evaluation=fixture)
    registration = ScenarioRegistration(
        bindings, package.baseline("template"), package.bundle.initial_resources, work_language="zh"
    )
    store = V2Store("sqlite:///" + str(tmp_path / "practice.db"))
    source, token = store.create_session(
        bindings, package.baseline("template"), package.bundle.initial_resources
    )
    gateway = SimpleNamespace(
        registry=SimpleNamespace(language_scenarios={("variant_v2", "zh"): registration})
    )
    return store, gateway, store.authenticate(source.session_id, token), source.session_id


def test_retrying_the_same_choice_returns_the_same_practice_and_access(world):
    store, gateway, owner, source = world
    first = _practice_session(
        store, gateway, owner, "variant_v2", "zh", source, "feedback-1", "request-1"
    )
    # The link write failed or the response was lost: the retry must not create another practice.
    again = _practice_session(
        store, gateway, owner, "variant_v2", "zh", source, "feedback-1", "request-1"
    )
    assert again["session_id"] == first["session_id"] and again["token"] == first["token"]
    assert store.authenticate(first["session_id"], first["token"]).executor.kind == "human"
    other = _practice_session(
        store, gateway, owner, "variant_v2", "zh", source, "feedback-1", "request-2"
    )
    assert other["session_id"] != first["session_id"]


def test_another_person_cannot_derive_the_practice_access(world, tmp_path):
    store, gateway, owner, source = world
    mine = _practice_session(
        store, gateway, owner, "variant_v2", "zh", source, "feedback-1", "request-1"
    )
    stranger_state, stranger_token = store.create_session(*_bindings(gateway))
    stranger = store.authenticate(stranger_state.session_id, stranger_token)
    with pytest.raises(C.ProtocolError):
        # Same ids, different credential: the derived access differs, so it cannot open the practice.
        _practice_session(
            store, gateway, stranger, "variant_v2", "zh", source, "feedback-1", "request-1"
        )
    assert store.authenticate(mine["session_id"], mine["token"])


def test_language_mismatch_is_refused(world):
    store, gateway, owner, source = world
    with pytest.raises(C.ProtocolError):
        _practice_session(
            store, gateway, owner, "variant_v2", "en", source, "feedback-1", "request-1"
        )


def _bindings(gateway):
    registration = gateway.registry.language_scenarios[("variant_v2", "zh")]
    return registration.bindings, registration.baseline_config, registration.resources
