/** A worksheet: one goal, angle hints, at most one choice and one big box. No sub-questions.
 * Writing only keeps a local draft; saving stores a new version of the pilot PRD (kind plan). */
import { Sparkle } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import type {
  AipmProgress,
  EvidenceRefV2,
  MetricDeclaration,
  ObjectRef,
  SheetState,
  StepId,
} from '../../aipm/types';
import { copy } from './copy';
import { patterns } from '../aipm-guide/content';
import { DESIGN_ID, type DesignRead, DiagramBlock, type DraftItem, Triage } from './desk';
import { sheetDraftKey } from './unsaved';
import { type AgentDraft, type Language, failure, findRef, mergeDraft, nextDesign } from './model';
import {
  type Block,
  blockId,
  type DesignContent,
  emptyBlocks,
  fromText,
  headings,
  insertAfter,
  insertAt,
  quoteRefs,
  readChoice,
  type SheetDesign,
  type SheetDraft,
  sheetKey,
  toText,
  metricKey,
  readMetric,
  wordCount,
  writeChoice,
  writeMetric,
} from './sheet-model';
import './worksheet.css';

type Role = 'manager' | 'business' | 'technical';
/** Host methods L1 adds for v2 (spec §10). Optional so the sheet degrades instead of breaking. */
export type WorksheetHost = AipmHost<
  unknown,
  AipmClient & { listDrafts?: () => Promise<unknown> }
> & {
  // L1 v2 host (claude/192-aipm-l1 8d4bf212, aipm/host.ts). Optional until that host.ts lands.
  currentScreen?(): { kind: string; sheet?: string };
  openWorksheet?(sheet: StepId | `free:${string}`): void;
  openMaterialSplit?(materialId: string): void;
  openReview?(step: StepId, reviewRef?: ObjectRef): void;
  askColleague?(input: { colleague: Role; prefill: string; attachPrd?: boolean }): Promise<void>;
  openPatterns?(): unknown;
};
export type Prd = { ref: ObjectRef; title?: string; sections: Partial<Record<StepId, string>> };
type Loaded = {
  content: DesignContent;
  saved: DesignRead | null;
  prd: Prd | null;
  drafts: DraftItem[];
  titles: Record<string, string>;
  /** Server view of this sheet and its latest review; absent until the host provides them. */
  sheetState?: SheetState | null;
  lastReview?: { at: string; version: number; ref: ObjectRef } | null;
};
const ROLE: Record<'manager' | 'business' | 'tech', Role> = {
  manager: 'manager',
  business: 'business',
  tech: 'technical',
};
const NAME: Record<Role, string> = { manager: 'Grace', business: 'Chen', technical: 'Daniel' };
/** Attribution in the sheet's language: 《title》v1 in Chinese, "title" v1 in English. */
export const sourceLabel = (language: Language, title: string, version: number) =>
  language === 'zh' ? `《${title}》v${version}` : `“${title}” v${version}`;
const draftKey = sheetDraftKey;
const notFound = (e: unknown) =>
  (e as { code?: string })?.code === 'object_not_found' ||
  (e as { status?: number })?.status === 404 ||
  /object_not_found|404/.test(String((e as Error)?.message ?? e));

/** A quote from the material view, delivered to the open sheet. Returns false when no sheet
 * is open, so the caller can say so instead of dropping the quote. */
const quotes = new EventTarget();
let openSheets = 0;
export function sendQuote(ref: EvidenceRefV2, label: string) {
  if (!openSheets) return false;
  quotes.dispatchEvent(new CustomEvent('quote', { detail: { ref, label } }));
  return true;
}

export function PatternCards({ language }: { language: Language }) {
  const content = patterns(language);
  return <aside className="aipm-sheet__patterns" aria-label={language === 'en' ? 'Public pattern cards' : '公开做法卡'}>
    <p>{content.label}</p><p>{content.note}</p>
    {content.cards.map((card) => <article key={card.id}>
      <h3>{card.title}</h3><p>{card.when}</p><p>{card.cost}</p><p>{card.whenNot}</p>
      <a href={card.source.url} target="_blank" rel="noreferrer">{card.source.title}</a>
    </article>)}
  </aside>;
}

/** The PRD as the server holds it now: its latest version. */
async function readPrd(host: WorksheetHost, ref: ObjectRef | null): Promise<Prd | null> {
  const data = host.getDataHost();
  if (!ref || !data) return null;
  const page = await data.query('work_products.versions.list', {
    product_id: ref.object_id,
    limit: 100,
  });
  const latest = [...page.items].sort((a, b) => b.version - a.version)[0];
  const payload = latest?.structured_payload as
    | { sections?: Partial<Record<StepId, string>> }
    | undefined;
  return latest
    ? { ref: { ...ref, version: latest.version }, title: latest.title, sections: payload?.sections ?? {} }
    : null;
}
/** The design as the server holds it now; null before the first save. */
async function readDesign(host: WorksheetHost): Promise<DesignRead | null> {
  const client = host.getClient();
  if (!client) return null;
  try {
    return await client.readDesign<DesignRead>(DESIGN_ID);
  } catch (e) {
    if (notFound(e)) return null;
    throw e;
  }
}
/** The part of the design each sheet writes itself (its choice, ③'s metric, ④'s rows); the
 * server judges a section review against the same part. */
