/** One evidence picker for resource requests, challenges and work citations: passages the
 * person read, actual test runs and saved work versions. A test run or work version is cited
 * with the exact reference the server gives (objects.read `evidence_ref`); the browser never
 * computes one. Closing the picker keeps the current choice. */
import { locale, T } from './app/i18n';
import type { EvidenceRefV2, ObjectRef, WorkspaceProductRead } from './contracts-v2';
import { purposeName } from './features/feedback-native/short-summary';
import { outcomeTerm } from './features/workspace/native-v4/outcome-copy';
import type { EvidenceKind, EvidencePick, V4HostAdapter } from './v4-host';
import type { PublicObject } from './v4-host-operations';
import { sheetDialog } from './sheet-dialog';
import './evidence-picker.css';

export type PickerSources = {
  sessionId: string;
  /** Passages returned when the person read a document in this browser. */
  passages: readonly EvidenceRefV2[];
  /** "material:version" → title, as listed by the workspace timeline. */
  titles: Readonly<Record<string, string>>;
  /** The current version of each document. */
  current: Readonly<Record<string, number>>;
  /** Test objects in the order they were saved. */
  tests: readonly Pick<PublicObject, 'ref' | 'content'>[];
  products: readonly WorkspaceProductRead[];
};
export type PickerRow = {
  key: string;
  kind: EvidenceKind;
  /** A passage, a previously chosen citation, or the object to cite on confirmation. */
  ref: EvidenceRefV2 | ObjectRef;
  label: string;
  meta: string;
  checked: boolean;
};
export type PickerGroup = { title?: string; note?: string; key?: string; rows: PickerRow[] };
export type PickerSection = {
  kind: EvidenceKind;
  title: string;
  empty: string;
  groups: PickerGroup[];
};
/** Shows the sections; `confirm` turns checked rows into citations or rejects with a reason.
 * Resolves with the citations, or null when the person closes the picker. */
export type AskEvidence = (
  sections: PickerSection[],
  confirm: (rows: readonly PickerRow[]) => Promise<EvidenceRefV2[]>,
) => Promise<EvidenceRefV2[] | null>;

/** Everything a person can cite: read passages, actual test runs and saved work versions. */
export const EVIDENCE_KINDS: readonly EvidenceKind[] = ['material', 'test', 'product'];
const KINDS = EVIDENCE_KINDS;
type TestContent = { query?: unknown; status?: unknown; config_ref?: { config_version?: unknown } };
const offered = (pick: EvidencePick): EvidenceKind[] =>
  KINDS.filter((kind) => (pick.kinds?.length ? pick.kinds : ['material']).includes(kind));
const isKind = (kind: string): kind is EvidenceKind => (KINDS as readonly string[]).includes(kind);

/** Same cited thing: a passage by its exact span, other objects by their exact version. */
export function evidenceKey(ref: EvidenceRefV2 | ObjectRef): string {
  const base = [ref.kind, ref.object_id, ref.version];
  if (ref.kind === 'material' && 'quote' in ref && ref.quote)
    return JSON.stringify([...base, ref.span_start ?? null, ref.span_end ?? null, ref.quote]);
  if (ref.kind === 'config') return JSON.stringify([...base, ref.config_version ?? null]);
  return JSON.stringify(base);
}
/** The bound practice changed while the person was choosing or reading; nothing was added. */
export const practiceChanged = () =>
  Error(T('练习已切换，请核对后继续。', 'The practice changed. Check it before continuing.'));
// Documents and settings keep "vN"; a work's version is "第 N 版" / "version N".
const documentTitle = (title: string, version: number) =>
  T(`《${title}》· v${version}`, `“${title}” · v${version}`);
const versionText = (version: number) => T(`第 ${version} 版`, `version ${version}`);
const documentVersion = (version: number) => `v${version}`;

