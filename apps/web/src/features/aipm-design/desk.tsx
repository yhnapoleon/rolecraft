import { useCallback, useEffect, useMemo, useState } from 'react';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import type {
  AipmDesign,
  EvidenceRefV2,
  ObjectRef,
  ProcessFeedback,
  StepId,
  TriageRow,
} from '../../aipm/types';
import { STEP_IDS } from '../../aipm/types';
import { ACTIONS, AUTHORITIES, ROUTE_IDS, STARTER_NEEDS, copy } from './copy';
import {
  type Language,
  designChanged,
  designSummary,
  diagram,
  emptySections,
  failure,
  findRef,
  newRow,
  nextDesign,
  prdContent,
  rowChanged,
} from './model';
import './desk.css';

export const DESIGN_ID = 'aipm-design';
export type DesignRead = { ref: ObjectRef; design: AipmDesign; feedback: ProcessFeedback[] };
export type Tab = 'triage' | 'prd' | 'diagram';
type Host = AipmHost<unknown, AipmClient>;
type Copy = ReturnType<typeof copy>;

const blank = (sessionId: string): AipmDesign => ({
  id: DESIGN_ID,
  session_id: sessionId,
  revision: 0,
  rows: [],
});
const notFound = (error: unknown) =>
  /object_not_found|404/.test(String((error as Error)?.message ?? error));

