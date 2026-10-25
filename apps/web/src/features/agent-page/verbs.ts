// What each MCP tool means to the person watching: which way the content travels and the plain
// verb a stream row starts with. Tool names are the delegated Agent tools of
// src/career_lab/delegations/catalog.py; reading a document's text is objects.read (there is no
// materials.get). Never offered to an Agent: submitting, engineer.submissions.sign,
// engineer.tickets.create, turns.create and feedback.create.

export type Direction = 'to_agent' | 'to_workspace';
export type Pair = [zh: string, en: string];
export type Verb = { direction: Direction; verb: Pair; group: 'read' | 'act' | 'return' };

const read = (zh: string, en: string): Verb => ({
  direction: 'to_agent',
  verb: [zh, en],
  group: 'read',
});
const act = (zh: string, en: string): Verb => ({
  direction: 'to_workspace',
  verb: [zh, en],
  group: 'act',
});
const handBack = (zh: string, en: string): Verb => ({
  direction: 'to_workspace',
  verb: [zh, en],
  group: 'return',
});

export const VERBS: Record<string, Verb> = {
  observation: read('查看了工作区', 'Looked around the workspace'),
  tools: read('查看了能用的工具', 'Checked what it may use'),
  'materials.list': read('翻阅了', 'Looked through'),
  'objects.read': read('读了', 'Read'),
  read_material: read('读了', 'Read'),
  'work_items.list': read('翻阅了', 'Looked through'),
  'work_products.list': read('翻阅了', 'Looked through'),
  'work_products.versions.list': read('读了各版本', 'Read the versions of'),
  'work_products.shares.list': read('查看了分享', 'Checked who has'),
  'tests.list': read('翻阅了', 'Looked through'),
  'reviews.read': read('读了评审', 'Read the review'),
  'feedback.records.read': read('读了反馈', 'Read the feedback'),
  'feedback.responses.list': read('读了反馈回应', 'Read the replies to'),
  'feedback.responses.read': read('读了反馈回应', 'Read a reply to'),
  'submissions.list': read('翻阅了', 'Looked through'),
  'requests.read': read('查了一次请求的结果', 'Checked on a request'),
  'workspace_imports.list': read('翻阅了', 'Looked through'),
  'workspace_imports.read': read('读了导入', 'Read an import'),
  'engineer.tickets.read': read('读了工单', 'Read the ticket'),
  'engineer.reviews.read': read('读了复核', 'Read the review'),
  'tests.create': act('跑了一次测试', 'Ran a test'),
  'engineer.reproduce': act('复现了', 'Reproduced'),
  'engineer.trial': act('试跑了', 'Ran a trial'),
  'feedback.responses.create': handBack('回应了反馈', 'Replied to feedback'),
  'work_products.create': handBack('交回了', 'Handed back'),
  'work_products.versions.create': handBack('交回了新版本', 'Handed back a new version of'),
  'work_items.create': handBack('加了一件事', 'Added a task'),
  'work_items.update': handBack('改了一件事', 'Updated a task'),
  'work_items.batch': handBack('整理了事项', 'Rearranged tasks'),
  'engineer.submissions.draft': handBack('起草了签字', 'Drafted a sign-off'),
};

/** Tools a connection is granted: everything above, nothing a person must do themselves. */
export const GRANTED_TOOLS = Object.keys(VERBS);
export const NEVER_GRANTED = [
  'submit',
  'submissions.create',
  'work_products.adopt',
  'begin_revision',
  'revision_cycles',
  'engineer.submissions.sign',
  'engineer.tickets.create',
  'turns.create',
  'feedback.create',
] as const;

export const verbOf = (tool: string): Verb =>
  VERBS[tool] ?? read(`调用了 ${tool}`, `Called ${tool}`);

