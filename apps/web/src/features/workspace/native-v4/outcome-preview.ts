/** Work-view outcome preview: summary first, details on demand. It reads saved previews and
 * their read-time states only; links open the existing v4 tools and never run anything. */
import type {
  FeedbackV2,
  JsonValue,
  _OutcomeItem as OutcomeItem,
  _PreviewActual as PreviewActual,
  _PreviewChange as PreviewChange,
  _PreviewState as PreviewState,
} from '../../../contracts-v2';
import { outcomeTerm, outcomeText, type OutcomeKey, type OutcomeLanguage } from './outcome-copy';

export type PreviewEntry = { preview: FeedbackV2; state: PreviewState | null };
type Row = Record<string, unknown>;
const row = (value: unknown): value is Row =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** Validate the optional preview fields of one versions page for this exact product. */
export function previewEntries(
  page: unknown,
  sessionId: string,
  productId: string,
): PreviewEntry[] {
  if (!row(page) || page.previews === undefined || page.previews === null) return [];
  const previews = page.previews,
    states = page.preview_states;
  if (!Array.isArray(previews)) throw Error('invalid_preview_page');
  if (states !== undefined && states !== null && !Array.isArray(states))
    throw Error('invalid_preview_page');
  return previews.map((preview, index) => {
    const subject = row(preview) ? preview.subject : undefined;
    if (
      !row(preview) ||
      preview.session_id !== sessionId ||
      typeof preview.id !== 'string' ||
      !row(subject) ||
      subject.kind !== 'product' ||
      subject.object_id !== productId ||
      !Number.isInteger(subject.version) ||
      !Array.isArray(preview.outcomes ?? [])
    )
      throw Error('invalid_preview');
    const state = Array.isArray(states) ? states[index] : null;
    if (
      state !== null &&
      (!row(state) ||
        !row(state.feedback) ||
        state.feedback.object_id !== preview.id ||
        (state.status !== 'current' && state.status !== 'stale'))
    )
      throw Error('invalid_preview_state');
    return { preview: preview as FeedbackV2, state: state as PreviewState | null };
  });
}

/** Operation → existing v4 shell action; sharing already sits right below the preview. */
const LINKS: Record<string, [string, OutcomeKey]> = {
  'tests.create': ['open-bench', 'linkTest'],
  'configuration.apply': ['config', 'linkConfig'],
  actions: ['resources', 'linkResources'],
  'submissions.create': ['submit', 'linkSubmit'],
  'reviews.create': ['request-review', 'linkReview'],
};
const KINDS: Record<OutcomeItem['kind'], OutcomeKey> = {
  fact: 'kindFact',
  conditional_prediction: 'kindPrediction',
  pending_verification: 'kindPending',
  unsupported: 'kindUnsupported',
};

export type OutcomeLine = {
  kind: OutcomeItem['kind'];
  label: string;
  summary: string;
  conditions: string[];
  waitsFor: string;
};
export type PreviewView = {
  labels: Record<
    'question' | 'changed' | 'actual' | 'details' | 'conditions' | 'waitsFor' | 'links',
    string
  >;
  heading: string;
  version: string;
  meta: string[];
  status: 'current' | 'stale';
  statusLabel: string;
  response: string;
  questions: string[];
  draftNote: string | null;
  carried: string | null;
  changes: string[];
  newer: string | null;
  refreshHint: string | null;
  actual: string[];
  outcomes: OutcomeLine[];
  basis: string;
  links: { action: string; label: string }[];
};
export type OutcomeView = {
  main: PreviewView;
  earlier: { label: string; view: PreviewView }[];
  earlierLabel: string;
};