export function pickerSections(sources: PickerSources, pick: EvidencePick): PickerSection[] {
  const kinds = offered(pick);
  const language = locale();
  const excluded = new Set((pick.exclude ?? []).map((ref) => `${ref.kind}:${ref.object_id}`));
  const selected = new Map((pick.selected ?? []).map((ref) => [evidenceKey(ref), ref]));
  const focus = pick.focus;
  const preselected = focus && focus.kind !== 'material' ? evidenceKey(focus) : '';
  const listed = new Set<string>();
  const row = (kind: EvidenceKind, ref: EvidenceRefV2 | ObjectRef, label: string, meta = '') => {
    const key = evidenceKey(ref);
    listed.add(key);
    return {
      key,
      kind,
      ref: selected.get(key) ?? ref,
      label,
      meta,
      checked: selected.has(key) || key === preselected,
    };
  };
  const allowed = (ref: { kind: string; object_id: string }) =>
    !excluded.has(`${ref.kind}:${ref.object_id}`);

  const documents = new Map<string, PickerGroup>();
  const documentGroup = (id: string, version: number) => {
    const key = `${id}:${version}`;
    let group = documents.get(key);
    if (!group) {
      group = {
        key,
        title: documentTitle(sources.titles[key] ?? T('资料', 'Document'), version),
        ...((sources.current[id] ?? version) > version
          ? { note: T('有新版本', 'Newer version') }
          : {}),
        rows: [],
      };
      documents.set(key, group);
    }
    return group;
  };
  for (const passage of sources.passages) {
    if (passage.session_id !== sources.sessionId || !passage.quote || !allowed(passage)) continue;
    if (listed.has(evidenceKey(passage))) continue;
    documentGroup(passage.object_id, passage.version).rows.push(
      row('material', passage, passage.quote),
    );
  }

  const runs = new Map<string, number>();
  const tests = sources.tests
    .filter((test) => test.ref.kind === 'test' && allowed(test.ref))
    .map((test) => {
      const content = test.content as TestContent;
      const query = typeof content.query === 'string' ? content.query : '';
      const run = (runs.get(query) ?? 0) + 1;
      runs.set(query, run);
      const config = content.config_ref?.config_version;
      const meta = [
        ...(Number.isInteger(config) ? [T(`配置 v${config}`, `config v${config}`)] : []),
        ...(typeof content.status === 'string'
          ? [outcomeTerm(language, 'test', content.status)]
          : []),
        T(`第 ${run} 次`, `run ${run}`),
      ].join(' · ');
      return row('test', test.ref, query || T('测试运行', 'Test run'), meta);
    })
    .reverse();

  const products = sources.products
    .filter((product) => !product.removed_at && product.session_id === sources.sessionId)
    .map((product) => ({
      product,
      ref: {
        session_id: product.session_id,
        kind: 'product',
        object_id: product.product_id,
        version: product.version,
      },
    }))
    .filter(({ ref }) => allowed(ref))
    .map(({ product, ref }) => {
      const title = product.title || T('未命名作品', 'Untitled work');
      const unchecked =
        product.author.kind !== 'human' && product.adoption?.status !== 'adopted'
          ? [T('待你检查', 'To check')]
          : [];
      return row(
        'product',
        ref,
        T(`《${title}》`, `“${title}”`),
        [versionText(product.version), purposeName(product.purpose ?? '', language), ...unchecked]
          .filter(Boolean)
          .join(' · '),
      );
    });

  // A current choice stays visible and checked even when its source is no longer listed.
  const unlisted = { test: [] as PickerRow[], product: [] as PickerRow[] };
  for (const ref of pick.selected ?? []) {
    if (!isKind(ref.kind) || !kinds.includes(ref.kind) || listed.has(evidenceKey(ref))) continue;
    if (ref.kind === 'material')
      documentGroup(ref.object_id, ref.version).rows.push(
        row('material', ref, ref.quote || documentVersion(ref.version)),
      );
    else
      unlisted[ref.kind].push(
        row(
          ref.kind,
          ref,
          ref.kind === 'test' ? T('测试运行', 'Test run') : T('作品', 'Work'),
          ref.kind === 'test' ? documentVersion(ref.version) : versionText(ref.version),
        ),
      );
  }

  const groups = [...documents.values()];
  if (focus?.kind === 'material') {
    const exact = groups.filter((g) => g.key === `${focus.object_id}:${focus.version}`);
    const same = exact.length
      ? exact
      : groups.filter((g) => g.key?.startsWith(`${focus.object_id}:`));
    groups.splice(0, groups.length, ...same, ...groups.filter((g) => !same.includes(g)));
  }
  const sections: Record<EvidenceKind, PickerSection> = {
    material: {
      kind: 'material',
      title: T('读过的资料段落', 'Passages you read'),
      empty: T(
        '先打开并阅读一份资料，再选择其中的段落。',
        'Read a document first, then choose a passage.',
      ),
      groups,
    },
    test: {
      kind: 'test',
      title: T('测试运行', 'Test runs'),
      empty: T(
        '还没有测试运行。在测试台运行后可以引用。',
        'No test runs yet. Run one on the test bench to cite it.',
      ),
      groups: [{ rows: [...tests, ...unlisted.test] }],
    },
    product: {
      kind: 'product',
      title: T('作品版本', 'Work versions'),
      empty: T('还没有其他已保存的作品。', 'No other saved work yet.'),
      groups: [{ rows: [...products, ...unlisted.product] }],
    },
  };
  return kinds.map((kind) => sections[kind]);
}

