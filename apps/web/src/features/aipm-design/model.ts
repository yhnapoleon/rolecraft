import type { AipmDesign, ObjectRef, ProcessFeedback, StepId, TriageRow } from '../../aipm/types';
import { STEP_IDS } from '../../aipm/types';

export type Language = 'zh' | 'en';
export const text = (language: Language, zh: string, en: string) => language === 'zh' ? zh : en;
export const escape = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
export const sameRef = (a?: ObjectRef | null, b?: ObjectRef | null) => !!a && !!b && a.session_id === b.session_id && a.kind === b.kind && a.object_id === b.object_id && a.version === b.version;
export function emptySections(): Record<StepId, string> { return Object.fromEntries(STEP_IDS.map(id => [id, ''])) as Record<StepId, string>; }
export function newRow(id: string): TriageRow {
  return { id, revision: 1, need_ref: '', source_refs: [], user_request: '', target_action: 'unknown', route: 'retrieval_generation', rationale: '', final_authority: 'unknown', confirmation_point: '', tool_assumptions: [], unresolved: [], execution_support: 'unknown' };
}
/** The server remains authoritative. Increment a row only if its declared choices changed. */
export function nextDesign(draft: AipmDesign, saved: AipmDesign | null): AipmDesign {
  const compare = ({ revision: _r, execution_support: _s, ...value }: TriageRow) => JSON.stringify(value);
  return { ...structuredClone(draft), revision: (saved?.revision ?? 0) + 1,
    rows: (draft.rows ?? []).map(row => {
      const previous = saved?.rows?.find(r => r.id === row.id);
      return { ...row, revision: previous ? (previous.revision ?? 1) + Number(compare(row) !== compare(previous)) : 1, execution_support: 'unknown' };
    }),
  };
}
export function visibleFeedback(items: ProcessFeedback[], savedRef: ObjectRef | null, dirty: boolean) {
  return items.map(item => ({ ...item, stale: !!item.stale || dirty || !sameRef(item.input_ref, savedRef) }));
}
export type DiagramLane = { rowId: string; request: string; nodes: string[]; status: string; sourceRefs: TriageRow['source_refs'] };
/** Fixed structure, always a proposed design. Actual settings are rendered independently. */
export function diagram(design: AipmDesign, language: Language): DiagramLane[] {
  const t = (zh: string, en: string) => text(language, zh, en);
  return (design.rows ?? []).map(row => {
    let nodes: string[];
    switch (row.route) {
      case 'deterministic': nodes = [t('已确认输入', 'Confirmed inputs'), t('规则与校验', 'Rules and validation'), t('计算或检查结果', 'Calculation or check')]; break;
      case 'retrieval_generation': nodes = [t('公开资料', 'Public sources'), t('索引与检索', 'Index and retrieval'), t('有出处的回答', 'Cited answer')]; break;
      case 'agent_confirmation': nodes = [t('整理与拟稿', 'Organize and draft'), ...(row.tool_assumptions?.length ? row.tool_assumptions : [t('待核对的工具', 'Tools to confirm')]), row.confirmation_point || t('待明确确认人和时点', 'Name who confirms and when')]; break;
      case 'human': nodes = [t('请求与依据', 'Request and evidence'), row.confirmation_point || t('有权限的接手人', 'Authorized owner'), t('人工处理记录', 'Human action record')]; break;
    }
    return { rowId: row.id, request: row.user_request || t('未命名需求', 'Untitled need'), nodes, sourceRefs: row.source_refs,
      status: row.execution_support === 'supported' ? t('已有受支持路径，未在此执行', 'Supported path; not executed here') : row.execution_support === 'plan_only' ? t('仅方案，尚无执行能力', 'Proposal only; execution unavailable') : t('执行能力待核对', 'Execution support unknown') };
  });
}
export function designSummary(design: AipmDesign, language: Language): { boundary: string; solution: string } {
  const lanes = diagram(design, language);
  return { boundary: lanes.map(lane => `${lane.request}\n${lane.nodes.join(' → ')}\n${lane.status}`).join('\n\n'),
    solution: [design.solution?.selected_approach, design.solution?.rationale, design.solution?.alternative, ...(design.solution?.dependencies ?? []), text(language, `来源：需求与方案第 ${design.revision} 版；保存方案不应用实际设置。`, `Source: needs and design version ${design.revision}; saving a design does not apply settings.`)].filter(Boolean).join('\n') };
}