/** Choose the preview of the saved version shown in the editor; older ones stay listed. */
export function outcomeView(
  entries: readonly PreviewEntry[],
  saved: { version: number; hasDraft: boolean },
  language: OutcomeLanguage,
  available: (operation: string) => boolean,
  titles: Readonly<Record<string, string>> = {},
): OutcomeView | null {
  if (!entries.length) return null;
  const ordered = [...entries].sort(
    (a, b) => b.preview.subject.version - a.preview.subject.version,
  );
  const exact = ordered.find((entry) => entry.preview.subject.version === saved.version);
  const main = exact ?? ordered.find((entry) => entry.preview.subject.version < saved.version);
  if (!main) return null;
  const earlier = ordered.filter((entry) => entry !== main);
  const view = (entry: PreviewEntry, primary: boolean) =>
    previewView(
      entry,
      language,
      primary ? saved.hasDraft : false,
      primary ? available : () => false,
      titles,
    );
  const shown = view(main, true);
  // A later lifecycle-only version (adoption, removal, restore) keeps this preview current.
  if (main.preview.subject.version < saved.version && shown.status === 'current')
    shown.carried = outcomeText(language, 'sameContent', { v: saved.version });
  return {
    main: shown,
    earlier: earlier.map((entry) => ({
      label: outcomeText(language, 'earlierEntry', { v: entry.preview.subject.version }),
      view: view(entry, false),
    })),
    earlierLabel: outcomeText(language, 'earlier', { n: earlier.length }),
  };
}

export function previewView(
  entry: PreviewEntry,
  language: OutcomeLanguage,
  hasDraft: boolean,
  available: (operation: string) => boolean,
  titles: Readonly<Record<string, string>> = {},
): PreviewView {
  const { preview, state } = entry;
  const t = (key: OutcomeKey, values?: Record<string, string | number>) =>
    outcomeText(language, key, values);
  const outcomes = preview.outcomes ?? [];
  const model = (
    {
      waiting_model: 'waitingModel',
      failed: 'modelFailed',
      unknown: 'modelUnknown',
      advisory: 'modelAdvisory',
    } as Record<string, OutcomeKey>
  )[preview.generation_status ?? ''];
  const stale = state?.status === 'stale';
  const version = preview.subject.version;
  const config = (preview.basis_refs ?? []).find((ref) => ref.kind === 'config');
  const seen = new Set<string>();
  const links = (preview.available_actions ?? [])
    .map((action) => action.operation)
    .filter((operation) => LINKS[operation] && available(operation) && !seen.has(operation))
    .map((operation) => {
      seen.add(operation);
      const [action, key] = LINKS[operation];
      return { action, label: t(key) };
    });
  return {
    labels: {
      question: t('question'),
      changed: t('changed'),
      actual: t('actualTitle'),
      details: t('details'),
      conditions: t('conditions'),
      waitsFor: t('waitsFor'),
      links: t('linksNote'),
    },
    heading: t('title'),
    version: t('version', { v: version }),
    meta: [t('ruleChecked'), ...(model ? [t(model)] : [])],
    status: stale ? 'stale' : 'current',
    statusLabel: t(stale ? 'stale' : 'current'),
    response: preview.business_response,
    questions: [...(preview.clarification ?? [])],
    draftNote: hasDraft ? t('draftNote', { v: version }) : null,
    carried: null,
    changes: (state?.changes ?? []).map((change) => changeLine(change, language, titles)),
    newer: state?.superseded_by ? t('newer') : null,
    refreshHint: stale && !state?.superseded_by ? t('refreshHint') : null,
    actual: (state?.actual ?? []).map((actual) => actualLine(actual, language)),
    outcomes: outcomes.map((o) => ({
      kind: o.kind,
      label: t(KINDS[o.kind]),
      summary: o.summary,
      conditions: [...(o.conditions ?? [])],
      waitsFor: (o.missing_inputs ?? [])
        .map((code) => outcomeTerm(language, 'missing', code))
        .join(language === 'en' ? ', ' : '、'),
    })),
    basis:
      t('basis', { v: version }) +
      (config?.config_version != null
        ? ` · ${t('basisConfiguration', { v: config.config_version })}`
        : ''),
    links,
  };
}

const integer = (value: JsonValue | undefined) =>
  typeof value === 'number' && Number.isInteger(value) ? value : null;