export function DesignDesk({
  host,
  initialTab = 'triage',
  initial,
}: {
  host: Host;
  initialTab?: Tab;
  initial?: DesignRead | null;
}) {
  const context = host.getSessionContext();
  const language: Language = context?.workLanguage === 'en' ? 'en' : 'zh';
  const c = copy(language);
  const readOnly = !!context?.readOnly;
  const [tab, setTab] = useState<Tab>(initialTab);
  const [saved, setSaved] = useState<DesignRead | null>(initial ?? null);
  const [draft, setDraft] = useState<AipmDesign>(() =>
    structuredClone(initial?.design ?? blank(context?.sessionId ?? '')),
  );
  const [loading, setLoading] = useState(initial === undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<'' | 'read' | 'save' | 'conflict'>('');

  const load = useCallback(async () => {
    const client = host.getClient();
    if (!client || !host.getSessionContext()) return setLoading(false);
    try {
      const read = await client.readDesign<DesignRead>(DESIGN_ID);
      setSaved(read);
      setDraft(structuredClone(read.design));
    } catch (e) {
      if (!notFound(e)) setError('read');
    } finally {
      setLoading(false);
    }
  }, [host]);
  const preloaded = initial !== undefined;
  useEffect(() => {
    if (!preloaded) void load();
  }, [load, preloaded]);

  const save = async () => {
    setBusy(true);
    setError('');
    const design = nextDesign(draft, saved?.design ?? null);
    try {
      const result = await host.command('aipm.design.save', {
        design,
        expected_revision: saved?.design.revision ?? 0,
      });
      const failed = failure(result);
      if (failed) throw new Error(failed);
      await load();
    } catch (e) {
      setError(/conflict/.test(String((e as Error).message)) ? 'conflict' : 'save');
    } finally {
      setBusy(false);
    }
  };

  const dirty = saved
    ? designChanged(draft, saved.design)
    : (draft.rows?.length ?? 0) + Number(!!draft.solution) + Number(!!draft.prd_ref) > 0;
  const errors = {
    read: c.t('暂时读不到已保存的方案。', 'Could not read the saved design.'),
    save: c.t('没有保存成功，内容仍在这里。', 'Not saved. Your edits are still here.'),
    conflict: c.t(
      '方案已在别处更新，请重新读取后再改。',
      'The design changed elsewhere. Reload before editing.',
    ),
  };
  const tabs: [Tab, string][] = [
    ['triage', c.t('需求分拣', 'Triage')],
    ['prd', c.t('PRD 七节', 'PRD sections')],
    ['diagram', c.t('系统方案图', 'System design')],
  ];

  return (
    <section
      className="aipm-design"
      lang={language}
      aria-label={c.t('需求与方案', 'Needs and design')}
    >
      <header className="aipm-design__head">
        <div>
          <p className="aipm-design__eyebrow">
            {c.t('需求与方案', 'Needs and design')}
            {saved
              ? ` · ${c.t(`已保存第 ${saved.design.revision} 版`, `Saved version ${saved.design.revision}`)}`
              : ''}
          </p>
          <h2>
            {c.t(
              '先拆清动作，再定谁有最后决定权',
              'Separate the action from who has the final say',
            )}
          </h2>
        </div>
        <div className="aipm-design__tabs" role="tablist">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>
      {loading ? (
        <p className="aipm-design__muted">{c.t('正在读取…', 'Loading…')}</p>
      ) : (
        <>
          {tab === 'triage' && (
            <Triage
              c={c}
              host={host}
              draft={draft}
              setDraft={setDraft}
              saved={saved}
              readOnly={readOnly}
            />
          )}
          {tab === 'prd' && (
            <Prd
              c={c}
              host={host}
              language={language}
              draft={draft}
              setDraft={setDraft}
              readOnly={readOnly}
            />
          )}
          {tab === 'diagram' && (
            <Diagram
              c={c}
              host={host}
              language={language}
              draft={draft}
              setDraft={setDraft}
              saved={saved}
              readOnly={readOnly}
            />
          )}
          <footer className="aipm-design__foot">
            <span className="aipm-design__muted" role="status">
              {error
                ? errors[error]
                : dirty
                  ? c.t(
                      '有未保存的修改；保存后按这一版重新核对。',
                      'Unsaved changes. Saving re-checks this exact version.',
                    )
                  : c.t(
                      '保存只记录方案，不会执行工具或修改设置。',
                      'Saving records the design only. It never runs tools or changes settings.',
                    )}
            </span>
            <button
              type="button"
              className="btn primary"
              disabled={readOnly || busy || !dirty}
              onClick={save}
            >
              {busy ? c.t('保存中…', 'Saving…') : c.t('保存并核对', 'Save and check')}
            </button>
          </footer>
        </>
      )}
    </section>
  );
}

type Edit = {
  c: Copy;
  host: Host;
  draft: AipmDesign;
  setDraft: (d: AipmDesign) => void;
  readOnly: boolean;
};

function Triage({
  c,
  host,
  draft,
  setDraft,
  saved,
  readOnly,
}: Edit & { saved: DesignRead | null }) {
  const rows = draft.rows ?? [];
  const [open, setOpen] = useState<string | null>(rows[0]?.id ?? null);
  const row = rows.find((r) => r.id === open) ?? rows[0];
  const rowId = row?.id;
  const update = (patch: Partial<TriageRow>) =>
    setDraft({ ...draft, rows: rows.map((r) => (r.id === rowId ? { ...r, ...patch } : r)) });
  const add = (need?: (typeof STARTER_NEEDS)[number]) => {
    const id = `row-${Date.now().toString(36)}`;
    const value = {
      ...newRow(id),
      need_ref: need?.id ?? '',
      user_request: need ? c.starter(need) : '',
    };
    setDraft({ ...draft, rows: [...rows, value] });
    setOpen(id);
  };
  const remove = () => {
    setDraft({ ...draft, rows: rows.filter((r) => r.id !== rowId) });
    setOpen(null);
  };
  const feedbackFor = (id: string) =>
    (saved?.feedback ?? []).filter((f) => f.section_or_row_id === id);
  const savedRow = (id: string) => saved?.design.rows?.find((r) => r.id === id);

  return (
    <div className="aipm-design__triage">
      <aside className="aipm-design__list" aria-label={c.t('需求清单', 'Needs')}>
        {rows.map((r) => {
          const worst = feedbackFor(r.id).find((f) => f.finding === 'violation')
            ? 'violation'
            : undefined;
          return (
            <button
              key={r.id}
              type="button"
              aria-pressed={r.id === row?.id}
              onClick={() => setOpen(r.id)}
            >
              <strong>{r.user_request || c.t('未命名需求', 'Untitled need')}</strong>
              <small>
                {c.route(r.route)}
                {worst && (
                  <>
                    <i className="aipm-design__dot" aria-hidden="true" />
                    <span className="aipm-design__sr">{c.finding('violation')}</span>
                  </>
                )}
              </small>
            </button>
          );
        })}
        {!readOnly && (
          <div className="aipm-design__add">
            {STARTER_NEEDS.filter((n) => !rows.some((r) => r.need_ref === n.id)).map((n) => (
              <button key={n.id} type="button" className="btn quiet small" onClick={() => add(n)}>
                + {c.starter(n)}
              </button>
            ))}
            <button type="button" className="btn quiet small" onClick={() => add()}>
              + {c.t('自己的需求', 'Your own need')}
            </button>
          </div>
        )}
      </aside>
      {row ? (
        <div className="aipm-design__editor">
          <fieldset disabled={readOnly}>
            <label className="aipm-design__field aipm-design__field--wide">
              <span>{c.t('用户请求', 'User request')}</span>
              <input
                value={row.user_request}
                onChange={(e) => update({ user_request: e.target.value })}
                placeholder={c.t('例如：帮我把报销单批了', 'e.g. Approve my expense claim')}
              />
            </label>
            <div className="aipm-design__pair">
              <label className="aipm-design__field">
                <span>{c.t('要做的动作', 'Target action')}</span>
                <select
                  value={row.target_action}
                  onChange={(e) =>
                    update({ target_action: e.target.value as TriageRow['target_action'] })
                  }
                >
                  {(Object.keys(ACTIONS) as TriageRow['target_action'][]).map((a) => (
                    <option key={a} value={a}>
                      {c.action(a)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="aipm-design__field">
                <span>{c.t('最终由谁决定', 'Final authority')}</span>
                <select
                  value={row.final_authority}
                  onChange={(e) =>
                    update({ final_authority: e.target.value as TriageRow['final_authority'] })
                  }
                >
                  {(Object.keys(AUTHORITIES) as TriageRow['final_authority'][]).map((a) => (
                    <option key={a} value={a}>
                      {c.authority(a)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <fieldset className="aipm-design__routes" aria-label={c.t('处理方式', 'Handling')}>
              {ROUTE_IDS.map((route) => (
                <label key={route}>
                  <input
                    type="radio"
                    name={`route-${row.id}`}
                    checked={row.route === route}
                    onChange={() => update({ route })}
                  />
                  <strong>{c.route(route)}</strong>
                  <small>{c.routeHelp(route)}</small>
                </label>
              ))}
            </fieldset>
            {(row.route === 'agent_confirmation' || row.route === 'human') && (
              <div className="aipm-design__pair">
                <label className="aipm-design__field">
                  <span>
                    {row.route === 'human'
                      ? c.t('交给谁、凭什么', 'Who takes it, with what')
                      : c.t('谁在何时确认', 'Who confirms, and when')}
                  </span>
                  <input
                    value={row.confirmation_point ?? ''}
                    onChange={(e) => update({ confirmation_point: e.target.value })}
                  />
                </label>
                {row.route === 'agent_confirmation' && (
                  <label className="aipm-design__field">
                    <span>{c.t('需要的工具（逗号分隔）', 'Tools needed (comma separated)')}</span>
                    <input
                      value={(row.tool_assumptions ?? []).join(', ')}
                      onChange={(e) =>
                        update({
                          tool_assumptions: e.target.value
                            .split(/[,，]/)
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                  </label>
                )}
              </div>
            )}
            <label className="aipm-design__field aipm-design__field--wide">
              <span>{c.t('为什么这样分', 'Why this split')}</span>
              <textarea
                rows={2}
                value={row.rationale}
                onChange={(e) => update({ rationale: e.target.value })}
              />
            </label>
          </fieldset>
          <div className="aipm-design__row-tools">
            <Evidence
              c={c}
              host={host}
              refs={row.source_refs ?? []}
              disabled={readOnly}
              onChange={(source_refs) => update({ source_refs })}
            />
            <span className="aipm-design__muted">
              {support(c, savedRow(row.id)?.execution_support)}
            </span>
            {!readOnly && (
              <button type="button" className="btn quiet small" onClick={remove}>
                {c.t('移除这一行', 'Remove row')}
              </button>
            )}
          </div>
          <Feedback
            c={c}
            host={host}
            items={feedbackFor(row.id)}
            stale={rowChanged(row, saved?.design ?? null)}
            version={saved?.design.revision}
          />
        </div>
      ) : (
        <p className="aipm-design__empty">
          {c.t(
            '从一项需求开始：先说清用户要的是回答还是行动。',
            'Start with one need: is the user asking for an answer or an action?',
          )}
        </p>
      )}
    </div>
  );
}

const support = (c: Copy, value?: TriageRow['execution_support']) =>
  value === 'supported'
    ? c.t('本局已有受支持路径', 'A supported path exists here')
    : value === 'plan_only'
      ? c.t('仅方案：本局没有执行能力', 'Proposal only: no execution here')
      : c.t('执行能力待服务端核对', 'Execution support not yet checked');

function Evidence({
  c,
  host,
  refs,
  onChange,
  disabled,
}: {
  c: Copy;
  host: Host;
  refs: readonly EvidenceRefV2[];
  onChange: (r: EvidenceRefV2[]) => void;
  disabled: boolean;
}) {
  const data = host.getDataHost();
  return (
    <button
      type="button"
      className="btn quiet small"
      disabled={disabled || !data}
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
        : c.t('引用原文', 'Cite a source')}
    </button>
  );
}

function Feedback({
  c,
  host,
  items,
  stale,
  version,
}: {
  c: Copy;
  host: Host;
  items: ProcessFeedback[];
  stale: boolean;
  version?: number;
}) {
  if (!items.length) return null;
  return (
    <div className="aipm-design__feedback" aria-live="polite">
      {items.map((item) => {
        const old = stale || !!item.stale;
        return (
          <article
            key={item.id}
            className={`aipm-design__finding is-${item.finding}${old ? ' is-stale' : ''}`}
          >
            <p className="aipm-design__eyebrow">
              {c.source(item.source)} · {c.finding(item.finding)}
              {old &&
                ` · ${c.t(`对应第 ${version ?? item.input_ref.version} 版，已修改，保存后重新核对`, `For version ${version ?? item.input_ref.version}; edited since, save to re-check`)}`}
            </p>
            <p>{item.message}</p>
            {(item.basis_refs ?? [])
              .filter((r) => r.quote)
              .map((r) => (
                <blockquote key={`${r.kind}:${r.object_id}:${r.version}:${r.span_start ?? ''}`}>
                  <button type="button" onClick={() => void host.getDataHost()?.openReference(r)}>
                    “{r.quote}”
                  </button>
                </blockquote>
              ))}
            {item.next_action && <p className="aipm-design__next">{item.next_action.label}</p>}
            <small className="aipm-design__muted">{item.checked_scope}</small>
          </article>
        );
      })}
    </div>
  );
}

function Prd({ c, host, language, draft, setDraft, readOnly }: Edit & { language: Language }) {
  const data = host.getDataHost();
  const [sections, setSections] = useState<Record<StepId, string>>(() => ({
    ...emptySections(),
    ...(data?.draft<Record<StepId, string>>('workspace', 'aipm-prd') ?? {}),
  }));
  const [open, setOpen] = useState<StepId>('business');
  const [linked, setLinked] = useState<Partial<Record<StepId, ObjectRef[]>>>({});
  const [note, setNote] = useState('');
  const linkedCount = (id: StepId) => linked[id]?.length ?? 0;
  const write = (id: StepId, value: string) => {
    const next = { ...sections, [id]: value };
    setSections(next);
    void data?.keepDraft('workspace', 'aipm-prd', next);
  };
  const current = data?.snapshot().currentProduct ?? null;
  const link = async (id: StepId) => {
    if (!current) return;
    const result = await host.command('aipm.step_links.save', {
      step_id: id,
      product_ref: current,
      section_key: id,
    });
    if (failure(result)) return setNote(c.t('没有关联成功。', 'The link was not saved.'));
    setLinked({ ...linked, [id]: [...(linked[id] ?? []), current] });
  };
  const fromTriage = (id: 'boundary' | 'solution') => write(id, designSummary(draft, language)[id]);
  const saveWork = async () => {
    const content = prdContent(sections, c.section);
    const prior = draft.prd_ref;
    const result = await host.createWorkVersion(
      prior
        ? { kind: 'text', content, product_id: prior.object_id, expected_head: prior.version }
        : {
            kind: 'text',
            content,
            title: c.t('知识助手 PRD', 'Knowledge assistant PRD'),
            purpose: c.t('七节 PRD', 'Seven-section PRD'),
          },
    );
    const ref = findRef(result, 'product');
    if (!ref || failure(result))
      return setNote(c.t('作品没有保存成功。', 'The work version was not saved.'));
    setDraft({ ...draft, prd_ref: ref });
    setNote(
      c.t(
        `已存为作品第 ${ref.version} 版；再保存方案即可关联。`,
        `Saved as work version ${ref.version}. Save the design to link it.`,
      ),
    );
  };
  return (
    <div className="aipm-design__prd">
      <ol>
        {STEP_IDS.map((id, index) => (
          <li key={id} className={open === id ? 'is-open' : ''}>
            <button
              type="button"
              className="aipm-design__section"
              aria-expanded={open === id}
              onClick={() => setOpen(id)}
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              <strong>{c.section(id)}</strong>
              <small>
                {sections[id].trim() ? c.t('已写', 'Drafted') : ''}
                {linkedCount(id)
                  ? ` · ${c.t(`关联 ${linkedCount(id)} 份作品`, `${linkedCount(id)} linked`)}`
                  : ''}
              </small>
            </button>
            {open === id && (
              <div className="aipm-design__section-body">
                <p className="aipm-design__muted">{c.sectionPrompt(id)}</p>
                <textarea
                  rows={6}
                  disabled={readOnly}
                  value={sections[id]}
                  onChange={(e) => write(id, e.target.value)}
                />
                <div className="aipm-design__row-tools">
                  {(id === 'boundary' || id === 'solution') && (
                    <button
                      type="button"
                      className="btn quiet small"
                      disabled={readOnly || !draft.rows?.length}
                      onClick={() => fromTriage(id)}
                    >
                      {c.t('从分拣结果填入', 'Fill from triage')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn quiet small"
                    disabled={readOnly || !current}
                    onClick={() => void link(id)}
                    title={
                      current ? undefined : c.t('先在作品区打开一份作品', 'Open a work item first')
                    }
                  >
                    {c.t('关联当前打开的作品', 'Link the open work item')}
                  </button>
                  <button
                    type="button"
                    className="btn quiet small"
                    onClick={() => void host.openWork()}
                  >
                    {c.t('打开作品区', 'Open work')}
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ol>
      <div className="aipm-design__row-tools">
        <span className="aipm-design__muted" role="status">
          {note ||
            c.t(
              '七节不必按顺序写完；可只写当下需要的部分。',
              'Sections need not be written in order; draft what you need now.',
            )}
        </span>
        <button
          type="button"
          className="btn quiet"
          disabled={readOnly}
          onClick={() => void saveWork()}
        >
          {draft.prd_ref ? c.t('另存新版本', 'Save new version') : c.t('存为作品', 'Save as work')}
        </button>
      </div>
    </div>
  );
}

function Diagram({
  c,
  host,
  language,
  draft,
  setDraft,
  saved,
  readOnly,
}: Edit & { language: Language; saved: DesignRead | null }) {
  const lanes = useMemo(() => (saved ? diagram(saved.design, language) : []), [saved, language]);
  const solution = draft.solution ?? {
    selected_approach: '',
    rationale: '',
    alternative: '',
    dependencies: [],
  };
  const set = (patch: Partial<typeof solution>) =>
    setDraft({ ...draft, solution: { ...solution, ...patch } });
  const configNotes = (saved?.feedback ?? []).filter((f) => f.step_id === 'solution');
  return (
    <div className="aipm-design__diagram">
      <section aria-label={c.t('拟议方案', 'Proposed design')}>
        <p className="aipm-design__eyebrow">
          {c.t('拟议方案', 'Proposed design')}
          {saved
            ? ` · ${c.t(`按已保存第 ${saved.design.revision} 版生成`, `Drawn from saved version ${saved.design.revision}`)}`
            : ''}
        </p>
        {lanes.length ? (
          lanes.map((lane) => {
            return (
              <div key={lane.rowId} className={`aipm-design__lane is-${lane.route}`}>
                <div className="aipm-design__lane-head">
                  <strong>{lane.request}</strong>
                  <small>
                    {c.route(lane.route)} · {lane.status}
                  </small>
                </div>
                <ol className="aipm-design__nodes">
                  {lane.nodes.map((node) => (
                    <li key={`${lane.rowId}:${node}`}>{node}</li>
                  ))}
                </ol>
              </div>
            );
          })
        ) : (
          <p className="aipm-design__empty">
            {c.t(
              '保存一次分拣后，这里按每行生成方案结构。',
              'Save a triage once to draw one lane per row.',
            )}
          </p>
        )}
      </section>
      <section className="aipm-design__actual" aria-label={c.t('实际生效', 'In effect')}>
        <p className="aipm-design__eyebrow">{c.t('实际生效', 'In effect')}</p>
        <p>
          {c.t(
            '知识助手仍按当前设置运行。图上的组件都是拟议，保存方案不会改变设置。',
            'The assistant still runs on its current settings. Everything above is proposed; saving never changes settings.',
          )}
        </p>
        {configNotes.map((f) => (
          <p key={f.id} className="aipm-design__next">
            {f.message}
          </p>
        ))}
        <button type="button" className="btn quiet small" onClick={() => void host.openSettings()}>
          {c.t('打开实际设置', 'Open actual settings')}
        </button>
      </section>
      <fieldset className="aipm-design__solution" disabled={readOnly}>
        <label className="aipm-design__field aipm-design__field--wide">
          <span>{c.t('选定做法', 'Chosen approach')}</span>
          <input
            value={solution.selected_approach}
            onChange={(e) => set({ selected_approach: e.target.value })}
          />
        </label>
        <div className="aipm-design__pair">
          <label className="aipm-design__field">
            <span>{c.t('方案理由', 'Rationale')}</span>
            <textarea
              rows={2}
              value={solution.rationale}
              onChange={(e) => set({ rationale: e.target.value })}
            />
          </label>
          <label className="aipm-design__field">
            <span>{c.t('实质替代方案', 'Meaningful alternative')}</span>
            <textarea
              rows={2}
              value={solution.alternative}
              onChange={(e) => set({ alternative: e.target.value })}
            />
          </label>
        </div>
        <label className="aipm-design__field aipm-design__field--wide">
          <span>{c.t('依赖和资源（每行一项）', 'Dependencies and resources (one per line)')}</span>
          <textarea
            rows={2}
            value={(solution.dependencies ?? []).join('\n')}
            onChange={(e) =>
              set({
                dependencies: e.target.value
                  .split('\n')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
      </fieldset>
    </div>
  );
}