const OWN: Partial<Record<StepId, keyof SheetDesign>> = {
  business: 'business',
  stakeholders: 'stakeholders',
  need: 'needs',
  boundary: 'rows',
  solution: 'solution',
  decision: 'intended_decision',
};
/** This sheet's own design part from the sheet, everything else as the server holds it now. */
export function withOwnPart(step: StepId, latest: SheetDesign, sheet: SheetDesign): SheetDesign {
  const key = OWN[step];
  return key ? { ...latest, [key]: sheet[key] } : latest;
}
/** Saving a design version against an older one: another write landed first. */
const MOVED = new Set(['version_conflict', 'aipm_design_revision_conflict']);

/** Agent drafts awaiting the learner; null when they cannot be read (drafts are optional). */
async function readDrafts(host: WorksheetHost): Promise<DraftItem[] | null> {
  try {
    const listed = (await host.getClient()?.listDrafts?.()) as { items?: DraftItem[] } | undefined;
    return (listed?.items ?? [])
      .filter((d) => d.draft.status === 'pending_owner_review')
      .map((d) => ({ ...d, draft: { ...d.draft, revision: d.ref.version } }));
  } catch {
    return null;
  }
}

async function loadSheet(host: WorksheetHost, step: StepId): Promise<Loaded> {
  const client = host.getClient();
  const content = (await host.readContent('design')) as DesignContent;
  let saved: DesignRead | null = null;
  try {
    saved = client ? await client.readDesign<DesignRead>(DESIGN_ID) : null;
  } catch (e) {
    if (!notFound(e)) throw e;
  }
  const prd = await readPrd(host, saved?.design.prd_ref ?? null);
  const data = host.getDataHost();
  const drafts = (await readDrafts(host)) ?? [];
  const titles: Record<string, string> = {};
  try {
    const page = data ? await data.query('materials.list', { limit: 200 }) : null;
    for (const m of page?.materials ?? []) titles[m.id] = m.title;
  } catch {
    // Titles only label buttons; ids remain usable.
  }
  let sheetState: SheetState | null = null;
  let lastReview: Loaded['lastReview'] = null;
  try {
    const progress = (await host.readProgress()) as AipmProgress | null;
    sheetState = progress?.steps?.find((s) => s.id === step)?.sheet ?? null;
    const page = await client?.sectionReviews?.(step, 0, 1);
    const latest = page?.items?.[0]?.review;
    const item = page?.items?.[0];
    if (latest && item)
      lastReview = { at: latest.created_at, version: latest.prd_ref.version, ref: item.ref };
  } catch {
    // Status is a label only; the sheet stays usable without it.
  }
  return { content, saved, prd, drafts, titles, sheetState, lastReview };
}

const savedSheet = (l: Loaded, step: StepId): SheetDraft => {
  const d = (l.saved?.design ?? null) as SheetDesign | null;
  return {
    blocks: fromText(l.prd?.sections[step] ?? '', d?.section_refs?.[step] ?? []),
    choice: d ? readChoice(step, d) : '',
  };
};
/** An unsaved local draft wins over the saved version when the sheet opens. */
const openingSheet = (l: Loaded, host: WorksheetHost, step: StepId): SheetDraft => {
  const local = host.getDataHost()?.draft<SheetDraft>('workspace', draftKey(step));
  return local?.blocks?.length ? local : savedSheet(l, step);
};
const baseDesign = (l: Loaded, host: WorksheetHost): SheetDesign =>
  (l.saved?.design as SheetDesign | undefined) ?? {
    id: DESIGN_ID,
    session_id: host.getSessionContext()?.sessionId ?? '',
    revision: 0,
    rows: [],
  };