const dict = (value: JsonValue | undefined): Record<string, JsonValue> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : {};
const shown = (value: JsonValue) =>
  Array.isArray(value) ? value.join('、') : value === null ? '' : String(value);

export function changeLine(
  change: PreviewChange,
  language: OutcomeLanguage,
  titles: Readonly<Record<string, string>> = {},
): string {
  const t = (key: OutcomeKey, values: Record<string, string | number> = {}) =>
    outcomeText(language, key, values);
  if (change.condition === 'input')
    return t('changeInput', {
      before: integer(change.before) ?? '?',
      after: integer(change.after) ?? '?',
    });
  if (change.condition === 'configuration')
    return t('changeConfiguration', {
      before: integer(change.before) ?? '?',
      after: integer(change.after) ?? '?',
    });
  const separator = language === 'en' ? ', ' : '；';
  const before = dict(change.before),
    after = dict(change.after);
  // A finite-scope reader learns only that the condition changed.
  if (change.before == null && change.after == null)
    return t(
      change.condition === 'resources' ? 'changeResourcesWithheld' : 'changeMaterialsWithheld',
    );
  if (change.condition === 'resources')
    return t('changeResources', {
      items: Object.keys(after)
        .map(
          (key) =>
            `${outcomeTerm(language, 'resource', key)} ${shown(before[key] ?? null)} → ${shown(after[key] ?? null)}`,
        )
        .join(separator),
    });
  return Object.entries(after)
    .map(([id, version]) => t('changeMaterial', { title: titles[id] ?? id, v: shown(version) }))
    .join(separator);
}

/** Material changes name materials; their titles come from the reader's own material list. */
export function changedMaterials(entries: readonly PreviewEntry[]): boolean {
  return entries.some((entry) =>
    (entry.state?.changes ?? []).some(
      (change) => change.condition === 'materials' && change.after != null,
    ),
  );
}

export function actualLine(actual: PreviewActual, language: OutcomeLanguage): string {
  const t = (key: OutcomeKey, values: Record<string, string | number>) =>
    outcomeText(language, key, values);
  const values = actual.values ?? {};
  if (actual.operation === 'configuration.apply') {
    const changed = Object.entries(dict(values.changed))
      .map(([key, value]) => `${outcomeTerm(language, 'setting', key)} ${shown(value)}`)
      .join(language === 'en' ? ', ' : '；');
    const head = t('actualConfiguration', { v: integer(values.config_version) ?? '?' });
    return changed ? `${head}${language === 'en' ? ': ' : '：'}${changed}` : head;
  }
  if (actual.operation === 'actions') {
    const granted = Object.entries(dict(values.granted))
      .map(([key, value]) => `${outcomeTerm(language, 'resource', key)} ${shown(value)}`)
      .join(language === 'en' ? ', ' : '；');
    const head = t('actualApproval', {
      status: outcomeTerm(language, 'status', actual.status),
    });
    return granted ? `${head}${language === 'en' ? ': ' : '：'}${granted}` : head;
  }
  if (actual.operation === 'tests.create')
    return t('actualTests', {
      n: integer(values.count) ?? 1,
      status: outcomeTerm(language, 'test', actual.status),
      v: integer(values.config_version) ?? '?',
    });
  if (actual.operation === 'submissions.create')
    return t('actualSubmission', {
      v: integer(values.version) ?? '?',
      decision: outcomeTerm(language, 'decision', String(values.decision ?? '')),
    });
  return t(actual.status === 'revoked' ? 'actualShareRevoked' : 'actualShare', {
    v: integer(values.version) ?? '?',
    role: outcomeTerm(language, 'role', String(values.recipient_role ?? '')),
  });
}