export async function pickerSources(
  host: V4HostAdapter,
  kinds: readonly EvidenceKind[],
): Promise<PickerSources> {
  const session = host.snapshot().session;
  if (session?.protocol !== 2) throw practiceChanged();
  const sessionId = session.sessionId;
  const timeline = await host.query('timeline');
  const products = kinds.includes('product')
    ? ((await host.query('work_products.list', { limit: 100 })).items ?? [])
    : [];
  return {
    sessionId,
    passages: (host.draft<EvidenceRefV2[]>('workspace', 'evidence-cache') ?? []).filter(
      (ref) => ref.kind === 'material',
    ),
    titles: timeline.workspace?.material_titles ?? {},
    current: timeline.workspace?.source_versions ?? {},
    tests: kinds.includes('test') ? (timeline.objects ?? []) : [],
    products,
  };
}

const sameObject = (a: EvidenceRefV2, b: ObjectRef) =>
  a.session_id === b.session_id &&
  a.kind === b.kind &&
  a.object_id === b.object_id &&
  a.version === b.version &&
  Number.isInteger(a.observed_at_seq) &&
  a.observed_at_seq >= 0;

/** Passages and earlier citations stay as they are; new tests and work get the server's ref. */
async function cite(host: V4HostAdapter, rows: readonly PickerRow[]): Promise<EvidenceRefV2[]> {
  const refs: EvidenceRefV2[] = [];
  let unverified = 0;
  for (const row of rows) {
    if ('observed_at_seq' in row.ref) {
      refs.push(row.ref);
      continue;
    }
    const target = row.ref;
    const found = await host
      .query('objects.read', {
        session_id: target.session_id,
        kind: target.kind,
        object_id: target.object_id,
        version: target.version,
      })
      .then((read) => read.evidence_ref)
      .catch(() => undefined);
    if (found && sameObject(found, target)) refs.push(found);
    else unverified++;
  }
  if (unverified)
    throw Error(
      T(
        `有 ${unverified} 项暂时无法核对确切版本，没有加入。`,
        `${unverified} item(s) could not be verified at their exact version and were not added.`,
      ),
    );
  return refs;
}

/** Load the sources, ask the person, and return their choice (unchanged when they close it). */
export async function pickEvidence(
  host: V4HostAdapter,
  pick: EvidencePick,
  ask: AskEvidence,
): Promise<EvidenceRefV2[]> {
  const kinds = offered(pick);
  const sections = pickerSections(await pickerSources(host, kinds), pick);
  const kept = (pick.selected ?? []).filter(
    (ref) => !isKind(ref.kind) || !kinds.includes(ref.kind),
  );
  const chosen = await ask(sections, async (rows) => {
    const refs = [...kept, ...(await cite(host, rows))];
    return [...new Map(refs.map((ref) => [evidenceKey(ref), ref])).values()];
  });
  return chosen ?? [...(pick.selected ?? [])];
}