export function Worksheet({
  host,
  step,
  preload,
}: {
  host: WorksheetHost;
  step: StepId;
  preload?: Loaded;
}) {
  const context = host.getSessionContext();
  const language: Language = context?.workLanguage === 'en' ? 'en' : 'zh';
  const c = copy(language);
  const readOnly = !!context?.readOnly;
  const [loaded, setLoaded] = useState<Loaded | null>(preload ?? null);
  const [sheet, setSheet] = useState<SheetDraft>(() =>
    preload ? openingSheet(preload, host, step) : { blocks: emptyBlocks(), choice: '' },
  );
  const [design, setDesign] = useState<SheetDesign | null>(() =>
    preload ? baseDesign(preload, host) : null,
  );
  const [loadFailed, setLoadFailed] = useState(false);
  const [caret, setCaret] = useState<{ id: string; offset: number } | null>(null);
  const [angle, setAngle] = useState<string | null>(null);
  const [showPatterns, setShowPatterns] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [menu, setMenu] = useState(false);
  const [structureOpen, setStructureOpen] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // An angle's one-line hint appears after a 300ms hover (at once on keyboard focus).
  const hoverIn = (id: string, delay = 300) => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHover(id), delay);
  };
  const hoverOut = () => {
    clearTimeout(hoverTimer.current);
    setHover(null);
  };
  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  const apply = useCallback(
    (l: Loaded) => {
      setLoaded(l);
      setDesign(baseDesign(l, host));
      setSheet(openingSheet(l, host, step));
    },
    [host, step],
  );
  const reload = useCallback(async () => {
    try {
      apply(await loadSheet(host, step));
    } catch {
      setLoadFailed(true);
    }
  }, [host, apply, step]);
  useEffect(() => {
    if (preload) apply(preload);
    else void reload();
  }, [preload, apply, reload]);
  /** Drafts only, leaving the writing alone: an agent may hand one back while the sheet is open
   * (the session's version point moves), and an adopted or declined one must leave (QA S-4). */
  const refreshDrafts = useCallback(async () => {
    const drafts = await readDrafts(host);
    if (drafts) setLoaded((l) => (l ? { ...l, drafts } : l));
  }, [host]);
  useEffect(() => {
    const data = host.getDataHost();
    if (!data) return;
    let point = JSON.stringify(data.snapshot().asOf);
    return data.subscribe(() => {
      const next = JSON.stringify(data.snapshot().asOf);
      if (next === point) return;
      point = next;
      void refreshDrafts();
    });
  }, [host, refreshDrafts]);

  const edit = (next: SheetDraft) => {
    setSheet(next);
    setNote('');
    void host.getDataHost()?.keepDraft('workspace', draftKey(step), next);
  };
  /** Subheadings split the paragraph at the caret; quotes go after the caret's paragraph. */
  const insert = (block: Block) => {
    const place = block.type === 'quote' ? insertAfter : insertAt;
    edit({ ...sheet, blocks: place(sheet.blocks, caret, block) });
    setCaret(null);
  };
  useEffect(() => {
    const on = (e: Event) => {
      const { ref, label } = (e as CustomEvent<{ ref: EvidenceRefV2; label: string }>).detail;
      insert({ id: blockId(), type: 'quote', text: ref.quote ?? '', label, ref });
    };
    quotes.addEventListener('quote', on);
    return () => quotes.removeEventListener('quote', on);
  });
  useEffect(() => {
    openSheets += 1;
    return () => {
      openSheets -= 1;
    };
  }, []);

  const content = loaded?.content.sheets[step];
  const prd = loaded?.prd ?? null;
  const dirty = loaded
    ? sheetKey(sheet) !== sheetKey(savedSheet(loaded, step)) ||
      metricKey(design) !== metricKey(loaded.saved?.design)
    : false;
  const sheetName = c.section(step);
  const version = prd?.ref.version;

  /** PRD version first, then the design that points at it (spec §5.3). Both go on top of what
   * the server holds now, not what this sheet read when it opened: another sheet, a review or an
   * adopted draft may have saved since, and a save against an older version is refused, the PRD
   * one before anything is sent (QA G-13). Only this section's text, quotes and own design part
   * come from the sheet; `build` puts that part on the latest design. */
  const saveVersion = async (state: SheetDraft, build: (latest: SheetDesign) => SheetDesign) => {
    if (!loaded) return null;
    let current = await readDesign(host);
    const head = (await readPrd(host, current?.design.prd_ref ?? prd?.ref ?? null)) ?? prd;
    const quotesHere = quoteRefs(state.blocks);
    const sections = { ...(head?.sections ?? {}), [step]: toText(state.blocks) };
    const evidence_refs = Object.values({
      ...(current?.design.section_refs ?? {}),
      [step]: quotesHere,
    }).flat() as EvidenceRefV2[];
    const payload = { type: 'plan' as const, sections };
    const work = await host.createWorkVersion(
      head
        ? {
            kind: 'plan',
            product_id: head.ref.object_id,
            expected_head: head.ref.version,
            title: head.title || c.t('试点 PRD', 'Pilot PRD'),
            structured_payload: payload,
            purpose: 'plan',
            evidence_refs,
          }
        : {
            kind: 'plan',
            title: c.t('试点 PRD', 'Pilot PRD'),
            purpose: 'plan',
            structured_payload: payload,
            evidence_refs,
          },
    );
    const prdRef = findRef(work, 'product');
    if (!prdRef || failure(work)) throw new Error('prd');
    // A colleague's reply or a model review can move the version point between the read and the
    // write; one more try on the design the server now holds.
    let result: unknown;
    for (let attempt = 0; ; attempt += 1) {
      const latest = (current?.design as SheetDesign | undefined) ?? baseDesign(loaded, host);
      const built = build(latest);
      const section_refs = { ...(latest.section_refs ?? {}), [step]: quotesHere };
      const next = writeChoice(step, { ...built, prd_ref: prdRef, section_refs }, state.choice);
      result = await host.command('aipm.design.save', {
        design: nextDesign(next, current?.design ?? null),
        expected_revision: current?.design.revision ?? 0,
      });
      const code = failure(result);
      if (!code) break;
      if (attempt > 0 || !MOVED.has(code)) throw Object.assign(new Error('choice'), { prdRef });
      current = await readDesign(host);
    }
    void host.getDataHost()?.keepDraft('workspace', draftKey(step), undefined);
    await reload();
    return { prdRef, designRef: findRef(result, 'aipm_design') };
  };
  const mine = (latest: SheetDesign) => (design ? withOwnPart(step, latest, design) : latest);
  const run = async (task: () => Promise<void>) => {
    setBusy(true);
    setNote('');
    try {
      await task();
    } catch (e) {
      setNote(
        (e as Error).message === 'review'
          ? c.t(
              '已存成新版本，批改没有生成，请再点一次。',
              'Saved as a new version; the review was not created. Try again.',
            )
          : (e as Error).message === 'choice'
            ? c.t(
                '文字已存成新版本，选择没存上，请再保存一次。',
                'The text is saved as a new version; the choice was not. Save again.',
              )
            : c.t('没有保存成功，内容仍在这里。', 'Not saved. Your writing is still here.'),
      );
    } finally {
      setBusy(false);
    }
  };
  const save = () =>
    run(async () => {
      if (design && dirty) await saveVersion(sheet, mine);
    });
  const review = () =>
    run(async () => {
      let prdRef = prd?.ref ?? null;
      let designRef = loaded?.saved?.ref ?? null;
      if (design && (dirty || !prdRef)) {
        const out = await saveVersion(sheet, mine);
        prdRef = out?.prdRef ?? prdRef;
        designRef = out?.designRef ?? designRef;
      }
      if (!prdRef) return;
      // Only the learner requests a review, on the exact version just saved (spec §6.1).
      const created = await host.command('aipm.section_review.create', {
        step_id: step,
        prd_ref: prdRef,
        design_ref: designRef,
      });
      if (failure(created)) throw new Error('review');
      if (host.openReview)
        host.openReview(step, findRef(created, 'aipm_section_review') ?? undefined);
      else
        setNote(
          c.t(
            '已存成新版本；批改单还没接入当前版本。',
            'Saved as a new version; the review view is not available in this build.',
          ),
        );
    });
  const ask = (who: Role) => {
    setMenu(false);
    const prefill = version
      ? c.t(
          `我在写「${sheetName}」第 ${version} 版，你怎么看？`,
          `I'm writing "${sheetName}", version ${version}. What do you think?`,
        )
      : c.t(
          `我在写「${sheetName}」，还没存版本，你怎么看？`,
          `I'm writing "${sheetName}" and have not saved a version yet. What do you think?`,
        );
    if (host.askColleague) void host.askColleague({ colleague: who, prefill });
    else void host.openColleague(who, prefill);
  };
  const adopt = (item: DraftItem) =>
    run(async () => {
      if (!design) return;
      const text = item.draft.prd_sections?.[step] ?? '';
      const blocks = text ? fromText(text, item.draft.section_refs?.[step] ?? []) : sheet.blocks;
      const out = await saveVersion(
        { blocks, choice: sheet.choice },
        (latest) => mergeDraft(latest, item.draft) as SheetDesign,
      );
      // The PRD keeps the learner as author; the draft record carries the agent's part (L4).
      const resolved = await host.command('aipm.design_drafts.resolve', {
        draft_id: item.draft.id,
        expected_revision: item.draft.revision,
        status: 'adopted',
        adopted_design_ref: out?.designRef,
        adopted_prd_ref: out?.prdRef,
      });
      await refreshDrafts();
      setNote(
        failure(resolved)
          ? c.t('已采用，但草稿状态没更新。', 'Adopted, but the draft status was not updated.')
          : c.t(
              `采用自你的 Agent 草稿，已存为第 ${out?.prdRef.version} 版。`,
              `Adopted from your agent's draft and saved as version ${out?.prdRef.version}.`,
            ),
      );
    });
  const decline = (item: DraftItem) =>
    run(async () => {
      const resolved = await host.command('aipm.design_drafts.resolve', {
        draft_id: item.draft.id,
        expected_revision: item.draft.revision,
        status: 'dismissed',
      });
      if (failure(resolved)) throw new Error('draft');
      await reload();
    });

  if (!loaded || !content || !design)
    return (
      <section className="aipm-sheet aipm-sheet--loading">
        {loadFailed
          ? c.t('暂时读不到这张纸。', 'Could not load this sheet.')
          : c.t('正在打开…', 'Opening…')}
      </section>
    );
  const drafts = loaded.drafts.filter((d) => d.draft.prd_sections?.[step]);
  const STATUS = {
    not_started: c.t('未开始', 'Not started'),
    draft: c.t('草稿', 'Draft'),
    based: c.t('有依据', 'Grounded'),
    solid: c.t('站得住', 'Holds up'),
    recheck: c.t('需重新核对', 'Recheck'),
  };
  const serverStatus = loaded.sheetState?.status ?? (version ? 'draft' : 'not_started');
  const status = STATUS[dirty ? 'draft' : serverStatus];
  const last = loaded.lastReview;
  const time = last
    ? new Date(last.at).toLocaleTimeString(language === 'zh' ? 'zh-CN' : 'en-GB', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '';
  const versionNote = last
    ? c.t(
        `上次批改 ${time} · 第 ${last.version} 版`,
        `Last reviewed ${time} · version ${last.version}`,
      )
    : version
      ? c.t(`已存第 ${version} 版`, `Saved version ${version}`)
      : '';
  const segment = {
    clarify: c.t('弄清问题', 'Clarify the problem'),
    design: c.t('设计方案', 'Design the solution'),
    verify: c.t('验证与决定', 'Verify and decide'),
  }[content.segment];
  const choiceOptions = content.choice?.from_headings
    ? headings(sheet.blocks).map((h) => ({ id: h, label: h }))
    : (content.choice?.options ?? []);
  const others = (['manager', 'business', 'tech'] as const).filter(
    (r) => !content.colleagues.includes(r),
  );
  const askOrder = [...content.colleagues, ...others].map((r) => ROLE[r]);
  const structure = (kind: 'triage' | 'diagram' | 'evaluation') => (
    <Structure
      kind={kind}
      open={structureOpen}
      onToggle={() => setStructureOpen(!structureOpen)}
      c={c}
      host={host}
      language={language}
      design={design}
      setDesign={setDesign}
      saved={loaded.saved}
      readOnly={readOnly}
      busy={busy}
      onSaveDesign={() =>
        run(async () => {
          const result = await host.command('aipm.design.save', {
            design: nextDesign(design, loaded.saved?.design ?? null),
            expected_revision: loaded.saved?.design.revision ?? 0,
          });
          if (failure(result)) throw new Error('save');
          await reload();
        })
      }
    />
  );

  return (
    <section className="aipm-sheet" lang={language} aria-label={sheetName}>
      <p className="aipm-sheet__eyebrow">
        <span>
          {segment} · {c.t(`第 ${content.order} 张`, `Sheet ${content.order}`)}
        </span>
        <span className={`aipm-sheet__tag is-${dirty ? 'draft' : serverStatus}`}>{status}</span>
        {last && host.openReview ? (
          <button
            type="button"
            className="aipm-sheet__review-link"
            onClick={() => host.openReview?.(step, last.ref)}
          >
            {versionNote} ›
          </button>
        ) : (
          versionNote && <span>{versionNote}</span>
        )}
      </p>
      <h1>{sheetName}</h1>
      <p className="aipm-sheet__goal">{content.goal}</p>

      {drafts.map((item) => (
        <AgentDraftCard
          key={item.draft.id}
          c={c}
          item={item.draft}
          mine={toText(sheet.blocks)}
          theirs={item.draft.prd_sections?.[step] ?? ''}
          disabled={readOnly || busy}
          onAdopt={() => void adopt(item)}
          onDecline={() => void decline(item)}
        />
      ))}

      <div className="aipm-sheet__angles">
        <p className="aipm-sheet__muted">
          {c.t(
            '可以从这些角度入手（点一下：插入小标题，或并排打开相关资料）',
            'Angles to start from (click: insert a subheading, or open related material alongside)',
          )}
        </p>
        <div className="aipm-sheet__chips">
          {content.angles.map((a) => (
            <span key={a.id} className="aipm-sheet__angle">
              <button
                type="button"
                aria-expanded={angle === a.id}
                aria-describedby={`angle-hint-${step}-${a.id}`}
                onMouseEnter={() => hoverIn(a.id)}
                onMouseLeave={hoverOut}
                onFocus={() => hoverIn(a.id, 0)}
                onBlur={hoverOut}
                onClick={() => {
                  hoverOut();
                  setAngle(angle === a.id ? null : a.id);
                }}
              >
                {a.label}
              </button>
              <span
                id={`angle-hint-${step}-${a.id}`}
                role="tooltip"
                className="aipm-sheet__hint"
                data-show={hover === a.id && angle !== a.id ? 'true' : undefined}
              >
                {a.hint}
              </span>
              {angle === a.id && (
                <span className="aipm-sheet__pop" role="menu">
                  <small>{a.hint}</small>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={readOnly}
                    onClick={() => {
                      insert({ id: blockId(), type: 'h', text: a.label });
                      setAngle(null);
                    }}
                  >
                    {c.t('插入小标题', 'Insert as subheading')}
                  </button>
                  {a.materials.map((m) => (
                    <button
                      key={m}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        void (host.openMaterialSplit ?? host.openMaterial)(m);
                        setAngle(null);
                      }}
                    >
                      {c.t('并排打开', 'Open alongside')}《{loaded.titles[m] ?? m}》
                    </button>
                  ))}
                  {a.patterns && (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setShowPatterns(true);
                        setAngle(null);
                      }}
                    >
                      {c.t('看市场做法卡', 'See the pattern cards')}
                    </button>
                  )}
                </span>
              )}
            </span>
          ))}
        </div>
      </div>
      {showPatterns && <section>
        <button type="button" className="aipm-sheet__patterns-close" onClick={() => setShowPatterns(false)}>{c.t('收起做法卡', 'Close pattern cards')}</button>
        <PatternCards language={language} />
      </section>}

      {content.choice && (
        <fieldset className="aipm-sheet__choice" disabled={readOnly}>
          <legend>{c.t(`${content.choice.label}：`, `${content.choice.label}:`)}</legend>
          {choiceOptions.length ? (
            <div className="aipm-sheet__segmented">
              {choiceOptions.map((o) => (
                <label key={o.id}>
                  <input
                    type="radio"
                    name={`choice-${step}`}
                    checked={sheet.choice === o.id}
                    onChange={() => edit({ ...sheet, choice: o.id })}
                  />
                  {o.label}
                </label>
              ))}
            </div>
          ) : (
            <span className="aipm-sheet__muted">{content.choice.empty}</span>
          )}
        </fieldset>
      )}

      {/* ⑤'s answer path is the sheet's picture: open and above the writing, never folded. */}
      {content.structure === 'diagram' && structure('diagram')}

      <Paper
        c={c}
        blocks={sheet.blocks}
        placeholder={loaded.content.placeholder}
        readOnly={readOnly}
        onChange={(blocks) => edit({ ...sheet, blocks })}
        onCaret={setCaret}
        onCite={async () => {
          const data = host.getDataHost();
          if (!data) return;
          for (const ref of await data.chooseEvidence({ selected: [] }))
            insert({
              id: blockId(),
              type: 'quote',
              text: ref.quote ?? '',
              label: sourceLabel(
                language,
                loaded.titles[ref.object_id] ?? ref.object_id,
                ref.version,
              ),
              ref,
            });
        }}
        footer={
          dirty
            ? c.t(
                `已存草稿 · ${wordCount(sheet.blocks)} 字`,
                `Draft kept · ${wordCount(sheet.blocks)} chars`,
              )
            : c.t(`${wordCount(sheet.blocks)} 字`, `${wordCount(sheet.blocks)} chars`)
        }
      />

      {content.structure === 'metric' && (
        <MetricBlock
          c={c}
          design={design}
          claim={sheet.choice}
          readOnly={readOnly}
          onChange={(patch) => {
            setDesign(writeMetric(design, sheet.choice, patch));
            setNote('');
          }}
        />
      )}
      {content.structure && content.structure !== 'metric' && content.structure !== 'diagram' &&
        structure(content.structure)}

      <footer className="aipm-sheet__foot">
        <AgentHelp c={c} host={host} step={step} />
        <span className="aipm-sheet__note" role="status">
          {note}
        </span>
        <button
          type="button"
          className="btn"
          disabled={readOnly || busy || !dirty}
          onClick={() => void save()}
        >
          {c.t('保存这一版', 'Save version')}
        </button>
        <span className="aipm-sheet__menu">
          <button type="button" className="btn" aria-expanded={menu} onClick={() => setMenu(!menu)}>
            {c.t('请同事看看', 'Ask a colleague')} ▾
          </button>
          {menu && (
            <span className="aipm-sheet__pop aipm-sheet__pop--up" role="menu">
              {askOrder.map((r) => (
                <button key={r} type="button" role="menuitem" onClick={() => ask(r)}>
                  {c.t(`问 ${NAME[r]}`, `Ask ${NAME[r]}`)}
                  {prd ? c.t(`（附上第 ${version} 版）`, ` (with version ${version})`) : ''}
                </button>
              ))}
            </span>
          )}
        </span>
        <button
          type="button"
          className="btn primary"
          disabled={readOnly || busy}
          onClick={() => void review()}
        >
          {c.t('交给批改', 'Get reviewed')}
        </button>
      </footer>
    </section>
  );
}

