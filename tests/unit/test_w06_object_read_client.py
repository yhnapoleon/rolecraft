from types import SimpleNamespace

import pytest

from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure
from examples.byo_agent_client.workflow import save


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / 'read.json'
    save(config, {'api_url': 'http://127.0.0.1:9', 'session_id': 'session1', 'token': 'PRIVATE'})
    client = HttpAgentClient(config)
    monkeypatch.setattr(client, 'observation', lambda *a, **kw: SimpleNamespace(
        tools=[SimpleNamespace(name='objects.read', available=True)]))
    client.sent = []
    def request(credentials, method, suffix, **kwargs):
        client.sent.append((method, suffix, kwargs.get('query')))
        return {'schema_version': 2, 'content': {'text': 'authorized body'}}
    monkeypatch.setattr(client, '_request', request)
    return client


@pytest.mark.parametrize('kind,extra,path,query', [
    ('material', {}, '/objects/material/brief/1', None),
    ('config', {'config_version': 0}, '/objects/config/brief/1', {'config_version': 0}),
])
def test_readonly_exact_object_uses_existing_get_without_command_or_receipt(client, kind, extra, path, query):
    ref = {'session_id': 'session1', 'kind': kind, 'object_id': 'brief', 'version': 1, **extra}
    result = client.call('objects.read', {'session_id': 'session1', 'query': {'ref': ref}})
    assert result['content']['text'] == 'authorized body'
    assert client.sent == [('GET', path, query)]


@pytest.mark.parametrize('ref,extra', [
    ({'session_id': 'other', 'kind': 'material', 'object_id': 'brief', 'version': 1}, {}),
    ({'session_id': 'session1', 'kind': 'material', 'object_id': '../private', 'version': 1}, {}),
    ({'session_id': 'session1', 'kind': 'test', 'object_id': 'brief', 'version': 1, 'config_version': 0}, {}),
    ({'session_id': 'session1', 'kind': 'material', 'object_id': 'brief', 'version': 1},
     {'as_of': {'business_seq': 0, 'workspace_revision': 0, 'storage_revision': 0}}),
])
def test_readonly_object_rejects_mixed_identity_path_or_unsupported_window_before_http(client, ref, extra):
    with pytest.raises(RemoteFailure):
        client.call('objects.read', {'session_id': 'session1', 'query': {'ref': ref, **extra}})
    assert not client.sent
