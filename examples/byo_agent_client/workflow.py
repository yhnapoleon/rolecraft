"""Persist exact business commands; advance only after authoritative completion."""
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.delegations.credentials import load_credentials
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def confirm(step, value, session_id, executor):
    try:
        result = C.RequestResult.model_validate(value)
    except ValidationError:
        raise RemoteFailure('request_result_contract_invalid') from None
    if (result.session_id != session_id or result.request_id != step['command']['request_id']
            or result.operation != step['name'] or result.executor != executor
            or result.response.boundary.request_id != result.request_id):
        raise RemoteFailure('request_result_identity_mismatch')
    # Preserve both the origin acknowledgement and each job's actual effect.
    # The origin response alone may only say that work was queued.
    step.update(status=result.status, result=result.response.model_dump(mode='json'),
                request_result=result.model_dump(mode='json'))


def run(config_path, journal_path, *, config_version, query='Which source supports this draft?', wait_seconds=5.0):
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 30:
        raise ValueError('invalid wait budget')
    credentials = load_credentials(config_path)
    client = HttpAgentClient(config_path)
    path = Path(journal_path)
    observation = client.observation(credentials.session_id)
    identity = {'api_url': credentials.api_url, 'executor': observation.actor.model_dump(mode='json')}
    if path.exists():
        record = json.loads(path.read_text())
        if record.get('session_id') != credentials.session_id or record.get('schema_version') != 1:
            raise ValueError('journal identity mismatch')
        if 'identity' in record and record['identity'] != identity:
            raise ValueError('journal identity mismatch')
        # A v1 journal did not bind the API/delegate. Recover existing commands
        # before adding an identity; never reissue its unknown requests on 404.
        legacy = 'identity' not in record and bool(record['steps'])
    else:
        if not observation.visible_sources:
            raise ValueError('Human investigation required before this example')
        legacy = False
        record = {'schema_version': 1, 'session_id': credentials.session_id, 'identity': identity,
                  'client': 'w06-no-model-example', 'provider': None, 'model': None, 'steps': [],
                  'draft': 'Source notes (unreviewed Agent draft):\n' + '\n'.join(x.text for x in observation.visible_sources),
                  'query': query, 'config_version': config_version}
    record['status'] = 'unconfirmed'
    save(path, record)
    operations = ('work_products.create', 'tests.create')
    for index, name in enumerate(operations):
        newly_prepared = len(record['steps']) <= index
        if newly_prepared:
            observation = client.observation(credentials.session_id)
            tool = next((t for t in observation.tools if t.name == name and t.available), None)
            if tool is None:
                raise RemoteFailure('example_tool_unavailable', 503)
            if name == 'work_products.create':
                payload = {'kind': 'text', 'title': 'Agent source notes', 'content': record['draft']}
            else:
                # This is explicit user setup, never a guessed production version.
                payload = {'query': record['query'], 'config_version': record['config_version']}
            command = C.Command(schema_version=2, request_id=uuid4().hex,
                                expected_version=observation.as_of.business_seq,
                                expected_workspace_revision=observation.as_of.workspace_revision,
                                operation=name, payload=payload)
            record['steps'].append({'name': name, 'command': command.model_dump(mode='json'), 'status': 'unconfirmed'})
            save(path, record)
        step = record['steps'][index]
        # Recheck even old "completed" entries: the first client version could
        # have written that status for a queued job. No fresh key is generated.
        try:
            recovered = client.wait_request(credentials.session_id, step['command']['request_id'], seconds=wait_seconds)
        except RemoteFailure as error:
            if (error.status != 404 or error.code != 'request_not_found'
                    or (legacy and not newly_prepared) or 'result' in step or 'request_result' in step):
                raise
            accepted = client.call(name, {'session_id': credentials.session_id, 'command': step['command']})
            step.update(status='unconfirmed', result=accepted)
            save(path, record)
            recovered = client.wait_request(credentials.session_id, step['command']['request_id'], seconds=wait_seconds)
        confirm(step, recovered, credentials.session_id, observation.actor)
        record['status'] = step['status'] if step['status'] != 'completed' else 'running'
        save(path, record)
        if step['status'] != 'completed':
            return record
    record.update(status='completed', identity=identity)
    save(path, record)
    return record