type Copy = ReturnType<typeof copy>;

/** Grows a textarea with its text: CSS field-sizing where supported, scrollHeight otherwise. */
function growToText(el: HTMLTextAreaElement | null) {
  if (!el || CSS.supports?.('field-sizing', 'content')) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

/** The big box: serif paragraphs, sans subheadings, quotes only from materials. */
function Paper({
  c,
  blocks,
  placeholder,
  readOnly,
  onChange,
  onCaret,
  onCite,
  footer,
}: {
  c: Copy;
  blocks: Block[];
  placeholder: string;
  readOnly: boolean;
  onChange: (b: Block[]) => void;
  onCaret: (at: { id: string; offset: number }) => void;
  onCite: () => void;
  footer: string;
}) {
  const refs = useRef(new Map<string, HTMLTextAreaElement | HTMLInputElement>());
  const set = (id: string, text: string) =>
    onChange(blocks.map((b) => (b.id === id ? { ...b, text } : b)));
  const remove = (id: string) => {
    const index = blocks.findIndex((b) => b.id === id);
    const next = blocks.filter((b) => b.id !== id);
    onChange(next.length ? next : [{ id: blockId(), type: 'p', text: '' }]);
    const before = next[index - 1];
    if (before) requestAnimationFrame(() => refs.current.get(before.id)?.focus());
  };
  const onlyEmpty = blocks.length === 1 && blocks[0].type === 'p' && !blocks[0].text;
  useLayoutEffect(() => {
    for (const el of refs.current.values()) if (el instanceof HTMLTextAreaElement) growToText(el);
  });
  return (
    <div className="aipm-sheet__paper">
      {blocks.map((b) =>
        b.type === 'quote' ? (
          <blockquote key={b.id} className="aipm-sheet__quote">
            <p>{b.text}</p>
            <cite>{c.t(`引自${b.label}`, `From ${b.label}`)}</cite>
            {!readOnly && (
              <button
                type="button"
                aria-label={c.t('移除引用', 'Remove quote')}
                onClick={() => remove(b.id)}
              >
                ×
              </button>
            )}
          </blockquote>
        ) : b.type === 'h' ? (
          <input
            key={b.id}
            className="aipm-sheet__h"
            value={b.text}
            readOnly={readOnly}
            ref={(el) => {
              if (el) refs.current.set(b.id, el);
            }}
            onChange={(e) => set(b.id, e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Backspace' && !b.text) {
                e.preventDefault();
                remove(b.id);
              }
            }}
          />
        ) : (
          <textarea
            key={b.id}
            className="aipm-sheet__p"
            value={b.text}
            readOnly={readOnly}
            placeholder={onlyEmpty ? placeholder : undefined}
            rows={1}
            data-only={onlyEmpty || undefined}
            ref={(el) => {
              if (el) refs.current.set(b.id, el);
            }}
            onChange={(e) => {
              set(b.id, e.target.value);
              onCaret({ id: b.id, offset: e.target.selectionStart });
            }}
            onSelect={(e) => onCaret({ id: b.id, offset: e.currentTarget.selectionStart })}
            onKeyDown={(e) => {
              if (e.key === 'Backspace' && !b.text && blocks.length > 1) {
                e.preventDefault();
                remove(b.id);
              }
            }}
          />
        ),
      )}
      <div className="aipm-sheet__paper-foot">
        {!readOnly && (
          <button type="button" className="aipm-sheet__cite" onClick={onCite}>
            {c.t('引用资料原句', 'Quote a source')}
          </button>
        )}
        <span className="aipm-sheet__count">{footer}</span>
      </div>
    </div>
  );
}

