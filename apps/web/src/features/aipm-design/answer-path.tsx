import { ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import type { AssistantConfig, EffectiveConfig } from '../../contracts-v2';
import { WORK_COST } from '../../app/vocab.js';
import type { V4HostAdapter } from '../../v4-host';
import {
  chainText,
  generatorText,
  guardText,
  type Identity,
  identityName,
  type OfflineKey,
  OFFLINE_IDENTITY,
  OFFLINE_KEYS,
  offlineName,
  onOff,
  STAGE_KEYS,
  type StageKey,
  stageName,
  updateStrategyText,
} from '../answer-chain/copy';
import { type Language, text } from './model';

/** The knowledge assistant's answer path as a design: the three offline steps that bring sources
 * in and the five online steps every question runs through, with the values in effect now.
 * The online names are the test bench's chain names (answer-chain/copy), so design and test read
 * as one picture. It only reads settings; nothing here changes them. */

type Config = Partial<AssistantConfig>;
export type PathRead = { config: Config; effective: EffectiveConfig | null };
export type PathNodeKey = OfflineKey | StageKey;
export type PathNode = {
  key: PathNodeKey;
  name: string;
  /** Hidden while the node is amber; the requested → effective line takes its place. */
  value: string;
  note: string | null;
  identities: Identity[];
  /** Has a "Your setting" part, so the whole node opens the settings. */
  settable: boolean;
  amber: { change: string; reason: string } | null;
};
export type PathView = { offline: PathNode[]; online: PathNode[]; effectiveKnown: boolean };

/** Design-view identities (spec M3); the test bench shows each step's main identity only. */
const IDENTITIES: Readonly<Record<PathNodeKey, Identity[]>> = {
  ...(Object.fromEntries(OFFLINE_KEYS.map((k) => [k, [OFFLINE_IDENTITY[k]]])) as Record<OfflineKey, Identity[]>),
  scope: ['yours', 'recognizer'],
  found: ['daniel', 'recognizer'],
  fresh: ['daniel'],
  answer: ['yours'],
  result: ['yours'],
};
/** The setting each node shows; a difference on it turns the node amber. */
const FIELDS: Readonly<Record<PathNodeKey, readonly (keyof AssistantConfig)[]>> = {
  sources: ['domains'],
  index: ['update_strategy'],
  passages: ['chunk_size', 'retrieval_limit'],
  scope: ['scope_filter'],
  found: ['min_score'],
  fresh: ['freshness_guard', 'manual_domains'],
  answer: ['generator'],
  result: ['fallback'],
};

/** The settings panel's knowledge-area words (app/vocab.js DOMAIN), in the work language. */
const DOMAIN_NAMES: Readonly<Record<string, [string, string]>> = {
  stable_faq: ['办公 FAQ', 'Office FAQ'],
  faq: ['办公 FAQ', 'Office FAQ'],
  onboarding: ['入职指引', 'Onboarding'],
  policy: ['差旅政策', 'Travel policy'],
  policy_travel: ['差旅政策', 'Travel policy'],
  policy_meal: ['餐费政策', 'Meal policy'],
  policy_leave: ['请假政策', 'Leave policy'],
};
const domainName = (id: string, language: Language) => {
  const names = DOMAIN_NAMES[id];
  return names ? names[language === 'zh' ? 0 : 1] : id;
};
const list = (ids: readonly string[], language: Language) =>
  ids.map((id) => domainName(id, language)).join(language === 'zh' ? '、' : ', ');
/** Product words start lower case where they sit inside a sentence; a node line starts a line. */
const line = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

export function reasonText(code: string | undefined, language: Language) {
  const t = (zh: string, en: string) => text(language, zh, en);
  switch (code) {
    case 'realtime_sync_not_provisioned':
      return t(
        `实时同步要 ${WORK_COST.realtime} 人日，还没批到。`,
        `Real-time sync needs ${WORK_COST.realtime} person-days that are not approved yet.`,
      );
    case 'scope_filter_not_provisioned':
      return t(
        `范围过滤要 ${WORK_COST.scope} 人日，还没批到。`,
        `The scope filter needs ${WORK_COST.scope} person-day that is not approved yet.`,
      );
    case 'human_fallback_not_provisioned':
      return t(
        `人工兜底要 ${WORK_COST.fallback} 人日，还没批到。`,
        `Human fallback needs ${WORK_COST.fallback} person-day that is not approved yet.`,
      );
    case 'manual_policy_not_provisioned':
      return t(
        '政策人工核需要范围过滤和人工兜底，还没批到。',
        'Manual policy checks need the scope filter and human fallback, not approved yet.',
      );
    default:
      return t('这项设置还没生效。', 'This setting is not in effect yet.');
  }
}

const NOT_RECORDED = (language: Language) => text(language, '没有记下', 'Not recorded');

/** The node's value in a few words, from one configuration; null when the field is absent. */
function brief(key: PathNodeKey, c: Config, language: Language): string | null {
  switch (key) {
    case 'sources':
      if (!Array.isArray(c.domains)) return null;
      return text(
        language,
        `${c.domains.length} 个知识域`,
        `${c.domains.length} knowledge area${c.domains.length === 1 ? '' : 's'}`,
      );
    case 'index':
      return updateStrategyText(c.update_strategy, language)?.value ?? null;
    case 'passages':
      return typeof c.chunk_size === 'number' && typeof c.retrieval_limit === 'number'
        ? chainText(language, 'passages_value', { size: c.chunk_size, limit: c.retrieval_limit })
        : null;
    case 'scope':
      return typeof c.scope_filter === 'boolean'
        ? chainText(language, 'scope_filter', { state: onOff(c.scope_filter, language) })
        : null;
    case 'found':
      return typeof c.min_score === 'number'
        ? chainText(language, 'threshold_value', { value: c.min_score })
        : null;
    case 'fresh': {
      const guard = guardText(c.freshness_guard, language);
      return guard ? chainText(language, 'row_guard', { value: guard }) : null;
    }
    case 'answer':
      return generatorText(c.generator ?? 'extractive', language);
    case 'result':
      return c.fallback === 'human' || c.fallback === 'none'
        ? chainText(language, 'human_fallback', { state: onOff(c.fallback === 'human', language) })
        : null;
  }
}

function note(key: PathNodeKey, c: Config, language: Language): string | null {
  switch (key) {
    case 'sources':
      return Array.isArray(c.domains) && c.domains.length ? list(c.domains, language) : null;
    case 'index':
      return updateStrategyText(c.update_strategy, language)?.note ?? null;
    case 'scope':
      return chainText(language, 'scope_detection');
    case 'found':
      return chainText(language, 'method_dense');
    case 'fresh':
      return c.manual_domains?.length
        ? text(language, '人工核验：', 'Manual check: ') + list(c.manual_domains, language)
        : null;
    default:
      return null;
  }
}

/** Compared as shown: the server may canonicalize a value (a knowledge area's alias) without it
 * meaning anything is not in effect. */
const shownAs = (key: PathNodeKey, c: Config, language: Language) =>
  `${brief(key, c, language)}|${note(key, c, language)}`;

export function answerPathView(read: PathRead, language: Language): PathView {
  const shown: Config = read.effective?.effective ?? read.config;
  const requested: Config = read.effective?.requested ?? read.config;
  const differences = read.effective?.differences ?? {};
  const node = (key: PathNodeKey, name: string): PathNode => {
    const identities = IDENTITIES[key];
    const fields = FIELDS[key];
    const field = fields.find((f) => f in differences);
    const changed = !!read.effective && shownAs(key, requested, language) !== shownAs(key, shown, language);
    let amber: PathNode['amber'] = null;
    if (field || changed) {
      const from = brief(key, requested, language) ?? NOT_RECORDED(language);
      const to = brief(key, shown, language) ?? NOT_RECORDED(language);
      amber = {
        change: text(language, `你请求：${from} → 实际：${to}`, `You asked: ${from} → in effect: ${to}`),
        reason: reasonText(field ? differences[field] : undefined, language),
      };
    }
    return {
      key,
      name,
      value: line(brief(key, shown, language) ?? NOT_RECORDED(language)),
      note: note(key, shown, language),
      identities,
      settable: identities.includes('yours'),
      amber,
    };
  };
  return {
    offline: OFFLINE_KEYS.map((k) => node(k, offlineName(k, language))),
    online: STAGE_KEYS.map((k) => node(k, stageName(k, language, true))),
    effectiveKnown: !!read.effective,
  };
}

/** One sentence per node for screen readers: "多久更新索引：每日，最长滞后 24 小时，你的设置". */
export function nodeSentence(n: PathNode, language: Language) {
  const sep = text(language, '，', ', ');
  const who = n.identities.map((i) => identityName(i, language)).join(text(language, '、', ' and '));
  const parts = n.amber
    ? [n.amber.change, who, text(language, '未生效', 'not in effect'), n.amber.reason]
    : [n.value, n.note, who];
  return `${n.name}${text(language, '：', ': ')}${parts.filter(Boolean).join(sep)}`;
}

/** workbench.read's workspace, the same read the workbench's live data uses. */
export async function readPath(data: Pick<V4HostAdapter, 'query'>): Promise<PathRead> {
  const context = await data.query('workbench.read');
  const w = context.timeline.workspace;
  return { config: w.config, effective: w.effective_config ?? null };
}

// ---- View ---------------------------------------------------------------------------------

function Node({
  n,
  language,
  onSettings,
}: {
  n: PathNode;
  language: Language;
  onSettings: (() => void) | null;
}) {
  const who = n.identities.map((i) => identityName(i, language)).join(' · ');
  const body = (
    <>
      <span className="sr-only">{nodeSentence(n, language)}</span>
      <span className="aipm-path__name" aria-hidden="true">
        {n.name}
      </span>
      {n.amber ? (
        <>
          <span className="aipm-path__value" aria-hidden="true">
            {n.amber.change}
          </span>
          <span className="aipm-path__reason" aria-hidden="true">
            {n.amber.reason}
          </span>
        </>
      ) : (
        <>
          <span className="aipm-path__value" aria-hidden="true">
            {n.value}
          </span>
          {n.note ? (
            <span className="aipm-path__note" aria-hidden="true">
              {n.note}
            </span>
          ) : null}
        </>
      )}
      <span className="aipm-path__who" aria-hidden="true">
        {who}
      </span>
    </>
  );
  const state = n.amber ? 'amber' : undefined;
  if (n.settable && onSettings)
    return (
      <button type="button" className="aipm-path__node" data-state={state} onClick={onSettings}>
        {body}
      </button>
    );
  return (
    <div
      className="aipm-path__node"
      data-state={state}
      title={
        n.identities.includes('daniel')
          ? text(language, '要调整，从测试台把失败的题交给 Daniel', 'To change this, hand a failed test to Daniel from the test bench')
          : undefined
      }
    >
      {body}
    </div>
  );
}

function Row({
  title,
  nodes,
  language,
  onSettings,
}: {
  title: string;
  nodes: PathNode[];
  language: Language;
  onSettings: (() => void) | null;
}) {
  return (
    <div className="aipm-path__row">
      <p className="aipm-path__row-title">{title}</p>
      <ol className="aipm-path__nodes" aria-label={title} data-count={nodes.length}>
        {nodes.map((n, i) => (
          <li key={n.key} className="aipm-path__step">
            {i > 0 ? (
              <span className="aipm-path__link" aria-hidden="true">
                <ChevronRight size={12} strokeWidth={1.6} />
              </span>
            ) : null}
            <Node n={n} language={language} onSettings={onSettings} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function Skeleton({ count }: { count: number }) {
  return (
    <ol className="aipm-path__nodes" aria-hidden="true" data-count={count}>
      {Array.from({ length: count }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed placeholders, never reordered.
        <li key={i} className="aipm-path__step">
          <span className="aipm-path__node aipm-path__node--blank" />
        </li>
      ))}
    </ol>
  );
}

type State = { kind: 'loading' } | { kind: 'failed' } | { kind: 'ready'; view: PathView };

/** The pure picture, for the desk and for tests. */
export function AnswerPathView({
  state,
  language,
  onSettings,
  onOpenSettings,
  onRetry,
}: {
  state: State;
  language: Language;
  /** Opens the settings from a "Your setting" node; null in a read-only session. */
  onSettings: (() => void) | null;
  /** The footer's "Open actual settings", as before (the sheet itself is read-only when it must be). */
  onOpenSettings: () => void;
  onRetry: () => void;
}) {
  const t = (zh: string, en: string) => text(language, zh, en);
  return (
    <section className="aipm-path" aria-labelledby="aipm-path-title" aria-busy={state.kind === 'loading'}>
      <h3 className="aipm-path__title" id="aipm-path-title">
        {t('知识助手的回答链', "The assistant's answer path")}
      </h3>
      <p className="aipm-path__lead">
        {t(
          '标「你的设置」的格子由你决定，标「Daniel 调」的由工程同事调整。保存方案不会改设置。',
          'Cells marked "Your setting" are yours to decide; "Daniel tunes" cells are adjusted by engineering. Saving a proposal never changes settings.',
        )}
      </p>
      {state.kind === 'failed' ? (
        <p className="aipm-path__failed" role="status">
          {t('暂时读不到当前设置', 'Current settings are unavailable right now')}
          <button type="button" className="btn quiet small" onClick={onRetry}>
            {t('重试', 'Retry')}
          </button>
        </p>
      ) : state.kind === 'loading' ? (
        <>
          <div className="aipm-path__row">
            <p className="aipm-path__row-title">{chainText(language, 'row_offline')}</p>
            <Skeleton count={OFFLINE_KEYS.length} />
          </div>
          <div className="aipm-path__row">
            <p className="aipm-path__row-title">{chainText(language, 'row_online')}</p>
            <Skeleton count={STAGE_KEYS.length} />
          </div>
        </>
      ) : (
        <>
          <Row
            title={chainText(language, 'row_offline')}
            nodes={state.view.offline}
            language={language}
            onSettings={onSettings}
          />
          <Row
            title={chainText(language, 'row_online')}
            nodes={state.view.online}
            language={language}
            onSettings={onSettings}
          />
        </>
      )}
      <p className="aipm-path__foot">
        {state.kind === 'ready' ? (
          <span>
            {state.view.effectiveKnown
              ? t('上图是此刻实际生效的设置。', 'Above is what is in effect now.')
              : t('上图是你保存的设置；实际生效暂不可读。', 'Above are your saved settings; what is in effect cannot be read right now.')}
          </span>
        ) : null}
        <button type="button" className="btn quiet small" onClick={onOpenSettings}>
          {t('打开实际设置', 'Open actual settings')}
        </button>
      </p>
    </section>
  );
}

/** Reads the settings once, and again whenever the workbench's data changes. */
export function AnswerPath({
  data,
  language,
  readOnly,
  onSettings,
  initial,
}: {
  data: Pick<V4HostAdapter, 'query' | 'subscribe' | 'snapshot'> | null;
  language: Language;
  readOnly: boolean;
  onSettings: () => void;
  /** Tests only: start from a read instead of querying. */
  initial?: PathRead | null;
}) {
  const [read, setRead] = useState<PathRead | null>(initial ?? null);
  const [failed, setFailed] = useState(!data && !initial);
  const load = useCallback(() => {
    if (!data) return;
    readPath(data)
      .then((next) => {
        setRead(next);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [data]);
  useEffect(() => {
    if (!data) return;
    // The host notifies on every snapshot change; settings can only move with the version point.
    let point = JSON.stringify(data.snapshot().asOf);
    load();
    return data.subscribe(() => {
      const next = JSON.stringify(data.snapshot().asOf);
      if (next === point) return;
      point = next;
      load();
    });
  }, [data, load]);
  const state: State = read
    ? { kind: 'ready', view: answerPathView(read, language) }
    : failed
      ? { kind: 'failed' }
      : { kind: 'loading' };
  return (
    <AnswerPathView
      state={state}
      language={language}
      onSettings={readOnly ? null : onSettings}
      onOpenSettings={onSettings}
      onRetry={() => {
        setFailed(false);
        load();
      }}
    />
  );
}
