import pytest

from career_lab.runtime.loop import AgentRuntime
from career_lab.runtime.model_adapter import ScriptedModel, ModelReply, ToolCall
from career_lab.storage.sessions import SessionStore


def test_results_fed_back_and_limit(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'loop.db'}")
    store.create_session(spec, "s")
    model = ScriptedModel(
        [
            ModelReply(
                tool_calls=(
                    ToolCall(id="1", name="read_material", arguments={"material_id": "technical"}),
                )
            ),
            ModelReply(text="资源3人日"),
        ]
    )
    runtime = AgentRuntime(store, model)
    turn = runtime.run_turn("s", "tech_lead", "资源？", "req")
    assert turn["text"] == "资源3人日"
    assert any(m["role"] == "tool" and "3" in m["content"] for m in model.calls[1])
    assert runtime.run_turn("s", "tech_lead", "资源？", "req") == turn
    assert len(model.calls) == 2
    repeating = ScriptedModel(
        [
            ModelReply(tool_calls=(ToolCall(id=str(i), name="list_materials", arguments={}),))
            for i in range(4)
        ]
    )
    result = AgentRuntime(store, repeating).run_turn("s", "tech_lead", "继续", "limit")
    assert result["status"] == "limit_reached"
    assert len(repeating.calls) == 4


def test_model_cannot_grant_capacity_or_leak_private_material(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'loop.db'}")
    store.create_session(spec, "s")
    model = ScriptedModel(
        [
            ModelReply(
                tool_calls=(
                    ToolCall(
                        id="1", name="approve_request", arguments={"rule_id": "capacity_approved"}
                    ),
                )
            ),
            ModelReply(text="已批准60人"),
        ]
    )
    AgentRuntime(store, model).run_turn("s", "business_lead", "扩容", "r")
    assert store.get_state("s").resources["capacity"] == 30
    assert "legacy_connector_unstable" not in str(model.calls)
    assert "tool_not_allowed" in str(model.calls[1])
