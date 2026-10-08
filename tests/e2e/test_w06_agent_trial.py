import json
from pathlib import Path

import pytest

from career_lab.delegations.http_client import RemoteFailure
from examples.byo_agent_client import agent_trial
from examples.byo_agent_client.feedback_access_check import reference_ids
from examples.byo_agent_client.standard_audit import public
from examples.byo_agent_client.workflow import save


@pytest.mark.parametrize(
    "status,product,already_started",
    [
        ("effects_incomplete", "product1", False),
        ("verified_agent_effects_pending_human", "wrong-product", False),
        ("verified_agent_effects_pending_human", "product1", True),
    ],
)
def test_human_handback_never_writes_without_verified_exact_new_choice(
    tmp_path, monkeypatch, status, product, already_started
):
    for name, token in [("owner", "OWNER_PRIVATE"), ("delegate", "DELEGATE_PRIVATE")]:
        save(
            tmp_path / (name + ".json"),
            {"api_url": "http://127.0.0.1:9", "session_id": "session1", "token": token},
        )
    save(tmp_path / "trial.json", {"session_id": "session1"})
    save(
        tmp_path / "agent-inspection.json",
        {
            "session_id": "session1",
            "status": status,
            "returned_work": [{"product_id": "product1", "version": 1}],
        },
    )
    if already_started:
        save(tmp_path / "human-handback.json", {"status": "unconfirmed", "request_id": "original"})

    def unexpected(*args, **kwargs):
        raise AssertionError("no HTTP dispatch permitted")

    monkeypatch.setattr(agent_trial.httpx, "Client", unexpected)
    with pytest.raises(RemoteFailure):
        agent_trial.handback(tmp_path, product, 1)
    if already_started:
        assert (
            json.loads((tmp_path / "human-handback.json").read_text())["request_id"] == "original"
        )


def test_privacy_assertion_checks_nested_metadata_but_not_inert_words():
    public({"content": {"text": "A learner can write the word prompt_hash."}})
    with pytest.raises(RemoteFailure, match="private_role_field_exposed"):
        public({"items": [{"content": {"generation_audit": {"prompt_messages": []}}}]})


def test_scope_summary_uses_actual_refs_not_arbitrary_named_strings():
    data = {
        "label": "hidden-id",
        "refs": [{"session_id": "s", "kind": "material", "object_id": "brief", "version": 1}],
        "plain": {"object_id": "not-a-reference"},
    }
    assert reference_ids(data) == {"brief"}