/** "1 row", "2 rows". */
const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

function Structure({
  kind,
  open,
  onToggle,
  c,
  host,
  language,
  design,
  setDesign,
  saved,
  readOnly,
  busy,
  onSaveDesign,
}: {
  kind: 'triage' | 'diagram' | 'evaluation';
  open: boolean;
  onToggle: () => void;
  c: Copy;
  host: WorksheetHost;
  language: Language;
  design: SheetDesign;
  setDesign: (d: SheetDesign) => void;
  saved: DesignRead | null;
  readOnly: boolean;
  busy: boolean;
  onSaveDesign: () => void;
}) {
  const rows = saved?.design.rows ?? [];
  const wrong = new Set(
    (saved?.feedback ?? [])
      .filter((f) => f.finding === 'violation')
      .map((f) => f.section_or_row_id),
  );
  const summary = {
    triage: c.t(
      `分拣表${rows.length ? ` · ${rows.length} 项` : ''}${wrong.size ? ` · ${wrong.size} 处越权` : ''}`,
      `Triage${rows.length ? ` · ${count(rows.length, 'row')}` : ''}${wrong.size ? ` · ${wrong.size} beyond authority` : ''}`,
    ),
    diagram: c.t('方案图', 'Solution diagram'),
    evaluation: c.t('评测计划、监控与回退表', 'Evaluation plan, monitoring and rollback'),
  }[kind];
  if (kind === 'diagram')
    return (
      <section className="aipm-sheet__structure" aria-label={summary}>
        <div className="aipm-sheet__structure-head">
          <strong className="aipm-sheet__structure-title">{summary}</strong>
          {rows.length > 0 && (
            <small className="aipm-sheet__structure-meta">
              {c.t(`按 ${rows.length} 行分拣`, `From ${count(rows.length, 'triage row')}`)}
            </small>
          )}
        </div>
        <div className="aipm-sheet__structure-body">
          <DiagramBlock c={c} host={host} saved={saved} language={language} />
        </div>
      </section>
    );
  if (kind === 'evaluation')
    return (
      <div className="aipm-sheet__structure">
        <button type="button" onClick={() => host.openFeature('evaluation')}>
          <strong>{summary}</strong>
          <small>{c.t('在评测台编辑', 'Edit in the evaluation desk')}</small>
        </button>
      </div>
    );
  return (
    <div className="aipm-sheet__structure">
      <button type="button" aria-expanded={open} onClick={onToggle}>
        <strong>{summary}</strong>
        <small>{open ? c.t('收起', 'Collapse') : c.t('展开编辑', 'Expand')}</small>
      </button>
      {open && (
        <div className="aipm-sheet__structure-body">
          {kind === 'triage' && (
            <Triage
              id="boundary"
              c={c}
              host={host}
              language={language}
              draft={design}
              setDraft={(d) => setDesign(d as SheetDesign)}
              saved={saved}
              justSaved={null}
              busy={busy}
              readOnly={readOnly}
              onSave={onSaveDesign}
              onNext={(s) => void host.openWorksheet?.(s)}
            />
          )}
        </div>
      )}
    </div>
  );
}