/** "Selected evidence: 2 passages · 1 test run · 1 work version". */
export function evidenceSummary(refs: readonly (EvidenceRefV2 | ObjectRef)[]): string {
  const count = (kind: string) => refs.filter((ref) => ref.kind === kind).length;
  const [passages, tests, works] = KINDS.map(count);
  const other = refs.length - passages - tests - works;
  const parts = [
    passages ? T(`${passages} 段资料`, `${passages} passage${passages > 1 ? 's' : ''}`) : '',
    tests ? T(`${tests} 次测试`, `${tests} test run${tests > 1 ? 's' : ''}`) : '',
    works ? T(`${works} 份作品`, `${works} work version${works > 1 ? 's' : ''}`) : '',
    other ? T(`${other} 项其他依据`, `${other} other`) : '',
  ].filter(Boolean);
  return parts.length
    ? T('已选依据：', 'Selected evidence: ') + parts.join(' · ')
    : T('还没有选择依据', 'No evidence selected');
}

/** The picker dialog in the existing sheet style. */
export function evidenceSheet(doc: Document): AskEvidence {
  return (sections, confirm) =>
    new Promise((resolve) => {
      const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
        const node = doc.createElement(tag);
        node.textContent = text;
        node.className = className;
        return node;
      };
      const sheet = sheetDialog(T('选择依据', 'Choose evidence'), {
        doc,
        className: 'evidence-picker',
      });
      const { element: dialog, body, foot } = sheet;
      const id = sheet.heading.id;
      const boxes: [HTMLInputElement, PickerRow][] = [];
      sections.forEach((section, index) => {
        const block = el('section', '', 'evidence-picker__section');
        const title = el('h3', section.title);
        title.id = `${id}-${index}`;
        block.setAttribute('aria-labelledby', title.id);
        block.append(title);
        const rows = section.groups.flatMap((group) => group.rows);
        if (!rows.length) block.append(el('p', section.empty, 'meta'));
        for (const group of section.groups) {
          if (!group.rows.length) continue;
          const list = el('div', '', 'evidence-picker__group');
          if (group.title) {
            const caption = el('h4', group.title);
            if (group.note) caption.append(' ', el('span', group.note, 'tag'));
            list.append(caption);
          }
          for (const row of group.rows) {
            const label = el('label', '', 'check');
            const box = el('input');
            box.type = 'checkbox';
            box.checked = row.checked;
            label.append(box, el('span', row.label));
            if (row.meta) label.append(el('small', row.meta));
            list.append(label);
            boxes.push([box, row]);
          }
          block.append(list);
        }
        body.append(block);
      });
      const status = el('span', '', 'foot-note');
      status.setAttribute('aria-live', 'polite');
      const error = el('p', '', 'inline-alert');
      error.setAttribute('role', 'alert');
      error.hidden = true;
      const use = el('button', T('使用选中的依据', 'Use selected evidence'), 'btn primary');
      use.type = 'button';
      const count = () => {
        const n = boxes.filter(([box]) => box.checked).length;
        status.textContent = T(`已选 ${n} 项`, `${n} selected`);
      };
      body.addEventListener('change', count);
      let done = false;
      use.onclick = () => {
        use.disabled = true;
        error.hidden = true;
        confirm(boxes.filter(([box]) => box.checked).map(([, row]) => row)).then(
          (refs) => {
            done = true;
            resolve(refs);
            dialog.close();
          },
          (failure: unknown) => {
            error.textContent =
              failure instanceof Error
                ? failure.message
                : T('依据暂时无法加入。', 'The evidence could not be added.');
            error.hidden = false;
            use.disabled = false;
          },
        );
      };
      foot.append(status, use);
      foot.before(error);
      dialog.addEventListener(
        'close',
        () => {
          if (!done) resolve(null);
        },
        { once: true },
      );
      count();
      dialog.showModal();
    });
}

/** Answers the host's `v4-choose-evidence` request for the bound practice. */
export function answerEvidenceRequest(
  getHost: () => V4HostAdapter | null,
  event: Event,
  ask: AskEvidence = evidenceSheet(document),
): void {
  const detail = (event as CustomEvent).detail,
    host = getHost();
  if (!host) return;
  if (host.snapshot().session?.protocol !== 2) return;
  detail.handled = true;
  const sessionId = detail.sessionId;
  void (async () => {
    if (sessionId !== host.snapshot().session?.sessionId) throw practiceChanged();
    const chosen = await pickEvidence(host, detail.pick ?? {}, ask);
    if (getHost()?.snapshot().session?.sessionId !== sessionId) throw practiceChanged();
    return chosen;
  })().then(detail.resolve, detail.reject);
}
