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

/** A supplied document version's formal title. Historical references keep their recorded
 * version's name; a document published only in Chinese keeps its Chinese title. */
export function documentName(title: unknown): string | undefined {
  // Earlier scenario packages appended the version stage to the title; the version shows it.
  const name = typeof title === 'string' ? title.replace(/(初始版|更新版)$/, '').trim() : '';
  return name || undefined;
}

/** What one catalog is built from, whether read from the timeline or from the workbench. */
export type CatalogSource = {
  /** 'id:version' -> the title of every readable document version. */
  materialTitles?: Readonly<Record<string, unknown>>;
  /** Tests in the order they ran. */
  tests?: readonly { id: string; query: string }[];
  /** Timeline events: history references, and deliveries in the order they were submitted. */
  events?: readonly unknown[];
  products?: readonly ProductTitle[];
};

export function buildCatalog(source: CatalogSource): ReferenceCatalog {
  const materialTitles: Record<string, string> = {};
  for (const [key, title] of Object.entries(source.materialTitles ?? {}))
    if (typeof title === 'string' && title) materialTitles[key] = title;
  const tests: Record<string, { query: string; run: number }> = {};
  const runs = new Map<string, number>();
  for (const test of source.tests ?? []) {
    const query = test.query.trim();
    if (!query || test.id in tests) continue;
    const run = (runs.get(query) ?? 0) + 1;
    runs.set(query, run);
    tests[test.id] = { query, run };
  }
  const events: Record<string, ServerEvent> = {};
  const deliveries: Record<string, number> = {};
  const ordered = list(source.events)
    .map(row)
    .sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0));
  for (const event of ordered) {
    if (typeof event.type !== 'string') continue;
    const refs = list(event.refs).map(row);
    if (typeof event.id === 'string')
      events[event.id] = {
        type: event.type,
        data: row(event.data),
        refs: refs as unknown as ServerEvent['refs'],
      };
    // Deliveries are numbered in the order they were submitted.
    const submission = refs.find((ref) => ref.kind === 'submission')?.object_id;
    if (event.type === 'submitted' && typeof submission === 'string' && !(submission in deliveries))
      deliveries[submission] = Object.keys(deliveries).length + 1;
  }
  const titles: Record<string, string> = {};
  for (const product of source.products ?? [])
    if (product.title) titles[`${product.product_id}:${product.version}`] = product.title;
  return { materialTitles, tests, deliveries, events, products: titles };
}

export function readCatalog(
  timeline: unknown,
  products: readonly ProductTitle[] = [],
): ReferenceCatalog {
  const source = page(timeline);
  // The server lists objects in the order they were created.
  const tests = list(source.objects).flatMap((object) => {
    const ref = row(row(object).ref),
      content = row(row(object).content);
    return ref.kind === 'test' &&
      typeof ref.object_id === 'string' &&
      typeof content.query === 'string'
      ? [{ id: ref.object_id, query: content.query }]
      : [];
  });
  return buildCatalog({
    materialTitles: row(row(source.workspace).material_titles),
    tests,
    events: list(source.events),
    products,
  });
}

/** A document's name: the formal title of its current (latest readable) version. */
export function catalogMaterialTitle(catalog: ReferenceCatalog, id: string, version?: number): string | undefined {
  if (version !== undefined) return documentName(catalog.materialTitles[`${id}:${version}`]);
  const latest = Object.keys(catalog.materialTitles)
    .filter((key) => key.startsWith(`${id}:`))
    .sort((a, b) => Number(b.slice(id.length + 1)) - Number(a.slice(id.length + 1)))[0];
  return latest ? documentName(catalog.materialTitles[latest]) : undefined;
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
