/** What a practice can name about the objects it refers to: document titles per version, test
 * questions with their run number, delivery order, work titles and the events behind history
 * references. Built from the timeline read the workbench already makes; never from server prose
 * or guessed versions. */
import {
  describeServerEvent,
  type CopyLanguage,
  type EventLookups,
  type ServerEvent,
} from './app/event-copy';

type Row = Record<string, unknown>;
export type ReferenceCatalog = {
  /** 'id:version' -> title, for every document version the learner can read. */
  materialTitles: Readonly<Record<string, string>>;
  /** Test ID -> its question and which run of that question it was (1-based), when known. */
  tests: Readonly<Record<string, { query: string; run?: number }>>;
  /** Submission ID -> which delivery of this practice it was (1-based). */
  deliveries: Readonly<Record<string, number>>;
  /** Event ID -> the event, for history references. */
  events: Readonly<Record<string, ServerEvent>>;
  /** 'productId:version' -> work title. */
  products: Readonly<Record<string, string>>;
};
export type ProductTitle = { product_id: string; version: number; title?: string | null };

const row = (value: unknown): Row =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/** The timeline page itself, through the usual V2Response `result` envelopes. */
function page(value: unknown): Row {
  let current = row(value);
  for (let depth = 0; depth < 4; depth++) {
    if ('events' in current || 'objects' in current || 'workspace' in current) return current;
    current = row(current.result);
  }
  return {};
}

export function readCatalog(
  timeline: unknown,
  products: readonly ProductTitle[] = [],
): ReferenceCatalog {
  const source = page(timeline);
  const materialTitles: Record<string, string> = {};
  for (const [key, title] of Object.entries(row(row(source.workspace).material_titles)))
    if (typeof title === 'string' && title) materialTitles[key] = title;
  const tests: Record<string, { query: string; run: number }> = {};
  const runs = new Map<string, number>();
  const deliveries: Record<string, number> = {};
  // The server lists objects in the order they were created.
  for (const object of list(source.objects)) {
    const ref = row(row(object).ref),
      content = row(row(object).content),
      id = ref.object_id;
    if (typeof id !== 'string') continue;
    if (ref.kind === 'test' && typeof content.query === 'string' && !(id in tests)) {
      const query = content.query.trim();
      const run = (runs.get(query) ?? 0) + 1;
      runs.set(query, run);
      tests[id] = { query, run };
    }
    if (ref.kind === 'submission' && !(id in deliveries))
      deliveries[id] = Object.keys(deliveries).length + 1;
  }
  const events: Record<string, ServerEvent> = {};
  for (const value of list(source.events)) {
    const event = row(value);
    if (typeof event.id === 'string' && typeof event.type === 'string')
      events[event.id] = {
        type: event.type,
        data: row(event.data),
        refs: list(event.refs).map(row) as unknown as ServerEvent['refs'],
      };
  }
  const titles: Record<string, string> = {};
  for (const product of products)
    if (product.title) titles[`${product.product_id}:${product.version}`] = product.title;
  return { materialTitles, tests, deliveries, events, products: titles };
}

/** A document's title at a version, else at its latest readable version. */
export function catalogMaterialTitle(
  catalog: ReferenceCatalog,
  id: string,
  version?: number,
): string | undefined {
  if (version !== undefined && catalog.materialTitles[`${id}:${version}`])
    return catalog.materialTitles[`${id}:${version}`];
  const latest = Object.keys(catalog.materialTitles)
    .filter((key) => key.startsWith(`${id}:`))
    .sort((a, b) => Number(b.slice(id.length + 1)) - Number(a.slice(id.length + 1)))[0];
  return latest ? catalog.materialTitles[latest] : undefined;
}

export function catalogLookups(catalog: ReferenceCatalog): EventLookups {
  return {
    materialTitle: (id, version) => catalogMaterialTitle(catalog, id, version),
    testQuery: (id) => catalog.tests[id]?.query,
    deliveryNumber: (id) => catalog.deliveries[id],
  };
}

export type ReferenceKey = {
  readonly kind: string;
  readonly object_id: string;
  readonly version: number;
  readonly config_version?: number | null;
};
/** `text` fits a button; `full` is the whole name; `label` adds the action, for screen readers. */
export type ReferenceLabel = { text: string; full: string; label: string };

// Button text stays about one line in the feedback column; Latin text takes less room.
const SHORT = { zh: 24, en: 40 } as const;

/** What an evidence reference points at, by name and version. */
export function referenceLabel(
  ref: ReferenceKey,
  catalog: ReferenceCatalog,
  language: CopyLanguage,
): ReferenceLabel {
  const say = (zh: string, en: string) => (language === 'en' ? en : zh);
  const limit = SHORT[language];
  const clip = (value: string) => (value.length > limit ? `${value.slice(0, limit - 1)}…` : value);
  const named = (full: string, short = full): ReferenceLabel => ({
    text: short,
    full,
    label: say('打开依据：', 'Open evidence: ') + full,
  });
  const id = ref.object_id,
    v = ref.version;
  switch (ref.kind) {
    case 'material': {
      const title = catalogMaterialTitle(catalog, id, v);
      return title
        ? named(`${title} · v${v}`, `${clip(title)} · v${v}`)
        : named(say(`资料 · v${v}`, `Document · v${v}`));
    }
    case 'test': {
      const test = catalog.tests[id];
      if (!test) return named(say('一次测试', 'A test run'));
      const lead = say('测试：', 'Test: '),
        run = test.run === undefined ? '' : say(` · 第 ${test.run} 次`, ` · run ${test.run}`);
      return named(lead + test.query + run, lead + clip(test.query) + run);
    }
    case 'product': {
      const title =
        catalog.products[`${id}:${v}`] ??
        Object.entries(catalog.products).find(([key]) => key.startsWith(`${id}:`))?.[1];
      if (!title) return named(say(`作品 · v${v}`, `Work · v${v}`));
      const full = (name: string) => say(`作品《${name}》· v${v}`, `Work “${name}” · v${v}`);
      return named(full(title), full(clip(title)));
    }
    case 'config': {
      const n = ref.config_version ?? v;
      return named(say(`配置 v${n}`, `Config v${n}`));
    }
    case 'submission': {
      const n = catalog.deliveries[id];
      return named(
        n === undefined
          ? say('交付记录', 'Delivery record')
          : say(`第 ${n} 次交付`, `Delivery ${n}`),
      );
    }
    case 'event': {
      const event = catalog.events[id];
      return named(
        event
          ? describeServerEvent(event, catalogLookups(catalog), language).text
          : say('历史记录', 'History record'),
      );
    }
    case 'role_reply':
      return named(say('同事回复', 'Colleague reply'));
    case 'role_turn':
      return named(say('你的提问', 'Your question'));
    case 'review':
      return named(say(`评审请求 · v${v}`, `Review request · v${v}`));
    case 'business_request':
      return named(say('资源申请', 'Resource request'));
    case 'business_decision':
      return named(say('审批决定', 'Approval decision'));
    case 'feedback_response':
      return named(say('你的补充', 'Your response'));
  }
  return named(say(`依据 · v${v}`, `Evidence · v${v}`));
}
