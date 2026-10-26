import type { AipmDesign, ObjectRef, ProcessFeedback, StepId, TriageRow } from '../../aipm/types';
import { STEP_IDS } from '../../aipm/types';

export type Language = 'zh' | 'en';
export const text = (language: Language, zh: string, en: string) => (language === 'zh' ? zh : en);
export const sameRef = (a?: ObjectRef | null, b?: ObjectRef | null) =>
  !!a &&
  !!b &&
  a.session_id === b.session_id &&
  a.kind === b.kind &&
  a.object_id === b.object_id &&
  a.version === b.version;
export function emptySections(): Record<StepId, string> {
  return Object.fromEntries(STEP_IDS.map((id) => [id, ''])) as Record<StepId, string>;
}
export function newRow(id: string): TriageRow {
  return {
    id,
    revision: 1,
    need_ref: '',
    source_refs: [],
    user_request: '',
    target_action: 'unknown',
    route: 'retrieval_generation',
    rationale: '',
    final_authority: 'unknown',
    confirmation_point: '',
    tool_assumptions: [],
    unresolved: [],
    execution_support: 'unknown',
  };
}
/** The server remains authoritative. Increment a row only if its declared choices changed. */
export function nextDesign(draft: AipmDesign, saved: AipmDesign | null): AipmDesign {
  const compare = ({ revision: _r, execution_support: _s, ...value }: TriageRow) =>
    JSON.stringify(value);
  return {
    ...structuredClone(draft),
    revision: (saved?.revision ?? 0) + 1,
    rows: (draft.rows ?? []).map((row) => {
      const previous = saved?.rows?.find((r) => r.id === row.id);
      return {
        ...row,
        revision: previous
          ? (previous.revision ?? 1) + Number(compare(row) !== compare(previous))
          : 1,
        execution_support: 'unknown',
      };
    }),
  };
}
export function visibleFeedback(
  items: ProcessFeedback[],
  savedRef: ObjectRef | null,
  dirty: boolean,
) {
  return items.map((item) => ({
    ...item,
    stale: !!item.stale || dirty || !sameRef(item.input_ref, savedRef),
  }));
}
export type DiagramLane = {
  rowId: string;
  route: TriageRow['route'];
  request: string;
  nodes: string[];
  status: string;
  sourceRefs: TriageRow['source_refs'];
};
/** Fixed structure, always a proposed design. Actual settings are rendered independently. */
export function diagram(design: AipmDesign, language: Language): DiagramLane[] {
  const t = (zh: string, en: string) => text(language, zh, en);
  return (design.rows ?? []).map((row) => {
    let nodes: string[];
    switch (row.route) {
      case 'deterministic':
        nodes = [
          t('已确认输入', 'Confirmed inputs'),
          t('规则与校验', 'Rules and validation'),
          t('计算或检查结果', 'Calculation or check'),
        ];
        break;
      case 'retrieval_generation':
        nodes = [
          t('公开资料', 'Public sources'),
          t('索引与检索', 'Index and retrieval'),
          t('有出处的回答', 'Cited answer'),
        ];
        break;
      case 'agent_confirmation':
        nodes = [
          t('整理与拟稿', 'Organize and draft'),
          ...(row.tool_assumptions?.length
            ? row.tool_assumptions
            : [t('待核对的工具', 'Tools to confirm')]),
          row.confirmation_point || t('待明确确认人和时点', 'Name who confirms and when'),
        ];
        break;
      case 'human':
        nodes = [
          t('请求与依据', 'Request and evidence'),
          row.confirmation_point || t('有权限的接手人', 'Authorized owner'),
          t('人工处理记录', 'Human action record'),
        ];
        break;
    }
    return {
      rowId: row.id,
      route: row.route,
      request: row.user_request || t('未命名需求', 'Untitled need'),
      nodes,
      sourceRefs: row.source_refs,
      status:
        row.execution_support === 'supported'
          ? t('已有受支持路径，未在此执行', 'Supported path; not executed here')
          : row.execution_support === 'plan_only'
            ? t('仅方案，尚无执行能力', 'Proposal only; execution unavailable')
            : t('执行能力待核对', 'Execution support unknown'),
    };
  });
}
export function designSummary(
  design: AipmDesign,
  language: Language,
): { boundary: string; solution: string } {
  const lanes = diagram(design, language);
  return {
    boundary: lanes
      .map((lane) => `${lane.request}\n${lane.nodes.join(' → ')}\n${lane.status}`)
      .join('\n\n'),
    solution: [
      design.solution?.selected_approach,
      design.solution?.rationale,
      design.solution?.alternative,
      ...(design.solution?.dependencies ?? []),
      text(
        language,
        `来源：需求与方案第 ${design.revision} 版；保存方案不应用实际设置。`,
        `Source: needs and design version ${design.revision}; saving a design does not apply settings.`,
      ),
    ]
      .filter(Boolean)
      .join('\n'),
  };
}
const choices = ({ revision: _r, execution_support: _s, ...value }: TriageRow) =>
  JSON.stringify(value);
