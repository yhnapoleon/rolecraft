"""Exercise an already-running service through public HTTP and optional Codex MCP.

Creates a new, isolated session. Never loads a store, scenario source, history
bridge or model. Private credentials and exact commands survive in run_dir;
trace.json contains only public responses and must not be called production
acceptance unless the service's independently pinned identity was verified.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from career_lab.contracts import v2 as C
from career_lab.delegations.credentials import load_credentials, redact
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure, safe_id

if __package__:
    from .codex_client import CodexMcpClient
    from .workflow import save
else:
    from codex_client import CodexMcpClient
    from workflow import save


def require(condition, code):
    if not condition:
        raise RemoteFailure(code)


class ServiceCheck:
    def __init__(self, api_url, run_dir, *, transport='http', cwd=None):
        url = urlsplit(api_url)
        require(url.hostname in {'127.0.0.1', 'localhost', '::1'} and url.scheme == 'http'
                and not (url.username or url.password or url.query or url.fragment or url.path.strip('/')),
                'local_service_required')
        require(transport in {'http', 'codex'}, 'transport_invalid')
        self.directory = Path(run_dir)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.http = httpx.Client(base_url=api_url.rstrip('/'), timeout=15, follow_redirects=False, trust_env=False)
        self.api_url, self.transport = api_url.rstrip('/'), transport
        self.cwd = cwd or Path(__file__).resolve().parents[2]
        self.trace = {'status': 'running', 'transport': transport, 'api_url': self.api_url,
                      'provider': None, 'model': None, 'model_turn_started': False, 'client_uses_history_bridge': False,
                      'service_history_source': 'unverified_by_client',
                      'boundary': 'Public client trace; service source identity must be independently verified.', 'steps': []}
        self.secrets = []
        self.agent = None
        self.delegate_token = None
        self.sid = self.token = self.delegation = None
        self.persist()

    def persist(self):
        trace = self.trace
        for secret in self.secrets:
            trace = redact(trace, secret)
        save(self.directory / 'trace.json', trace)

    def owner(self, method, suffix, body=None):
        response = self.http.request(method, suffix, json=body,
                                     headers={'Authorization': 'Bearer ' + self.token} if self.token else {})
        if response.status_code >= 300:
            try: code = response.json().get('code')
            except (ValueError, AttributeError): code = None
            if not isinstance(code, str) or not re.fullmatch('[a-z][a-z0-9_]{0,95}', code):
                code = 'service_request_failed'
            raise RemoteFailure(code, response.status_code)
        return response.json()

    def command(self, name, payload):
        state = self.owner('GET', '/sessions/' + self.sid)['state']
        return C.Command(schema_version=2, request_id=uuid4().hex,
                         expected_version=state['business_seq'], expected_workspace_revision=state['workspace_revision'],
                         operation=name, payload=payload).model_dump(mode='json')

    def human(self, name, suffix, payload, *, method='POST'):
        command = self.command(name, payload)
        step = {'executor': 'human', 'operation': name, 'command': command, 'status': 'unconfirmed'}
        self.trace['steps'].append(step); self.persist()
        result = self.owner(method, '/sessions/' + self.sid + suffix, command)
        step.update(status='responded', response=redact(result, '')); self.persist()
        return result

    def call(self, name, arguments):
        result = self.agent.call(name, arguments)
        if self.transport == 'codex':
            if result.get('isError'):
                raise RemoteFailure(result.get('structuredContent', {}).get('code', 'mcp_tool_failed'))
            return result['structuredContent']
        return result

    def observe(self):
        value = self.call('observation', {'session_id': self.sid})
        return C.Observation.model_validate(value['result'])

    def agent_command(self, name, payload):
        command = self.command(name, payload)
        step = {'executor': 'external_agent', 'operation': name, 'command': command, 'status': 'unconfirmed'}
        self.trace['steps'].append(step); self.persist()
        response = self.call(name, {'session_id': self.sid, 'command': command})
        step['response'] = response; self.persist()
        recovered = self.call('requests.read', {'session_id': self.sid, 'query': {'request_id': command['request_id']}})
        result = C.RequestResult.model_validate(recovered)
        require(result.request_id == command['request_id'] and result.operation == name
                and result.session_id == self.sid and result.executor == self.observe().actor,
                'request_recovery_identity_mismatch')
        step.update(status=result.status, recovered=recovered); self.persist()
        require(result.status == 'completed', 'request_requires_followup')
        return response, command

    def run(self, *, scenario, query, config_version, material_id=None, work_language=None):
        try:
            create = {'schema_version': 2, 'scenario': scenario}
            if work_language is not None: create['work_language'] = work_language
            created = self.owner('POST', '/sessions', create)
            self.sid, self.token = created['session_id'], created['token']
            self.secrets.append(self.token)
            save(self.directory / 'owner.json', {'api_url': self.api_url, 'session_id': self.sid, 'token': self.token})
            self.trace.update(session_id=self.sid, session=redact(created, ''), query=query, config_version=config_version)
            self.persist()
            grant = self.human('delegations.create', '/delegations', {
                'agent_label': 'Explicit public service check', 'capabilities': ['read', 'act'],
                'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()})['result']['result']
            self.delegation = grant['delegation']['id']
            self.delegate_token = grant['token']
            self.secrets.append(grant['token']); self.persist()
            config = self.directory / 'delegate.json'
            save(config, {'api_url': self.api_url, 'session_id': self.sid, 'token': grant['token']})
            self.agent = (HttpAgentClient(config) if self.transport == 'http'
                          else CodexMcpClient(config, cwd=self.cwd))
            before = self.observe()
            require(before.actor.kind == 'external_agent', 'delegation_required')
            require(not before.visible_sources and not before.read_versions, 'fresh_session_not_unread')
            self.trace['initial_observation'] = before.model_dump(mode='json'); self.persist()
            candidates = [m for m in before.catalog if material_id is None or m.id == material_id]
            require(bool(candidates), 'public_material_missing')
            material = candidates[0]
            ref = C.ObjectRef(session_id=self.sid, kind='material', object_id=material.id, version=material.version)
            read, _ = self.agent_command('read_material', {'tool': 'read_material', 'material': ref.model_dump(mode='json')})
            after = self.observe()
            texts = [f['text'] for f in read['result']['fragments']]
            require(bool(texts) and all(any(f.ref.object_id == material.id and f.ref.version == material.version
                    and f.text == text and f.acquired_via == 'material_read' and not f.fact_ids
                    for f in after.visible_sources) for text in texts), 'material_receipt_missing')
            require(ref in after.read_versions, 'read_version_missing')
            require('fact_ids' not in json.dumps(read), 'material_private_metadata')
            self.trace.update(initial_observation=before.model_dump(mode='json'),
                              acquired_observation=after.model_dump(mode='json')); self.persist()
            product, command = self.agent_command('work_products.create', {
                'kind': 'investigation', 'title': 'External Agent source notes', 'content': '\n\n'.join(texts)})
            obj = product['result']['object']
            require(obj['executor']['kind'] == 'external_agent' and obj['adoption']['status'] == 'unadopted',
                    'product_attribution_invalid')
            state = self.owner('GET', '/sessions/' + self.sid)
            replay = self.call('work_products.create', {'session_id': self.sid, 'command': command})
            require(replay['replayed'] and self.owner('GET', '/sessions/' + self.sid) == state, 'replay_changed_state')
            self.trace['product_replay'] = replay; self.persist()
            tested, _ = self.agent_command('tests.create', {'query': query, 'config_version': config_version})
            require(tested['result']['test']['execution']['executor']['kind'] == 'external_agent', 'test_attribution_invalid')
            adopted = self.human('work_products.adopt', '/work-products/' + obj['product_id'] + '/adoption', {
                'product_id': obj['product_id'], 'product_version': obj['version'], 'expected_head': obj['version'], 'status': 'adopted'})
            submitted = self.human('submit', '/submissions', {'decision': 'defer_with_conditions', 'products': [adopted['result']['ref']]})
            require(submitted['executor']['kind'] == 'human' and submitted['state']['status'] == 'submitted', 'human_submission_invalid')
            self.revoke()
            state = self.owner('GET', '/sessions/' + self.sid)
            denied_http = self.http.get('/sessions/' + self.sid + '/observation',
                headers={'Authorization': 'Bearer ' + self.delegate_token})
            require(denied_http.status_code in {401, 403}, 'revocation_http_not_verified')
            self.trace['revocation_http_status'] = denied_http.status_code
            try: self.observe()
            except (RemoteFailure, RuntimeError) as error:
                # A network error is not evidence of an authorization denial.
                denied = ((isinstance(error, RemoteFailure) and error.status in {401, 403})
                          or (self.transport == 'codex' and str(error) == 'codex_client_rpc_failed: 1001'))
                require(denied, 'revocation_not_verified')
            else: raise RemoteFailure('revocation_not_enforced')
            require(self.owner('GET', '/sessions/' + self.sid) == state, 'revoked_read_changed_state')
            if self.transport == 'codex':
                require('turn/start' not in self.agent.calls, 'unexpected_model_turn')
                self.trace['codex_protocol_calls'] = self.agent.calls
            self.trace.update(status='completed', revocation_denied=True)
            self.persist()
            return self.trace
        except Exception as error:
            code = error.code if isinstance(error, RemoteFailure) else 'client_check_failed'
            self.trace.update(status='incomplete', failure_code=code)
            self.persist()
            raise
        finally:
            if self.agent is not None and self.transport == 'codex': self.agent.close()
            self.http.close()

    def revoke(self):
        self.human('delegations.revoke', '/delegations/' + self.delegation,
                   {'delegation_id': self.delegation}, method='DELETE')


def recover_requests(run_dir):
    """Human read-only recovery, including after the delegate was revoked.

    The original trace and commands are preserved. No command is sent again;
    missing, failed or queued effects never become a new request or model call.
    """
    directory = Path(run_dir)
    owner = load_credentials(directory / 'owner.json')
    trace = json.loads((directory / 'trace.json').read_text())
    require(trace.get('session_id') == owner.session_id, 'recovery_session_mismatch')
    actor = trace.get('initial_observation', {}).get('actor')
    report = {'session_id': owner.session_id, 'mode': 'human_read_only', 'requests': [],
              'original_trace_unchanged': True, 'commands_reexecuted': False}
    with httpx.Client(base_url=owner.api_url, timeout=15, trust_env=False, follow_redirects=False) as http:
        for step in trace['steps']:
            if step['executor'] != 'external_agent': continue
            command = C.Command.model_validate(step['command'])
            response = http.get('/sessions/' + safe_id(owner.session_id) + '/requests/' + safe_id(command.request_id),
                                headers={'Authorization': 'Bearer ' + owner.token})
            entry = {'request_id': command.request_id, 'operation': command.operation,
                     'http_status': response.status_code, 'status': 'unconfirmed'}
            if response.status_code == 200:
                result = C.RequestResult.model_validate(response.json())
                require(result.session_id == owner.session_id and result.request_id == command.request_id
                        and result.operation == command.operation and result.executor.model_dump(mode='json') == actor,
                        'request_recovery_identity_mismatch')
                entry.update(status=result.status, executor=result.executor.model_dump(mode='json'),
                             jobs=[job.model_dump(mode='json') for job in result.jobs])
            elif response.status_code == 404:
                entry['status'] = 'not_found_or_not_visible'
            report['requests'].append(entry)
    save(directory / 'recovery.json', redact(report, owner.token))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url')
    parser.add_argument('--recover-run', type=Path, help='Read original requests as the human owner; sends no command')
    parser.add_argument('--run-dir', type=Path, help='New private directory; never reuse an interrupted run')
    parser.add_argument('--transport', choices=('http', 'codex'), default='http')
    parser.add_argument('--scenario', default='pm_pilot_v2')
    parser.add_argument('--query')
    parser.add_argument('--config-version', type=int)
    parser.add_argument('--material-id')
    parser.add_argument('--work-language', choices=('zh', 'en'))
    args = parser.parse_args(argv)
    if args.recover_run:
        if args.api_url or args.run_dir: parser.error('recovery uses the original private owner configuration')
        try:
            report = recover_requests(args.recover_run)
        except Exception:
            print('Recovery unconfirmed. Keep the original trace and credentials.', file=sys.stderr)
            return 1
        print('Read ' + str(len(report['requests'])) + ' original requests; no command was reexecuted. See recovery.json.')
        return 0
    if not args.api_url or not args.run_dir or args.query is None or args.config_version is None:
        parser.error('new runs require --api-url, --run-dir, --query and --config-version')
    try:
        check = ServiceCheck(args.api_url, args.run_dir, transport=args.transport)
        check.run(scenario=args.scenario, query=args.query, config_version=args.config_version,
                  material_id=args.material_id, work_language=args.work_language)
    except Exception:
        print('Incomplete. Preserve trace.json and private credentials; recover original request IDs before further actions.', file=sys.stderr)
        return 1
    print('Public service transport check completed; no model turn. Evidence: ' + str(args.run_dir / 'trace.json'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