export function AgentDraftCard({
  c,
  item,
  mine,
  theirs,
  disabled,
  onAdopt,
  onDecline,
}: {
  c: Copy;
  item: AgentDraft;
  mine: string;
  theirs: string;
  disabled: boolean;
  onAdopt: () => void;
  onDecline: () => void;
}) {
  return (
    <article className="aipm-sheet__draft" data-draft-id={item.id}>
      <p className="aipm-sheet__eyebrow">
        {c.t('来自你的 Agent · 待你确认', 'From your agent · awaiting your confirmation')}
      </p>
      {item.note && <p className="aipm-sheet__muted">{item.note}</p>}
      <details>
        <summary>{c.t('看差异', 'See the difference')}</summary>
        <div className="aipm-sheet__diff">
          <div>
            <small>{c.t('你现在的', 'Yours now')}</small>
            <pre>{mine || c.t('（空）', '(empty)')}</pre>
          </div>
          <div>
            <small>{c.t('Agent 写的', 'Your agent wrote')}</small>
            <pre>{theirs}</pre>
          </div>
        </div>
      </details>
      <p className="aipm-sheet__muted">
        {c.t(
          '采用后才存成 PRD 新版本；不用时草稿记录会保留。',
          'Only adopting saves a new PRD version; if you decline, the draft stays on record.',
        )}
      </p>
      <div className="aipm-sheet__actions">
        <button type="button" className="btn primary small" disabled={disabled} onClick={onAdopt}>
          {c.t('采用', 'Adopt')}
        </button>
        <button type="button" className="btn quiet small" disabled={disabled} onClick={onDecline}>
          {c.t('不用', 'Decline')}
        </button>
      </div>
    </article>
  );
}