/** Build the block with plain DOM; the caller owns placement and removal. */
export function renderOutcome(doc: Document, view: OutcomeView, language: OutcomeLanguage) {
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const section = el('section', '', 'w03-outcome');
  section.dataset.outcomePreview = view.main.status;
  section.setAttribute('aria-label', view.main.heading);
  section.append(...previewNodes(el, view.main, true));
  if (view.earlier.length) {
    const older = el('details', '', 'w03-outcome-earlier');
    older.append(el('summary', view.earlierLabel));
    for (const entry of view.earlier) {
      const item = el('details', '', 'w03-outcome-earlier-item');
      item.dataset.outcomeEarlier = entry.view.status;
      item.append(el('summary', `${entry.label} · ${entry.view.statusLabel}`));
      item.append(...previewNodes(el, entry.view, false));
      older.append(item);
    }
    section.append(older);
  }
  section.lang = language === 'en' ? 'en' : 'zh-CN';
  return section;
}

type Make = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  cls?: string,
) => HTMLElementTagNameMap[K];

function previewNodes(el: Make, view: PreviewView, primary: boolean): HTMLElement[] {
  const nodes: HTMLElement[] = [];
  const list = (lines: string[], cls = '') => {
    const node = el('ul', '', cls);
    node.append(...lines.map((line) => el('li', line)));
    return node;
  };
  const box = (name: string, label: string, ...children: HTMLElement[]) => {
    const node = el('div', '', `w03-outcome-${name}`);
    node.dataset[`outcome${name[0].toUpperCase()}${name.slice(1)}`] = '';
    node.append(el('strong', label), ...children);
    return node;
  };
  if (primary) {
    const head = el('header', '', 'w03-outcome-head');
    const badge = el('span', view.statusLabel, `w03-outcome-badge ${view.status}`);
    badge.dataset.outcomeStatus = view.status;
    head.append(el('h3', view.heading, 'w03-outcome-title'), badge);
    nodes.push(head);
  }
  nodes.push(el('p', [view.version, ...view.meta].join(' · '), 'w03-outcome-meta'));
  const summary = el('p', '', 'w03-outcome-summary');
  summary.append(el('strong', view.response));
  nodes.push(summary);
  const items = el('ul', '', 'w03-outcome-items');
  for (const outcome of view.outcomes) {
    const item = el('li', '', `w03-outcome-item ${outcome.kind}`);
    item.dataset.outcomeKind = outcome.kind;
    item.append(el('span', outcome.label, 'w03-outcome-kind'), el('span', outcome.summary));
    items.append(item);
  }
  nodes.push(items);
  if (view.carried) nodes.push(el('p', view.carried, 'w03-outcome-note'));
  if (view.draftNote) nodes.push(el('p', view.draftNote, 'w03-outcome-note'));
  if (view.questions.length)
    nodes.push(box('question', view.labels.question, ...view.questions.map((q) => el('p', q))));
  if (view.changes.length || view.newer) {
    const extra = [view.newer, view.refreshHint].filter((line): line is string => !!line);
    nodes.push(
      box(
        'changes',
        view.labels.changed,
        list(view.changes),
        ...extra.map((line) => el('p', line, 'muted')),
      ),
    );
  }
  if (view.actual.length) nodes.push(box('actual', view.labels.actual, list(view.actual)));
  const details = el('details', '', 'w03-outcome-details');
  details.append(el('summary', view.labels.details));
  for (const outcome of view.outcomes) {
    if (!outcome.conditions.length && !outcome.waitsFor) continue;
    const item = el('div', '', `w03-outcome-detail ${outcome.kind}`);
    item.append(el('span', outcome.label, 'w03-outcome-kind'));
    if (outcome.conditions.length)
      item.append(el('p', view.labels.conditions, 'muted'), list(outcome.conditions));
    if (outcome.waitsFor)
      item.append(el('p', `${view.labels.waitsFor} ${outcome.waitsFor}`, 'muted'));
    details.append(item);
  }
  details.append(el('p', view.basis, 'muted'));
  nodes.push(details);
  if (view.links.length) {
    const links = el('div', '', 'w03-outcome-links');
    links.append(el('p', view.labels.links, 'muted'));
    for (const link of view.links) {
      const button = el('button', link.label, 'btn quiet small');
      button.type = 'button';
      button.dataset.action = link.action;
      links.append(button);
    }
    nodes.push(links);
  }
  return nodes;
}