/** A row whose declared choices differ from the saved version invalidates that row's feedback. */
export function rowChanged(row: TriageRow | undefined, saved: AipmDesign | null) {
  const previous = saved?.rows?.find((r) => r.id === row?.id);
  return !row || !previous || choices(row) !== choices(previous);
}
export function designChanged(draft: AipmDesign, saved: AipmDesign | null) {
  const strip = (d: AipmDesign) =>
    JSON.stringify({ ...d, revision: 0, rows: (d.rows ?? []).map(choices) });
  return !saved || strip(draft) !== strip(saved);
}
/** Host write results are wrapped differently per adapter; find the first ref of a kind. */
export function findRef(value: unknown, kind: string, depth = 0): ObjectRef | null {
  if (!value || typeof value !== 'object' || depth > 5) return null;
  const v = value as Record<string, unknown>;
  if (v.kind === kind && typeof v.object_id === 'string' && typeof v.version === 'number')
    return v as unknown as ObjectRef;
  for (const child of Object.values(v)) {
    const found = findRef(child, kind, depth + 1);
    if (found) return found;
  }
  return null;
}
export function failure(value: unknown): string | null {
  const v = value as { status?: string; result?: { code?: string; message?: string } } | null;
  return v && typeof v === 'object' && v.status && v.status !== 'confirmed'
    ? v.result?.code || v.result?.message || v.status
    : null;
}

/** Steps this panel edits; assurance belongs to L3's desk and decision to delivery. */
export const DESIGN_STEPS = ['business', 'stakeholders', 'need', 'boundary', 'solution'] as const;
export type DesignStep = (typeof DESIGN_STEPS)[number];
export const isDesignStep = (id: StepId): id is DesignStep =>
  (DESIGN_STEPS as readonly string[]).includes(id);
export const nextStep = (id: StepId): StepId | null => STEP_IDS[STEP_IDS.indexOf(id) + 1] ?? null;

/** Mirror of L4's AipmDesignDraft (types.py) until apps/web/src/aipm/types.ts carries it. */
export type AgentDraft = Pick<
  AipmDesign,
  'business' | 'stakeholders' | 'needs' | 'rows' | 'solution'
> & {
  id: string;
  revision: number;
  status: 'pending_owner_review' | 'adopted' | 'dismissed';
  author?: { kind: string; id?: string };
  note?: string | null;
  prd_sections?: Partial<Record<StepId, string>>;
};
export function draftSteps(
  draft: Pick<AipmDesign, 'business' | 'stakeholders' | 'needs' | 'rows' | 'solution'>,
): StepId[] {
  const steps: StepId[] = [];
  if (draft.business) steps.push('business');
  if (draft.stakeholders?.length) steps.push('stakeholders');
  if (draft.needs?.length) steps.push('need');
  if (draft.rows?.length) steps.push('boundary');
  if (draft.solution) steps.push('solution');
  return steps;
}
/** Adopting replaces single answers and upserts list items by id; row revisions are recomputed on save. */
export function mergeDraft(design: AipmDesign, draft: AgentDraft): AipmDesign {
  const upsert = <T extends { id: string }>(mine: readonly T[] = [], theirs: readonly T[] = []) => [
    ...mine.map((item) => theirs.find((t) => t.id === item.id) ?? item),
    ...theirs.filter((t) => !mine.some((item) => item.id === t.id)),
  ];
  return {
    ...design,
    business: draft.business ?? design.business,
    stakeholders: upsert(design.stakeholders, draft.stakeholders),
    needs: upsert(design.needs, draft.needs),
    rows: upsert(design.rows, draft.rows).map((row) => ({
      ...row,
      execution_support: 'unknown' as const,
    })),
    solution: draft.solution ?? design.solution,
  };
}

/** What the card after a save says. Only server rule findings may say right or wrong;
 * missing is a plain field check; anything rules cannot judge is said to be pending. */
