/** Test harness only, never installed into the workbench. */
import {
  mount,
  mountConversation,
  type RolesView,
  type RolesNativeAdapter,
  type RoleId,
} from './index';
import { setPreference } from '../../app/i18n';
import { createGatewayTransport } from '../../gateway-transport';
import { request as legacyRead } from '../../api';
setPreference('zh');
const node = document.querySelector<HTMLElement>('#roles')!;
const colleagues = [
  { id: 'supervisor' as const, name: '经理', available: true },
  { id: 'business_lead' as const, name: '业务负责人', available: true },
  { id: 'tech_lead' as const, name: '技术负责人', available: true },
];
let view: RolesView = {
  sessionId: 'component-fixture',
  workLanguage: 'zh',
  mode: 'local_reference',
  colleagues,
  turns: [],
  canSend: true,
};
const calls: unknown[] = [];
const drafts = new Map<RoleId, string>();
let listener = () => {};
let failRead = false;
let loseResponse = false;
let holdSend = false;
let releaseSend = () => {};
let pending: { roleId: RoleId; text: string } | undefined;
const adapter: RolesNativeAdapter = {
  async read() {
    if (failRead) throw Error('PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER');
    return structuredClone(view);
  },
  async send(input) {
    calls.push(['send', structuredClone(input)]);
    pending = input;
    if (holdSend)
      await new Promise<void>((resolve) => {
        releaseSend = resolve;
      });
    view = {
      ...view,
      turns: [
        ...view.turns,
        {
          id: 'turn-' + view.turns.length,
          roleId: input.roleId,
          question: input.text,
          status: 'queued',
        },
      ],
    };
    if (loseResponse) {
      loseResponse = false;
      view.unconfirmed = true;
      throw Error('PRIVATE_DIAGNOSTIC_MUST_NOT_RENDER');
    }
  },
  async recover() {
    calls.push(['recover']);
    view.unconfirmed = false;
    return pending ? { confirmed: pending } : undefined;
  },
  async retry(id) {
    calls.push(['retry', id]);
    view = {
      ...view,
      turns: view.turns.map((t) => (t.id === id ? { ...t, status: 'queued' } : t)),
    };
  },
  async refreshContext(id) {
    calls.push(['refresh', id]);
    view = {
      ...view,
      turns: view.turns.map((t) => (t.id === id ? { ...t, status: 'queued' } : t)),
    };
  },
  async recordDisplay(id) {
    calls.push(['display', id]);
    if (displayFailure) throw Error('PRIVATE_DISPLAY_ERROR_MUST_NOT_RENDER');
  },
  openMaterial(ref) {
    calls.push(['material', ref]);
  },
  subscribe(fn) {
    listener = fn;
    return () => {
      listener = () => {};
      calls.push(['unsubscribe']);
    };
  },
  drafts: {
    read: (id) => drafts.get(id) || '',
    write: (id, text) => {
      drafts.set(id, text);
    },
  },
};
let handle = mount(node, adapter);
let displayFailure = false;
const controls = {
  calls,
  drafts,
  displayFailure(value: boolean) {
    displayFailure = value;
  },
  get view() {
    return view;
  },
  setView(next: RolesView) {
    view = next;
    listener();
  },
  loseResponse() {
    loseResponse = true;
  },
  holdSend() {
    holdSend = true;
  },
  release() {
    holdSend = false;
    releaseSend();
  },
  failRead(value: boolean) {
    failRead = value;
  },
  locale: setPreference,
  remount() {
    handle.destroy();
    handle = mount(node, adapter);
  },
  embedded(role: RoleId) {
    handle.destroy();
    handle = mountConversation(node, adapter, role);
  },
  destroy() {
    handle.destroy();
  },
  refresh() {
    return handle.refresh();
  },
};
Object.assign(window, { rolesTest: controls });

// Separate real-HTTP boundary mode. The test uses the existing transport and
// existing v2 endpoints; c7 deliberately returns unavailable private generation.
// This harness's in-memory command is a test journal, not a production client.
if (new URLSearchParams(location.search).get('mode') === 'http') {
  handle.destroy();
  document.querySelector('#fixture-description')!.textContent =
    '原生部件验收页 · 真实HTTP与独立worker · c7私有端口安全关闭路径';
  const raw = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schema_version: 2, scenario: 'w04-unavailable-ports' }),
  });
  if (!raw.ok) throw Error('Test API unavailable');
  const session = await raw.json();
  const sessionId = session.session_id as string;
  const transport = createGatewayTransport(() => ({ sessionId, token: session.token }));
  const commands: { command: any; roleId: RoleId; text: string; jobId?: string }[] = [];
  let current: (typeof commands)[number] | undefined;
  const ingest = (entry: (typeof commands)[number], result: any) => {
    const body = result.response?.result ?? result.result;
    if (body?.queued_jobs?.length) entry.jobId = body.queued_jobs[0];
    if (typeof body?.question === 'string') entry.text = body.question;
  };
  adapter.read = async () => {
    const turns = [];
    for (const entry of commands) {
      if (!entry.jobId) continue;
      const job: any = await legacyRead(`/sessions/${sessionId}/jobs/${entry.jobId}`, undefined, {
        id: sessionId,
        token: session.token,
      });
      turns.push({
        id: entry.command.request_id,
        roleId: entry.roleId,
        question: entry.text,
        status: job.status,
        explanation: job.status === 'failed' ? '本地生成端口尚未接入，问题已保存。' : undefined,
      });
    }
    return {
      sessionId,
      workLanguage: 'zh',
      mode: 'local_reference',
      colleagues,
      turns,
      canSend: true,
      unconfirmed: !!view.unconfirmed,
    };
  };
  adapter.send = async (input) => {
    calls.push(['send', structuredClone(input)]);
    const state: any = await transport(`/sessions/${sessionId}`);
    current = {
      roleId: input.roleId,
      text: input.text,
      command: {
        schema_version: 2,
        request_id: crypto.randomUUID(),
        operation: 'turns.create',
        expected_version: state.state.business_seq,
        expected_workspace_revision: state.state.workspace_revision,
        payload: { role_id: input.roleId, text: input.text },
      },
    };
    commands.push(current);
    pending = input;
    const result = await transport(`/sessions/${sessionId}/turns`, current.command);
    ingest(current, result);
    if (loseResponse) {
      loseResponse = false;
      view.unconfirmed = true;
      throw Error('test response loss after server acceptance');
    }
  };
  adapter.recover = async () => {
    calls.push(['recover']);
    if (!current) return;
    const result: any = await transport(
      `/sessions/${sessionId}/requests/${current.command.request_id}`,
    );
    ingest(current, result);
    if (!result.response?.result?.question) throw Error('Original request unconfirmed');
    view.unconfirmed = false;
    return { confirmed: { roleId: current.roleId, text: result.response.result.question } };
  };
  adapter.retry = undefined;
  adapter.refreshContext = undefined;
  handle = mount(node, adapter);
  Object.assign(window, {
    rolesHttp: {
      ready: true,
      requestCount: () => commands.length,
      publicEvidence: () =>
        commands.map((c) => ({
          requestId: c.command.request_id,
          question: c.text,
          jobId: c.jobId,
        })),
    },
  });
}

if (['v4-slot', 'v4-real-host'].includes(new URLSearchParams(location.search).get('mode') || '')) {
  handle.destroy();
  const fixture = await import('./v4-fixture');
  await fixture.start(node, new URLSearchParams(location.search).get('mode') === 'v4-real-host');
}
