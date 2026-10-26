import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import type {
  AipmDesign,
  AipmProgress,
  BusinessDeclaration,
  EvidenceRefV2,
  NeedDeclaration,
  ObjectRef,
  ProcessFeedback,
  StakeholderDeclaration,
  StepId,
  TriageRow,
} from '../../aipm/types';
import { STEP_IDS } from '../../aipm/types';
import {
  ACTIONS,
  AUDIENCES,
  AUTHORITIES,
  BASIS,
  CLAIMS,
  copy,
  METRICS,
  RELATIONSHIPS,
  ROUTE_IDS,
  STARTER_NEEDS,
} from './copy';
import {
  type AgentDraft,
  type DesignStep,
  designChanged,
  diagram,
  draftSteps,
  failure,
  findRef,
  isDesignStep,
  type Language,
  mergeDraft,
  newRow,
  nextDesign,
  nextStep,
  rowChanged,
  type SectionCheck,
  sectionCheck,
} from './model';
import './desk.css';

export const DESIGN_ID = 'aipm-design';
export type DesignRead = { ref: ObjectRef; design: AipmDesign; feedback: ProcessFeedback[] };
export type DraftItem = { ref: ObjectRef; draft: AgentDraft };
/** L4's AipmClient.listDrafts (GET /drafts, pending only); absent clients show no drafts.
 * Typed loosely so it merges with L4's own DraftPage type without a clash. */
type DraftClient = { listDrafts?: () => Promise<unknown> };
type Host = AipmHost<unknown, AipmClient & DraftClient>;
type Copy = ReturnType<typeof copy>;
type Saved = { step: StepId; rowId?: string } | null;

const blank = (sessionId: string): AipmDesign => ({
  id: DESIGN_ID,
  session_id: sessionId,
  revision: 0,
  rows: [],
});
// The gateway transport keeps the server's code and status on the error, not in its message.
const notFound = (error: unknown) =>
  (error as { code?: string })?.code === 'object_not_found' ||
  (error as { status?: number })?.status === 404 ||
  /object_not_found|404/.test(String((error as Error)?.message ?? error));