/** Without a connected agent: copyable instructions for this section, returned for review. */
function AgentHelp({ c, host, step }: { c: Copy; host: WorksheetHost; step: StepId }) {
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState('');
  useEffect(() => {
    if (!open || brief) return;
    host
      .readGuide()
      .then((g) => {
        const s = (
          g as { steps?: { id: string; help?: { agent_brief?: string }[] }[] }
        )?.steps?.find((x) => x.id === step);
        setBrief(s?.help?.find((h) => h.agent_brief)?.agent_brief ?? '');
      })
      .catch(() => {});
  }, [open, brief, host, step]);
  const text = useMemo(
    () =>
      `${brief}\n\n${c.t(
        `写完用 aipm.design.draft 交回，放在 prd_sections.${step}；交回后由我本人确认。`,
        `When done, return it with aipm.design.draft under prd_sections.${step}; I will confirm it myself.`,
      )}`.trim(),
    [brief, c, step],
  );
  return (
    <span className="aipm-sheet__menu">
      <button
        type="button"
        className="btn quiet"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Sparkle size={15} aria-hidden="true" />
        {c.t('让我的 Agent 帮我写', 'Ask my agent')}
      </button>
      {open && (
        <span className="aipm-sheet__pop aipm-sheet__pop--up aipm-sheet__pop--wide" role="dialog">
          <small>{c.t('把这段交给你的 Agent：', 'Give this to your agent:')}</small>
          <pre>{text}</pre>
          <button
            type="button"
            className="btn quiet small"
            onClick={() => void navigator.clipboard?.writeText(text)}
          >
            {c.t('复制', 'Copy')}
          </button>
        </span>
      )}
    </span>
  );
}

