"""HTTP adapter boundary tests with httpx.MockTransport; not product/API QA."""
import httpx
import pytest
from career_lab.contracts.v2 import Command, Executor, Observation, VersionPoint
from career_lab.reference_agent.ports import HttpEnvironment, HttpBindings, ActionOutcome, PortError


def make(handler, bindings=None):
    bindings = bindings or HttpBindings(
        lambda s: "/sessions/" + s + "/observation",
        lambda s, operation: "/sessions/" + s + "/commands",
        lambda s, j: "/sessions/" + s + "/jobs/" + j,
        Observation.model_validate,
        lambda raw: ActionOutcome("pending", job_id=raw["job_id"]),
    )
    return HttpEnvironment("http://127.0.0.1:19999", "synthetic-scoped-test-token",
                           bindings, transport=httpx.MockTransport(handler))


def test_http_command_serializes_frozen_identity_no_client_executor():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"job_id": "j"})
    env = make(handler)
    command = Command(request_id="r", operation="read", expected_version=2,
                      expected_workspace_revision=3, payload={"query": "q"})
    try:
        assert env.execute("s", command, 1).job_id == "j"
        import json
        body = json.loads(requests[0].content)
        assert body["expected_workspace_revision"] == 3 and "executor" not in body
        assert requests[0].headers["authorization"] == "Bearer synthetic-scoped-test-token"
    finally:
        env.close()


@pytest.mark.parametrize("status,code,retryable", [
    (401, "unauthorized", False), (403, "forbidden", False),
    (409, "version_or_request_conflict", False), (422, "invalid_parameters", False),
    (429, "rate_limited", True), (503, "http_503", True),
])
def test_http_errors_bounded_and_never_echo_server_secrets(status, code, retryable):
    env = make(lambda _: httpx.Response(status, text="private material or credential"))
    try:
        with pytest.raises(PortError) as exc:
            env.observe("s", 1)
        assert exc.value.code == code and exc.value.retryable == retryable
        assert "private" not in str(exc.value)
    finally:
        env.close()


def test_redirect_is_not_followed_with_credential():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(302, headers={"Location": "https://other.example/"})
    env = make(handler)
    try:
        with pytest.raises(PortError, match="http_302"):
            env.observe("s", 1)
        assert len(calls) == 1
    finally:
        env.close()


def test_absolute_route_rejected_before_transport():
    b = HttpBindings(lambda _: "https://other.example/", lambda s, a: "/", lambda s, j: "/",
                     Observation.model_validate, lambda x: x)
    calls = []
    env = make(lambda r: calls.append(r), b)
    try:
        with pytest.raises(PortError, match="unsafe_endpoint"):
            env.observe("s", 1)
        assert not calls
    finally:
        env.close()


def test_timeout_preserves_ambiguous_post_identity():
    def handler(request):
        raise httpx.ReadTimeout("sensitive transport detail", request=request)
    env = make(handler)
    try:
        command = Command(request_id="r", operation="read", expected_version=0, expected_workspace_revision=0)
        with pytest.raises(PortError) as exc:
            env.execute("s", command, 1)
        assert exc.value.retryable and exc.value.ambiguous
        assert "sensitive" not in str(exc.value)
    finally:
        env.close()


def test_reconcile_uses_read_only_request_lookup_and_never_posts():
    from dataclasses import replace
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={'job_id': 'saved-job'})
    env = make(handler)
    env.bindings = replace(env.bindings, request_result_path=lambda s, r: '/sessions/' + s + '/requests/' + r)
    command = Command(request_id='original-request', operation='submit', expected_version=0, expected_workspace_revision=0)
    try:
        assert env.reconcile('s', command, 1).job_id == 'saved-job'
        assert calls[0].method == 'GET' and calls[0].url.path.endswith('/original-request')
        assert len(calls) == 1
    finally:
        env.close()


def test_missing_reconcile_route_does_not_fallback_to_execution():
    calls = []
    env = make(lambda request: calls.append(request))
    try:
        with pytest.raises(PortError, match='request_lookup_not_installed'):
            env.reconcile('s', Command(request_id='r', operation='read', expected_version=0, expected_workspace_revision=0), 1)
        assert calls == []
    finally:
        env.close()