const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}`;

export function DesignDesk({
  host,
  step,
  initial,
  drafts: initialDrafts = [],
}: {
  host: Host;
  /** Open this section; otherwise the server's focus step is used. */
  step?: StepId;
  initial?: DesignRead | null;
  drafts?: DraftItem[];
}) {
  const context = host.getSessionContext();
  const language: Language = context?.workLanguage === 'en' ? 'en' : 'zh';
  const c = copy(language);
  const readOnly = !!context?.readOnly;
  const [open, setOpen] = useState<StepId>(step ?? 'business');
  const [saved, setSaved] = useState<DesignRead | null>(initial ?? null);
  const [draft, setDraft] = useState<AipmDesign>(() =>
    structuredClone(initial?.design ?? blank(context?.sessionId ?? '')),
  );
  const [drafts, setDrafts] = useState<DraftItem[]>(initialDrafts);
  const [adopting, setAdopting] = useState<AgentDraft | null>(null);
  const [justSaved, setJustSaved] = useState<Saved>(null);
  const [loading, setLoading] = useState(initial === undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<'' | 'read' | 'save' | 'conflict' | 'draft'>('');

  const load = useCallback(async () => {
    const client = host.getClient();
    if (!client || !host.getSessionContext()) return setLoading(false);
    try {
      const read = await client.readDesign<DesignRead>(DESIGN_ID);
      setSaved(read);
      setDraft(structuredClone(read.design));
    } catch (e) {
      if (!notFound(e)) setError('read');
    }
    try {
      const listed = (await client.listDrafts?.()) as { items?: DraftItem[] } | undefined;
      setDrafts(
        (listed?.items ?? [])
          .filter((d) => d.draft.status === 'pending_owner_review')
          // The server checks expected_revision against the draft head, i.e. ref.version.
          .map((d) => ({ ...d, draft: { ...d.draft, revision: d.ref.version } })),
      );
    } catch {
      // Drafts are optional; the learner's own work stays usable without them.
    }
    setLoading(false);
  }, [host]);
  const preloaded = initial !== undefined;
  useEffect(() => {
    if (!preloaded) void load();
  }, [load, preloaded]);
  useEffect(() => {
    if (step) return;
    host
      .readProgress()
      .then((p) => {
        const focus = (p as AipmProgress | null)?.focus_step;
        if (focus) setOpen(focus);
      })
      .catch(() => {});
  }, [host, step]);

  const save = async (design: AipmDesign, adopt: AgentDraft | null, at: Saved) => {
    setBusy(true);
    setError('');
    const next = nextDesign(design, saved?.design ?? null);
    try {
      const result = await host.command('aipm.design.save', {
        design: next,
        expected_revision: saved?.design.revision ?? 0,
      });
      const failed = failure(result);
      if (failed) throw new Error(failed);
      if (adopt) {
        const ref = findRef(result, 'aipm_design') ?? {
          session_id: next.session_id,
          kind: 'aipm_design',
          object_id: DESIGN_ID,
          version: next.revision,
        };
        const resolved = await host.command('aipm.design_drafts.resolve', {
          draft_id: adopt.id,
          expected_revision: adopt.revision,
          status: 'adopted',
          adopted_design_ref: ref,
        });
        if (failure(resolved)) setError('draft');
      }
      setAdopting(null);
      setJustSaved(at);
      await load();
    } catch (e) {
      setError(/conflict/.test(String((e as Error).message)) ? 'conflict' : 'save');
    } finally {
      setBusy(false);
    }
  };
  const decline = async (d: AgentDraft) => {
    try {
      const result = await host.command('aipm.design_drafts.resolve', {
        draft_id: d.id,
        expected_revision: d.revision,
        status: 'dismissed',
      });
      if (failure(result)) throw new Error('draft');
      setDrafts(drafts.filter((item) => item.draft.id !== d.id));
    } catch {
      setError('draft');
    }
  };
  const goTo = (target: StepId) => {
    setJustSaved(null);
    void host
      .command('aipm.focus.set', { step_id: target })
      .then(() => host.refresh())
      .catch(() => {});
    if (target === 'assurance') host.openFeature('evaluation');
    else setOpen(target);
  };

  const errors = {
    read: c.t('暂时读不到已保存的内容。', 'Could not read what you saved.'),
    save: c.t('没有保存成功，内容仍在这里。', 'Not saved. Your edits are still here.'),
    conflict: c.t(
      '内容已在别处更新，请重新打开后再改。',
      'This changed elsewhere. Reopen before editing.',
    ),
    draft: c.t('Agent 草稿的状态没有更新成功。', 'The agent draft status was not updated.'),
  };
  const filled = (id: StepId) => {
    const d = saved?.design;
    return !!d && draftSteps(d).includes(id);
  };
  const openIndex = STEP_IDS.indexOf(open);
  const later = (id: StepId) =>
    id === 'assurance'
      ? c.t('在评测台完成', 'Done in the evaluation desk')
      : id === 'decision'
        ? c.t('交付时完成', 'Done when you deliver')
        : filled(id)
          ? c.t('已填', 'Written')
          : STEP_IDS.indexOf(id) > openIndex
            ? c.t('后面几步再填', 'For a later step')
            : c.t('可以回来补', 'You can come back to it');

  return (
    <section className="aipm-design" lang={language} aria-label={c.t('PRD 七节', 'PRD sections')}>
      <header className="aipm-design__head">
        <p className="aipm-design__eyebrow">
          {c.t(`PRD · 第 ${openIndex + 1} 节，共 7 节`, `PRD · section ${openIndex + 1} of 7`)}
          {saved
            ? ` · ${c.t(`已保存第 ${saved.design.revision} 版`, `saved version ${saved.design.revision}`)}`
            : ''}
        </p>
        <h2>{c.question(open)}</h2>
      </header>
      {loading ? (
        <p className="aipm-design__muted">{c.t('正在读取…', 'Loading…')}</p>
      ) : (
        <ol className="aipm-design__sections">
          {STEP_IDS.map((id, index) =>
            id === open ? (
              <li key={id} className="aipm-design__open">
                <p className="aipm-design__why">
                  <span>{c.t('为什么写', 'Why')}</span>
                  {c.why(id)}
                </p>
                {c.example(id).length > 0 && (
                  <details className="aipm-design__example">
                    <summary>
                      {c.t('看一个示例（示例，不是标准答案）', 'See an example (not the answer)')}
                    </summary>
                    <ul>
                      {c.example(id).map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </details>
                )}
                {drafts
                  .filter((d) => draftSteps(d.draft).includes(id))
                  .map((d) => (
                    <DraftCard
                      key={d.draft.id}
                      c={c}
                      item={d.draft}
                      disabled={readOnly || busy}
                      onAdopt={() => {
                        const merged = mergeDraft(draft, d.draft);
                        setDraft(merged);
                        void save(merged, d.draft, { step: id });
                      }}
                      onEdit={() => {
                        setDraft(mergeDraft(draft, d.draft));
                        setAdopting(d.draft);
                        setDrafts(drafts.filter((x) => x.draft.id !== d.draft.id));
                      }}
                      onDecline={() => void decline(d.draft)}
                    />
                  ))}
                {adopting && draftSteps(adopting).includes(id) && (
                  <p className="aipm-design__notice">
                    {c.t(
                      '已载入你的 Agent 草稿。改完点保存，才算你的内容。',
                      'Your agent’s draft is loaded. It becomes yours only when you save.',
                    )}
                  </p>
                )}
                {isDesignStep(id) ? (
                  <Section
                    id={id}
                    c={c}
                    host={host}
                    language={language}
                    draft={draft}
                    setDraft={(d) => {
                      setDraft(d);
                      setJustSaved(null);
                    }}
                    saved={saved}
                    justSaved={justSaved}
                    busy={busy}
                    readOnly={readOnly}
                    onSave={(at) => void save(draft, adopting, at)}
                    onNext={goTo}
                  />
                ) : id === 'assurance' ? (
                  <button
                    type="button"
                    className="btn primary"
                    onClick={() => host.openFeature('evaluation')}
                  >
                    {c.t('打开评测台', 'Open the evaluation desk')}
                  </button>
                ) : null}
                <LinkWork c={c} host={host} step={id} readOnly={readOnly} />
                {error && (
                  <p role="alert" className="aipm-design__notice">
                    {errors[error]}
                  </p>
                )}
              </li>
            ) : (
              <li key={id}>
                <button
                  type="button"
                  className="aipm-design__collapsed"
                  onClick={() => setOpen(id)}
                >
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <strong>{c.section(id)}</strong>
                  <small>{later(id)}</small>
                </button>
              </li>
            ),
          )}
        </ol>
      )}
    </section>
  );
}

export type SectionProps = {
  id: DesignStep;
  c: Copy;
  host: Host;
  language: Language;
  draft: AipmDesign;
  setDraft: (d: AipmDesign) => void;
  saved: DesignRead | null;
  justSaved: Saved;
  busy: boolean;
  readOnly: boolean;
  onSave: (at: Saved) => void;
  onNext: (step: StepId) => void;
};

function Section(p: SectionProps) {
  const { id, c, draft, saved } = p;
  if (id === 'boundary') return <Triage {...p} />;
  const dirty = !saved || designChanged(draft, saved.design);
  const next = nextStep(id);
  const body = {
    business: <Business {...p} />,
    stakeholders: <Stakeholders {...p} />,
    need: <Needs {...p} />,
    solution: <Solution {...p} />,
  }[id];
  return (
    <>
      <fieldset className="aipm-design__form" disabled={p.readOnly}>
        {body}
      </fieldset>
      <div className="aipm-design__actions">
        <button
          type="button"
          className="btn primary"
          disabled={p.readOnly || p.busy || !dirty}
          onClick={() => p.onSave({ step: id })}
        >
          {p.busy ? c.t('保存中…', 'Saving…') : c.t('保存这一节', 'Save this section')}
        </button>
        {dirty && saved && (
          <span className="aipm-design__muted">
            {c.t('有改动，保存后按新内容重新核对。', 'Edited. Saving checks the new version.')}
          </span>
        )}
      </div>
      {saved && !dirty && (p.justSaved?.step === id || draftSteps(saved.design).includes(id)) && (
        <CheckCard
          c={c}
          host={p.host}
          check={sectionCheck(id, saved.design, saved.feedback, p.language)}
          next={next ? { label: c.section(next), go: () => p.onNext(next) } : null}
        />
      )}
    </>
  );
}

function Chips<T extends string>({
  label,
  options,
  value,
  onChange,
  c,
  multiple,
}: {
  label: string;
  options: Record<T, readonly [string, string]>;
  value: string | readonly string[];
  onChange: (v: T) => void;
  c: Copy;
  multiple?: boolean;
}) {
  const chosen = (k: T) => (typeof value === 'string' ? value === k : value.includes(k));
  return (
    <fieldset className="aipm-design__chips">
      <legend>{label}</legend>
      {(Object.keys(options) as T[]).map((k) => (
        <label key={k}>
          <input
            type={multiple ? 'checkbox' : 'radio'}
            checked={chosen(k)}
            onChange={() => onChange(k)}
          />
          {c.label(options[k])}
        </label>
      ))}
    </fieldset>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="aipm-design__field">
      <span>{label}</span>
      <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Business({ c, host, draft, setDraft }: SectionProps) {
  const b: BusinessDeclaration = draft.business ?? {
    audience: 'unknown',
    offering_explanation: '',
    task_goal: '',
    source_refs: [],
  };
  const set = (patch: Partial<BusinessDeclaration>) =>
    setDraft({ ...draft, business: { ...b, ...patch } });
  return (
    <>
      <Chips
        c={c}
        label={c.t('这个助手服务谁？', 'Who does the assistant serve?')}
        options={AUDIENCES}
        value={b.audience}
        onChange={(audience) => set({ audience })}
      />
      <Field
        label={c.t(
          '公司靠什么业务服务客户？一句话',
          'How does the company serve customers? One line',
        )}
        value={b.offering_explanation}
        onChange={(offering_explanation) => set({ offering_explanation })}
      />
      <Field
        label={c.t(
          '这次要帮谁、解决什么？一句话',
          'Whom does this pilot help, with what? One line',
        )}
        value={b.task_goal}
        onChange={(task_goal) => set({ task_goal })}
      />
      <Evidence
        c={c}
        host={host}
        refs={b.source_refs ?? []}
        onChange={(source_refs) => set({ source_refs })}
      />
    </>
  );
}

function Stakeholders({ c, draft, setDraft }: SectionProps) {
  const list = draft.stakeholders?.length ? draft.stakeholders : [emptyStakeholder(newId('s'))];
  const set = (sid: string, patch: Partial<StakeholderDeclaration>) =>
    setDraft({ ...draft, stakeholders: list.map((s) => (s.id === sid ? { ...s, ...patch } : s)) });
  return (
    <>
      {list.map((s, i) => (
        <div key={s.id} className="aipm-design__item">
          <Field
            label={c.t(`第 ${i + 1} 位：角色或人`, `Person ${i + 1}: role or name`)}
            value={s.name_or_role}
            onChange={(name_or_role) => set(s.id, { name_or_role })}
          />
          <Chips
            c={c}
            multiple
            label={c.t('和这个助手的关系（可多选）', 'Relationship to the assistant (any)')}
            options={RELATIONSHIPS}
            value={s.relationships ?? []}
            onChange={(r) =>
              set(s.id, {
                relationships: s.relationships?.includes(r)
                  ? s.relationships.filter((x) => x !== r)
                  : [...(s.relationships ?? []), r],
              })
            }
          />
          <Field
            label={c.t('负责什么', 'What they are responsible for')}
            value={s.responsibility}
            onChange={(responsibility) => set(s.id, { responsibility })}
          />
          <Chips
            c={c}
            label={c.t('依据', 'Basis')}
            options={BASIS}
            value={s.fact_or_hypothesis}
            onChange={(fact_or_hypothesis) => set(s.id, { fact_or_hypothesis })}
          />
        </div>
      ))}
      <button
        type="button"
        className="btn quiet small"
        onClick={() =>
          setDraft({ ...draft, stakeholders: [...list, emptyStakeholder(newId('s'))] })
        }
      >
        + {c.t('再加一位', 'Add another')}
      </button>
    </>
  );
}
const emptyStakeholder = (id: string): StakeholderDeclaration => ({
  id,
  name_or_role: '',
  relationships: [],
  responsibility: '',
  fact_or_hypothesis: 'unknown',
});

function Needs({ c, draft, setDraft }: SectionProps) {
  const list = draft.needs?.length ? draft.needs : [emptyNeed(newId('n'))];
  const set = (nid: string, patch: Partial<NeedDeclaration>) =>
    setDraft({ ...draft, needs: list.map((n) => (n.id === nid ? { ...n, ...patch } : n)) });
  return (
    <>
      {list.map((n) => (
        <div key={n.id} className="aipm-design__item">
          <Field
            label={c.t('要解决的问题', 'The problem')}
            value={n.problem}
            onChange={(problem) => set(n.id, { problem })}
          />
          <Chips
            c={c}
            label={c.t('现在是', 'It is currently')}
            options={CLAIMS}
            value={n.claim_status}
            onChange={(claim_status) => set(n.id, { claim_status })}
          />
          <Field
            label={c.t('什么事实会推翻它？', 'What fact would disprove it?')}
            value={n.counterevidence_or_unknown}
            onChange={(counterevidence_or_unknown) => set(n.id, { counterevidence_or_unknown })}
          />
          <Field
            label={c.t('下一步怎样核对？', 'How will you check it next?')}
            value={n.next_validation}
            onChange={(next_validation) => set(n.id, { next_validation })}
          />
          <details className="aipm-design__more" open={!!n.metric}>
            <summary>{c.t('加一个成功指标（可选）', 'Add a success metric (optional)')}</summary>
            <Chips
              c={c}
              label={c.t('指标衡量的是', 'The metric measures')}
              options={METRICS}
              value={n.metric?.kind ?? ''}
              onChange={(kind) => set(n.id, { metric: { ...emptyMetric, ...n.metric, kind } })}
            />
            <Field
              label={c.t('数据来自哪个字段', 'Source field')}
              placeholder="duration_minutes"
              value={n.metric?.source_field ?? ''}
              onChange={(source_field) =>
                set(n.id, { metric: { ...emptyMetric, ...n.metric, source_field } })
              }
            />
          </details>
        </div>
      ))}
    </>
  );
}
const emptyNeed = (id: string): NeedDeclaration => ({
  id,
  problem: '',
  claim_status: 'hypothesis',
  counterevidence_or_unknown: '',
  next_validation: '',
});
const emptyMetric = {
  kind: 'other' as const,
  source_field: '',
  unit: '',
  population: '',
  window: '',
  formula_description: '',
  claimed_interpretation: '',
};

export function Triage(p: SectionProps) {
  const { c, draft, setDraft, saved, language } = p;
  const rows = draft.rows ?? [];
  const [openRow, setOpenRow] = useState<string | null>(
    rows.find((r) => rowChanged(r, saved?.design ?? null))?.id ?? rows[0]?.id ?? null,
  );
  const row = rows.find((r) => r.id === openRow);
  const update = (patch: Partial<TriageRow>) =>
    setDraft({ ...draft, rows: rows.map((r) => (r.id === openRow ? { ...r, ...patch } : r)) });
  const add = (need?: (typeof STARTER_NEEDS)[number]) => {
    const id = newId('row');
    setDraft({
      ...draft,
      rows: [
        ...rows,
        { ...newRow(id), need_ref: need?.id ?? '', user_request: need ? c.starter(need) : '' },
      ],
    });
    setOpenRow(id);
  };
  const remaining = STARTER_NEEDS.filter((n) => !rows.some((r) => r.need_ref === n.id));
  const verdict = (r: TriageRow) => {
    if (rowChanged(r, saved?.design ?? null)) return c.t('未保存', 'Not saved');
    if (saved?.feedback.some((f) => f.section_or_row_id === r.id && f.finding === 'violation'))
      return c.t('有越权', 'Beyond authority');
    return c.t('已保存', 'Saved');
  };
  const changed = row ? rowChanged(row, saved?.design ?? null) : false;
  const savedRow = saved?.design.rows?.find((r) => r.id === row?.id);
  const next = remaining[0];
  return (
    <>
      {rows.length > 0 && (
        <ul className="aipm-design__rows">
          {rows.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                aria-pressed={r.id === openRow}
                onClick={() => setOpenRow(r.id)}
              >
                <strong>{r.user_request || c.t('未命名请求', 'Untitled request')}</strong>
                <small>{verdict(r)}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {row ? (
        <fieldset className="aipm-design__form" disabled={p.readOnly}>
          <Field
            label={c.t('用户的请求', 'The user’s request')}
            value={row.user_request}
            placeholder={c.t('例如：帮我把报销单批了', 'e.g. Approve my expense claim')}
            onChange={(user_request) => update({ user_request })}
          />
          <Chips
            c={c}
            label={c.t('1 · 这项请求要做什么？', '1 · What does this request need done?')}
            options={withoutUnknown(ACTIONS)}
            value={row.target_action}
            onChange={(target_action) => update({ target_action })}
          />
          {row.target_action !== 'unknown' && (
            <>
              <fieldset className="aipm-design__routes">
                <legend>{c.t('2 · 交给哪种方式处理？', '2 · How should it be handled?')}</legend>
                {ROUTE_IDS.map((route) => (
                  <label key={route}>
                    <input
                      type="radio"
                      checked={row.route === route}
                      onChange={() => update({ route })}
                    />
                    <strong>{c.route(route)}</strong>
                    <small>{c.routeHelp(route)}</small>
                  </label>
                ))}
              </fieldset>
              <Chips
                c={c}
                label={c.t('3 · 最后谁说了算？', '3 · Who has the final say?')}
                options={withoutUnknown(AUTHORITIES)}
                value={row.final_authority}
                onChange={(final_authority) => update({ final_authority })}
              />
              {(row.route === 'agent_confirmation' || row.route === 'human') && (
                <Field
                  label={
                    row.route === 'human'
                      ? c.t('交给谁处理？', 'Who takes it?')
                      : c.t('谁在什么时候确认？', 'Who confirms, and when?')
                  }
                  value={row.confirmation_point ?? ''}
                  onChange={(confirmation_point) => update({ confirmation_point })}
                />
              )}
              <details className="aipm-design__more">
                <summary>
                  {c.t('补充理由与依据（可选）', 'Reasoning and sources (optional)')}
                </summary>
                <label className="aipm-design__field">
                  <span>{c.t('为什么这样分', 'Why this split')}</span>
                  <textarea
                    rows={2}
                    value={row.rationale}
                    onChange={(e) => update({ rationale: e.target.value })}
                  />
                </label>
                {row.route === 'agent_confirmation' && (
                  <Field
                    label={c.t('需要的工具（逗号分隔）', 'Tools needed (comma separated)')}
                    value={(row.tool_assumptions ?? []).join(', ')}
                    onChange={(v) =>
                      update({
                        tool_assumptions: v
                          .split(/[,，]/)
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                )}
                <Evidence
                  c={c}
                  host={p.host}
                  refs={row.source_refs ?? []}
                  onChange={(source_refs) => update({ source_refs })}
                />
              </details>
            </>
          )}
          <div className="aipm-design__actions">
            <button
              type="button"
              className="btn primary"
              disabled={p.readOnly || p.busy || !changed}
              onClick={() => p.onSave({ step: 'boundary', rowId: row.id })}
            >
              {p.busy ? c.t('保存中…', 'Saving…') : c.t('保存这一行', 'Save this row')}
            </button>
            {savedRow && (
              <span className="aipm-design__muted">{support(c, savedRow.execution_support)}</span>
            )}
          </div>
          {saved && savedRow && !changed && (
            <CheckCard
              c={c}
              host={p.host}
              check={sectionCheck('boundary', saved.design, saved.feedback, language, row.id)}
              next={
                next
                  ? { label: c.starter(next), go: () => add(next) }
                  : { label: c.section('solution'), go: () => p.onNext('solution') }
              }
            />
          )}
        </fieldset>
      ) : (
        <div className="aipm-design__start">
          <p className="aipm-design__muted">
            {c.t('一项一项来：先选一项请求。', 'One at a time: pick a request to start.')}
          </p>
          {remaining.map((n) => (
            <button key={n.id} type="button" className="btn quiet small" onClick={() => add(n)}>
              + {c.starter(n)}
            </button>
          ))}
        </div>
      )}
      {row && !p.readOnly && (
        <button type="button" className="btn quiet small" onClick={() => add()}>
          + {c.t('再拆一项自己的请求', 'Add a request of your own')}
        </button>
      )}
    </>
  );
}
const withoutUnknown = <T extends string>(o: Record<T, readonly [string, string]>) =>
  Object.fromEntries(Object.entries(o).filter(([k]) => k !== 'unknown')) as Record<
    Exclude<T, 'unknown'>,
    readonly [string, string]
  >;
const support = (c: Copy, value?: TriageRow['execution_support']) =>
  value === 'supported'
    ? c.t('本局已有受支持路径', 'A supported path exists here')
    : value === 'plan_only'
      ? c.t('仅方案：本局没有执行能力', 'Proposal only: no execution here')
      : c.t('执行能力待核对', 'Execution support not yet checked');

function Solution({ c, host, draft, setDraft, saved, language }: SectionProps) {
  const s = draft.solution ?? {
    selected_approach: '',
    rationale: '',
    alternative: '',
    dependencies: [],
  };
  const set = (patch: Partial<typeof s>) => setDraft({ ...draft, solution: { ...s, ...patch } });
  return (
    <>
      <DiagramBlock c={c} host={host} saved={saved} language={language} />
      <Field
        label={c.t('选定的做法', 'Chosen approach')}
        value={s.selected_approach}
        onChange={(selected_approach) => set({ selected_approach })}
      />
      <Field
        label={c.t('为什么选它', 'Why this one')}
        value={s.rationale}
        onChange={(rationale) => set({ rationale })}
      />
      <Field
        label={c.t('认真考虑过的替代做法，以及为什么不选', 'A serious alternative, and why not')}
        value={s.alternative}
        onChange={(alternative) => set({ alternative })}
      />
    </>
  );
}

export function CheckCard({
  c,
  host,
  check,
  next,
}: {
  c: Copy;
  host: Host;
  check: SectionCheck;
  next: { label: string; go: () => void } | null;
}) {
  const group = (title: string, tone: string, items: ReactNode[]) =>
    items.length > 0 && (
      <div className={`aipm-design__check-group is-${tone}`}>
        <p className="aipm-design__eyebrow">{title}</p>
        <ul>{items}</ul>
      </div>
    );
  return (
    <article className="aipm-design__check" aria-live="polite">
      {group(
        c.t('对的', 'Right'),
        'right',
        check.right.map((m) => <li key={m}>{m}</li>),
      )}
      {group(
        c.t('错的', 'Wrong'),
        'wrong',
        check.wrong.map((f) => (
          <li key={f.id}>
            <span className="aipm-design__muted">{c.source(f.source)} · </span>
            {f.message}
            {(f.basis_refs ?? [])
              .filter((r) => r.quote)
              .map((r) => (
                <blockquote key={`${r.kind}:${r.object_id}:${r.version}:${r.span_start ?? ''}`}>
                  <button type="button" onClick={() => void host.getDataHost()?.openReference(r)}>
                    “{r.quote}”
                  </button>
                </blockquote>
              ))}
            {f.next_action && <em>{f.next_action.label}</em>}
          </li>
        )),
      )}
      {group(
        c.t('缺的', 'Missing'),
        'missing',
        check.missing.map((m) => <li key={m}>{m}</li>),
      )}
      {check.pending && <p className="aipm-design__muted">{check.pending}</p>}
      {next && (
        <button type="button" className="btn primary small" onClick={next.go}>
          {c.t('下一步：', 'Next: ')}
          {next.label}
        </button>
      )}
    </article>
  );
}

function DraftCard({
  c,
  item,
  disabled,
  onAdopt,
  onEdit,
  onDecline,
}: {
  c: Copy;
  item: AgentDraft;
  disabled: boolean;
  onAdopt: () => void;
  onEdit: () => void;
  onDecline: () => void;
}) {
  return (
    <article className="aipm-design__draft">
      <p className="aipm-design__eyebrow">
        {c.t('来自你的 Agent · 待你确认', 'From your agent · awaiting you')}
      </p>
      <p>
        {c.t('涉及：', 'Covers: ')}
        {draftSteps(item)
          .map((s) => c.section(s))
          .join(c.t('、', ', '))}
      </p>
      {item.note && <p className="aipm-design__muted">{item.note}</p>}
      <p className="aipm-design__muted">
        {c.t(
          '采用后才算你的内容，也才会核对和计入进度。',
          'It counts, gets checked and shows in progress only after you adopt it.',
        )}
      </p>
      <div className="aipm-design__actions">
        <button type="button" className="btn primary small" disabled={disabled} onClick={onAdopt}>
          {c.t('采用', 'Adopt')}
        </button>
        <button type="button" className="btn quiet small" disabled={disabled} onClick={onEdit}>
          {c.t('修改后再用', 'Edit first')}
        </button>
        <button type="button" className="btn quiet small" disabled={disabled} onClick={onDecline}>
          {c.t('不采用', 'Decline')}
        </button>
      </div>
    </article>
  );
}

function Evidence({
  c,
  host,
  refs,
  onChange,
}: {
  c: Copy;
  host: Host;
  refs: readonly EvidenceRefV2[];
  onChange: (r: EvidenceRefV2[]) => void;
}) {
  const data = host.getDataHost();
  return (
    <button
      type="button"
      className="btn quiet small aipm-design__cite"
      disabled={!data}
      onClick={async () => {
        if (!data) return;
        onChange([...(await data.chooseEvidence({ selected: refs }))]);
      }}
    >
      {refs.length
        ? c.t(
            `已引用 ${refs.length} 处原文`,
            `${refs.length} cited passage${refs.length > 1 ? 's' : ''}`,
          )
        : c.t('引用原文（可选）', 'Cite a source (optional)')}
    </button>
  );
}

/** Any free work item the learner has open can be attached to a section. */
function LinkWork({
  c,
  host,
  step,
  readOnly,
}: {
  c: Copy;
  host: Host;
  step: StepId;
  readOnly: boolean;
}) {
  const [linked, setLinked] = useState<string | null>(null);
  const current = host.getDataHost()?.snapshot().currentProduct ?? null;
  if (!current || readOnly) return null;
  const link = async () => {
    const result = await host.command('aipm.step_links.save', {
      step_id: step,
      product_ref: current,
      section_key: step,
    });
    setLinked(
      failure(result)
        ? c.t('没有关联成功。', 'The link was not saved.')
        : c.t('已关联到这一节。', 'Linked to this section.'),
    );
  };
  return (
    <p className="aipm-design__muted">
      <button
        type="button"
        className="btn quiet small"
        onClick={() =>
          void link().catch(() => setLinked(c.t('没有关联成功。', 'The link was not saved.')))
        }
      >
        {c.t('把当前打开的作品关联到这一节', 'Link the open work item to this section')}
      </button>
      {linked}
    </p>
  );
}

/** The fixed-structure proposal drawn from the saved triage, beside what is actually in effect. */
export function DiagramBlock({
  c,
  host,
  saved,
  language,
}: {
  c: Copy;
  host: Host;
  saved: DesignRead | null;
  language: Language;
}) {
  const lanes = useMemo(() => (saved ? diagram(saved.design, language) : []), [saved, language]);
  return (
    <div className="aipm-design__diagram">
      <div>
        <p className="aipm-design__eyebrow">
          {c.t('拟议方案 · 按已保存的分拣生成', 'Proposed design · drawn from your saved triage')}
        </p>
        {lanes.length ? (
          lanes.map((lane) => (
            <div key={lane.rowId} className="aipm-design__lane">
              <div className="aipm-design__lane-head">
                <strong>{lane.request}</strong>
                <small>
                  {c.route(lane.route)} · {lane.status}
                </small>
              </div>
              <ol className="aipm-design__nodes">
                {lane.nodes.map((node) => (
                  <li key={`${lane.rowId}:${node}`} className="aipm-design__node">
                    {node}
                  </li>
                ))}
              </ol>
            </div>
          ))
        ) : (
          <p className="aipm-design__muted">
            {c.t(
              '先在「AI 边界」保存一行分拣，这里就会出现方案图。',
              'Save a triage row under AI boundary to draw the design here.',
            )}
          </p>
        )}
      </div>
      <aside className="aipm-design__actual">
        <p className="aipm-design__eyebrow">{c.t('实际生效', 'In effect')}</p>
        <p>
          {c.t(
            '知识助手仍按当前设置运行。上面的组件都是拟议，保存方案不会改变设置。',
            'The assistant still runs on its current settings. Everything shown is proposed; saving never changes settings.',
          )}
        </p>
        <button type="button" className="btn quiet small" onClick={() => void host.openSettings()}>
          {c.t('打开实际设置', 'Open actual settings')}
        </button>
      </aside>
    </div>
  );
}
