// Server events in plain language. Types come from GET /timeline; the live adapter
// renames read_material to material_read and copies the payload into `detail`.
import { T, locale } from './i18n';
import { serverText } from '../store';
import { materialTitle } from './vocab.js';
import { describeServerEvent } from './event-copy';

const WORLD = [
  'policy_updated',
  'approve_request',
  'approval_denied',
  'update_pilot',
  'refresh_index',
  'request_capacity',
  'request_resources',
  'submit_plan',
];
export const isFeedEvent = (e) => WORLD.includes(e.type);

// Where each kind of line leads in the workbench.
const OPEN = {
  material: (s) => ({ action: 'open-doc', id: s.id, ...(s.compare ? { compare: true } : {}) }),
  test: (s) => ({ action: 'open-run', id: s.id }),
  settings: () => ({ action: 'config' }),
  resources: () => ({ action: 'resources' }),
  bench: () => ({ action: 'open-bench' }),
  review: () => ({ action: 'to-review' }),
};
// Titles, questions and delivery order this attempt can actually read.
function lookups(a) {
  const materials = a.backend?.materials || [];
  const titles = a.backend?.materialTitles || {};
  const deliveries = (a.events || [])
    .filter((x) => x.server && x.type === 'submitted')
    .sort((x, y) => x.seq - y.seq)
    .map((x) => (x.refs || []).find((r) => r.kind === 'submission')?.object_id);
  return {
    materialTitle: (id, version) => {
      const exact = version && titles[`${id}:${version}`];
      const m = exact ? { id, title: exact } : materials.find((x) => x.id === id);
      return m ? materialTitle(m) : undefined;
    },
    testQuery: (id) => (a.tests || []).find((x) => x.id === id)?.question || undefined,
    deliveryNumber: (id) => {
      const i = deliveries.indexOf(id);
      return i < 0 ? undefined : i + 1;
    },
  };
}

export function eventLine(a, e) {
  const d = e.detail || {};
  const w = a.world || {};
  switch (e.type) {
    case 'policy_updated': {
      const v =
        ((d.material_versions || []).find((x) => x.material_id === 'policy') || {}).version ||
        w.policyVersion;
      return {
        text: T(`差旅政策更新为 v${v}`, `Travel policy updated to v${v}`),
        icon: 'bolt',
        tone: 'warn',
        announce: 'policy',
        world: true,
      };
    }
    case 'approve_request':
      return d.rule_id === 'capacity_approved'
        ? {
            text: T(
              `经理批准扩容：上限 ${w.capacity} 人`,
              `The manager approved more seats: up to ${w.capacity}`,
            ),
            icon: 'check',
            tone: 'good',
            announce: 'info',
            world: true,
          }
        : {
            text: T(
              `经理批准资源：${w.devDays} 人日，第 ${w.deadline} 天上线`,
              `The manager approved resources: ${w.devDays} person-days, launch on day ${w.deadline}`,
            ),
            icon: 'check',
            tone: 'good',
            announce: 'info',
            world: true,
          };
    case 'approval_denied':
      return { text: serverText('', d.code, d.details), icon: 'hand', world: true };
    case 'update_pilot':
      return { text: T('试点设置已保存', 'Pilot settings saved'), icon: 'gear' };
    case 'refresh_index':
      return { text: T('助手索引已刷新', 'Assistant index refreshed'), icon: 'refresh' };
    case 'request_capacity':
      return { text: T('你申请了更多名额', 'You asked for more seats'), icon: 'hand' };
    case 'request_resources':
      return {
        text: T('你申请了开发资源或延期', 'You asked for engineering time or a later date'),
        icon: 'hand',
      };
    case 'submit_plan':
      return { text: T('交付已固定', 'Deliverable submitted'), icon: 'stamp' };
    case 'save_artifact':
      return { text: T('交付稿已保存', 'Deliverable saved'), icon: 'doc' };
  }
  // v2 events (and anything unknown) in plain words. v1 test events carry the test ID in the
  // payload instead of a reference.
  const refs =
    e.refs?.length || e.type !== 'test_assistant' || !d.object_id
      ? e.refs
      : [{ kind: 'test', object_id: d.object_id }];
  const copy = describeServerEvent({ type: e.type, data: d, refs }, lookups(a), locale());
  const subject = copy.subject;
  const test =
    subject?.kind === 'test' ? (a.tests || []).find((x) => x.id === subject.id) : undefined;
  return {
    text: (e.agent ? T('我的 Agent：', 'My agent: ') : '') + copy.text,
    icon: copy.icon,
    tone: copy.tone,
    world: copy.world,
    open: subject ? OPEN[subject.kind](subject) : undefined,
    taskId: test?.taskId,
  };
}