export type SectionCheck = {
  right: string[];
  wrong: ProcessFeedback[];
  missing: string[];
  pending: string | null;
};
export function sectionCheck(
  step: DesignStep,
  design: AipmDesign,
  feedback: ProcessFeedback[],
  language: Language,
  rowId?: string,
): SectionCheck {
  const t = (zh: string, en: string) => text(language, zh, en);
  const blank = (v?: string | null) => !v?.trim();
  const out: SectionCheck = {
    right: [],
    wrong: [],
    missing: [],
    pending: t(
      '这部分规则判不了，已记录，语义待核对。',
      'Rules cannot judge this part. Recorded; meaning still to be checked.',
    ),
  };
  const add = (cond: boolean, zh: string, en: string) => {
    if (cond) out.missing.push(t(zh, en));
  };
  const here = feedback.filter(
    (f) => f.step_id === step && (!rowId || f.section_or_row_id === rowId),
  );
  out.wrong = here.filter((f) => f.finding === 'violation');
  out.missing.push(...here.filter((f) => f.finding === 'improve').map((f) => f.message));
  switch (step) {
    case 'business': {
      const b = design.business;
      add(
        !b || b.audience === 'unknown',
        '还没选这个助手服务谁。',
        'You have not chosen who the assistant serves.',
      );
      add(
        blank(b?.offering_explanation),
        '还没写公司靠什么业务服务客户。',
        'You have not said how the company serves customers.',
      );
      add(
        blank(b?.task_goal),
        '还没写这次要帮谁解决什么。',
        'You have not said whom this pilot helps, with what.',
      );
      add(
        !!b && !b.source_refs?.length,
        '还没引用原文；有人问起时不好核对。',
        'No passage cited yet, so it is hard to check later.',
      );
      break;
    }
    case 'stakeholders': {
      const list = design.stakeholders ?? [];
      add(
        list.length < 2,
        '至少写两位：用它的人和批准的人。',
        'Name at least two: who uses it and who approves.',
      );
      add(
        list.length > 0 && !list.some((s) => s.relationships?.includes('approver')),
        '还没写谁有批准权。',
        'Nobody is marked as the approver yet.',
      );
      add(
        list.some((s) => blank(s.responsibility)),
        '有相关方还没写职责。',
        'Some stakeholders have no responsibility yet.',
      );
      break;
    }
    case 'need': {
      const list = design.needs ?? [];
      add(
        !list.length || list.some((n) => blank(n.problem)),
        '还没写要解决的问题。',
        'The problem is not written yet.',
      );
      add(
        list.some((n) => blank(n.counterevidence_or_unknown)),
        '还没写什么事实会推翻它。',
        'What would disprove it is not written yet.',
      );
      add(
        list.some((n) => blank(n.next_validation)),
        '还没写下一步怎样核对。',
        'How you will check it next is not written yet.',
      );
      break;
    }
    case 'boundary': {
      const row = design.rows?.find((r) => r.id === rowId);
      if (!row) break;
      add(
        row.target_action === 'unknown',
        '还没选这项请求要做什么。',
        'The action is not chosen yet.',
      );
      add(
        row.final_authority === 'unknown',
        '还没选最后谁说了算。',
        'Who has the final say is not chosen yet.',
      );
      add(
        (row.route === 'agent_confirmation' || row.route === 'human') &&
          blank(row.confirmation_point),
        row.route === 'human' ? '还没写交给谁处理。' : '还没写谁在什么时候确认。',
        row.route === 'human'
          ? 'You have not said who takes it.'
          : 'You have not said who confirms, and when.',
      );
      if (row.execution_support === 'unknown')
        add(
          true,
          '这项需求没有匹配的核实依据，请补充来源与权限。',
          'No verified basis matches this need. Add sources and authority.',
        );
      else if (!out.wrong.length)
        out.right.push(
          t('按当前权限，没有发现越权。', 'No action beyond current authority was found.'),
        );
      out.pending = t(
        '这样分是否最好，规则判不了；已记录，语义待核对。',
        'Whether this split is the best one is beyond the rules. Recorded; to be checked.',
      );
      break;
    }
    case 'solution': {
      const s = design.solution;
      add(
        blank(s?.selected_approach),
        '还没写选定的做法。',
        'The chosen approach is not written yet.',
      );
      add(blank(s?.rationale), '还没写理由。', 'The rationale is not written yet.');
      add(
        blank(s?.alternative),
        '还没写认真考虑过的替代做法。',
        'No serious alternative is written yet.',
      );
      break;
    }
  }
  return out;
}

/** PRD text for a work version, built from what was actually saved. */
export function prdFromDesign(
  design: AipmDesign,
  title: (id: StepId) => string,
  language: Language,
) {
  const t = (zh: string, en: string) => text(language, zh, en);
  const lines: Partial<Record<StepId, string[]>> = {
    business: design.business
      ? [design.business.offering_explanation, design.business.task_goal]
      : [],
    stakeholders: (design.stakeholders ?? []).map((s) => `${s.name_or_role}: ${s.responsibility}`),
    need: (design.needs ?? []).flatMap((n) => [
      n.problem,
      n.counterevidence_or_unknown,
      n.next_validation,
    ]),
    boundary: [designSummary(design, language).boundary],
    solution: [designSummary(design, language).solution],
  };
  return STEP_IDS.map(
    (id) =>
      `## ${title(id)}\n\n${(lines[id] ?? []).filter(Boolean).join('\n') || t('（未填写）', '(Not written)')}`,
  ).join('\n\n');
}
