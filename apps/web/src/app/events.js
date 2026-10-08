// Server events in plain language. Types come from GET /timeline; the live adapter
// renames read_material to material_read and copies the payload into `detail`.
import { T } from './i18n';
import { serverText } from '../store';
import { materialTitle } from './vocab.js';

const WORLD = ['policy_updated', 'approve_request', 'approval_denied', 'update_pilot', 'refresh_index', 'request_capacity', 'request_resources', 'submit_plan'];
export const isFeedEvent = e => WORLD.includes(e.type);

export function eventLine(a, e) {
  const d = e.detail || {};
  const w = a.world || {};
  switch (e.type) {
    case 'policy_updated': {
      const v = ((d.material_versions || []).find(x => x.material_id === 'policy') || {}).version || w.policyVersion;
      return { text: T(`差旅政策更新为 v${v}`, `Travel policy updated to v${v}`), icon: 'bolt', tone: 'warn', announce: 'policy' };
    }
    case 'approve_request':
      return d.rule_id === 'capacity_approved'
        ? { text: T(`经理批准扩容：上限 ${w.capacity} 人`, `The manager approved more seats: up to ${w.capacity}`), icon: 'check', tone: 'good', announce: 'info' }
        : { text: T(`经理批准资源：${w.devDays} 人日，第 ${w.deadline} 天上线`, `The manager approved resources: ${w.devDays} person-days, launch on day ${w.deadline}`), icon: 'check', tone: 'good', announce: 'info' };
    case 'approval_denied': return { text: serverText('', d.code, d.details), icon: 'hand' };
    case 'update_pilot': return { text: T('试点设置已保存', 'Pilot settings saved'), icon: 'gear' };
    case 'refresh_index': return { text: T('助手索引已刷新', 'Assistant index refreshed'), icon: 'refresh' };
    case 'request_capacity': return { text: T('你申请了更多名额', 'You asked for more seats'), icon: 'hand' };
    case 'request_resources': return { text: T('你申请了开发资源或延期', 'You asked for engineering time or a later date'), icon: 'hand' };
    case 'submit_plan': return { text: T('交付已固定', 'Deliverable submitted'), icon: 'stamp' };
    case 'save_artifact': return { text: T('交付稿已保存', 'Deliverable saved'), icon: 'doc' };
    case 'test_assistant': {
      const t = (a.tests || []).find(x => x.id === d.object_id);
      return { text: T('测试：', 'Test: ') + (t ? t.question : ''), icon: 'flask' };
    }
    case 'material_read':
    case 'read_material': {
      const m = ((a.backend && a.backend.materials) || []).find(x => x.id === (d.materialId || d.material_id));
      const title = m ? materialTitle(m) : (d.materialId || d.material_id || '');
      return { text: T(`读了《${title}》`, `Read “${title}”`), icon: 'doc' };
    }
    case 'pause': return { text: T('暂停了练习', 'Paused the practice'), icon: 'pause' };
    case 'resume': return { text: T('恢复了练习', 'Resumed the practice'), icon: 'play' };
    default: return { text: e.type, icon: 'info' };
  }
}