const METRIC_KINDS: Record<MetricDeclaration['kind'], readonly [string, string]> = {
  elapsed_time: ['结单历时', 'Elapsed time'],
  labor_time: ['人工处理工时', 'Hands-on labour time'],
  case_count: ['工单数量', 'Case count'],
  other: ['其他', 'Other'],
};
/** Optional: what the success metric measures and which field it comes from. */
function MetricBlock({
  c,
  design,
  claim,
  readOnly,
  onChange,
}: {
  c: Copy;
  design: SheetDesign;
  claim: string;
  readOnly: boolean;
  onChange: (patch: Partial<MetricDeclaration>) => void;
}) {
  const metric = readMetric(design);
  const [open, setOpen] = useState(false);
  const summary = metric
    ? [c.t(...METRIC_KINDS[metric.kind]), metric.source_field, metric.unit]
        .filter(Boolean)
        .join(' · ')
    : c.t('未填', 'Not filled');
  return (
    <div className="aipm-sheet__structure">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <strong>
          {c.t('指标小块（可选）', 'Metric (optional)')} · {summary}
        </strong>
        <small>{open ? c.t('收起', 'Collapse') : c.t('展开编辑', 'Expand')}</small>
      </button>
      {open && (
        <fieldset
          className="aipm-sheet__structure-body aipm-sheet__metric"
          disabled={readOnly || !claim}
        >
          {!claim && (
            <p className="aipm-sheet__muted">
              {c.t(
                '先在上面选这个需求现在是什么，再填指标。',
                'Choose where this need stands above first.',
              )}
            </p>
          )}
          <div className="aipm-sheet__choice">
            <span className="aipm-sheet__choice-label">
              {c.t('指标衡量的是：', 'The metric measures:')}
            </span>
            <div className="aipm-sheet__segmented">
              {(Object.keys(METRIC_KINDS) as MetricDeclaration['kind'][]).map((k) => (
                <label key={k}>
                  <input
                    type="radio"
                    name="metric-kind"
                    checked={metric?.kind === k}
                    onChange={() => onChange({ kind: k })}
                  />
                  {c.t(...METRIC_KINDS[k])}
                </label>
              ))}
            </div>
          </div>
          <div className="aipm-sheet__metric-fields">
            <label>
              <span>{c.t('来源字段', 'Source field')}</span>
              <input
                value={metric?.source_field ?? ''}
                placeholder="duration_minutes"
                onChange={(e) => onChange({ source_field: e.target.value.trim() })}
              />
            </label>
            <label>
              <span>{c.t('单位', 'Unit')}</span>
              <input
                value={metric?.unit ?? ''}
                placeholder={c.t('分钟', 'minutes')}
                onChange={(e) => onChange({ unit: e.target.value })}
              />
            </label>
          </div>
        </fieldset>
      )}
    </div>
  );
}
