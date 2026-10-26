import json

import pytest

from career_lab.delegations.http_client import RemoteFailure
from career_lab.mcp.protocol import CAPABILITIES, LEGACY, MODERN, VERSION, Protocol, RpcFailure


class Backend:
    session_id = "session-1"

    def tools(self):
        return []

    def aipm_read(self, kind, **kwargs):
        if kind == "guide":
            return {"work_language": "en", "steps": []}
        if kind == "progress":
            return {
                "work_language": "en",
                "focus_step": "business",
                "steps": [{"id": "business", "order": 1, "label": "Understand the business"}],
            }
        return {
            "work_language": "en",
            "status": "not_ready",
            "feedback_ref": None,
            "read": None,
            "exact_read": None,
        }


def rpc(protocol, method, params=None):
    return protocol.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
        }
    )


def test_resources_prompts_and_tool_share_read_service():
    protocol = Protocol(Backend())
    assert rpc(protocol, "server/discover")["capabilities"] == {
        "tools": {},
        "resources": {},
        "prompts": {},
    }
    entries = rpc(protocol, "resources/list")["resources"]
    assert len(entries) == 2
    resource = rpc(protocol, "resources/read", {"uri": entries[0]["uri"]})
    tool = rpc(
        protocol, "tools/call", {"name": "aipm.context.read", "arguments": {"kind": "guide"}}
    )
    assert json.loads(resource["contents"][0]["text"]) == tool["structuredContent"]
    assert tool["isError"] is False
    assert (
        "work does not mean mastery"
        in rpc(protocol, "prompts/get", {"name": "aipm-next-step"})["messages"][0]["content"][
            "text"
        ]
    )
    assert len(rpc(protocol, "resources/templates/list")["resourceTemplates"]) == 1
    assert len(rpc(protocol, "prompts/list")["prompts"]) == 2


@pytest.mark.parametrize(
    "uri",
    [
        "file:///etc/passwd",
        "https://example.test",
        "rolecraft://sessions/session-1/aipm/../private",
        "rolecraft://sessions/session-1/aipm/guide?extra=1",
    ],
)
def test_rejects_unregistered_uris(uri):
    with pytest.raises(RpcFailure) as caught:
        rpc(Protocol(Backend()), "resources/read", {"uri": uri})
    assert caught.value.code == -32602


def test_cross_session_is_not_found():
    with pytest.raises(RemoteFailure) as caught:
        rpc(Protocol(Backend()), "resources/read", {"uri": "rolecraft://sessions/other/aipm/guide"})
    assert caught.value.status == 404


def test_legacy_prompt_and_unknown_method():
    protocol = Protocol(Backend(), negotiated=LEGACY)
    result = protocol.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {
                "name": "aipm-review-submission",
                "arguments": {"submission_id": "s1", "version": "1"},
            },
        }
    )
    assert "No readable formal feedback" in result["messages"][0]["content"]["text"]
    with pytest.raises(RpcFailure) as caught:
        rpc(protocol, "unknown/method")
    assert caught.value.code == -32601