/** What a list read looked through, as the object of "Looked through …". */
const LISTS: Record<string, Pair> = {
  'materials.list': ['份资料', 'documents'],
  'work_items.list': ['件事项', 'tasks'],
  'work_products.list': ['份作品', 'pieces of work'],
  'tests.list': ['次测试', 'test runs'],
  'submissions.list': ['次交付', 'deliveries'],
  'workspace_imports.list': ['次导入', 'imports'],
};
export function listObject(tool: string, count: number | null | undefined): Pair | null {
  const noun = LISTS[tool];
  if (!noun) return null;
  if (count == null) return [noun[0].replace(/^[份件次]/, ''), noun[1]];
  return [`${count} ${noun[0]}`, `${count} ${count === 1 ? singular(noun[1]) : noun[1]}`];
}
const singular = (en: string) =>
  ({
    documents: 'document',
    tasks: 'task',
    'pieces of work': 'piece of work',
    'test runs': 'test run',
    deliveries: 'delivery',
    imports: 'import',
  })[en] ?? en;

/** A known refusal: why, in one sentence, and what to tell the Agent instead. */
export function refusal(code: string | null | undefined, tool = ''): { why: Pair; tell: Pair } {
  const lifecycle = tool === 'work_products.remove' || tool === 'work_products.restore';
  switch (code) {
    case 'version_conflict':
      return {
        why: ['它读过之后，这份作品又改过了。', 'The work changed after your agent read it.'],
        tell: [
          '先用 work_products.versions.list 读最新版本，再把 expected_head 设成它，重新交回。',
          'Read the latest version with work_products.versions.list, set expected_head to it, then hand it back again.',
        ],
      };
    case 'capability_forbidden':
    case 'action_forbidden':
    case 'human_adoption_required':
      return {
        why: ['这一步只能你自己做。', 'Only you can do this step.'],
        tell: [
          '只读资料、跑测试、交回草稿；采用和交付留给我。',
          'Read, run tests and hand back drafts; leave adopting and submitting to me.',
        ],
      };
    case 'session_submitted':
    case 'session_paused':
    case 'session_not_active':
      return {
        why: ['这一局现在不收新东西。', 'This practice is not taking new work right now.'],
        tell: ['等我开始修订后再交回。', 'Wait until I start a revision, then hand it back.'],
      };
    case 'tool_arguments_invalid':
    case 'operation_route_mismatch':
    case 'route_object_required':
      return {
        why: ['请求的格式不对。', 'The request was not in the expected shape.'],
        tell: [
          '按 tools/list 里这个工具的 inputSchema 填字段，再发一次。',
          'Fill in exactly the fields in this tool’s inputSchema from tools/list, then send it again.',
        ],
      };
    case 'lifecycle_permission_unavailable':
      // The same code answers two different refusals; the tool says which one this was.
      return lifecycle
        ? {
            why: ['删除和恢复作品只能你自己来做。', 'Only you can remove or restore work.'],
            tell: [
              '不要删除或恢复作品，这一步留给我。',
              'Don’t remove or restore work; leave that to me.',
            ],
          }
        : {
            why: ['它改的版本已经不是最新的。', 'The version it edited is no longer the latest.'],
            tell: [
              '先用 work_products.versions.list 读最新版本，再在它上面交回新版本。',
              'Read the latest version with work_products.versions.list, then hand back a new version on top of it.',
            ],
          };
    default:
      return {
        why: [
          `RoleCraft 没有接受（${code || '未知原因'}）。`,
          `RoleCraft refused it (${code || 'unknown reason'}).`,
        ],
        tell: [
          '先用 requests.read 查原请求的结果，告诉我发生了什么，再决定要不要重试。',
          'Check the original request with requests.read and tell me what happened before you retry.',
        ],
      };
  }
}

/** The product name of a client from its self-reported clientInfo.name. */
export function clientName(name: string | null | undefined): string {
  const n = String(name || '').toLowerCase();
  if (!n) return 'My agent';
  if (n.includes('claude')) return 'Claude Code';
  if (n.includes('codex')) return 'Codex';
  if (n.includes('cursor')) return 'Cursor';
  return String(name);
}
