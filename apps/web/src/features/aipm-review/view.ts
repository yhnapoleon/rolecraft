/** The section review screen: what was written (read-only, sentence by sentence when the
 * recognition layer is on) beside the review. It is the result page made small: the sentence
 * lens, rule lines, item rows and the three colleague columns are the result page's own
 * renderers and classes, called here without changing how the result page uses them. */
import type { PreviewRecognition } from '../recognition-native/chain';
import { renderSentenceLens } from '../recognition-native/sentences';
import { renderItemRow, type ItemRow } from '../feedback-native/feedback-items';
import { criterionLabels } from '../feedback-native/criteria';
import { renderRuleLines, ruleLines } from '../feedback-native/rule-lines';
import type { Report } from '../feedback-native/index';
import { COLLEAGUE_NAMES, colleagueRemit, type Colleague } from '../../screens/result/colleagues';
import {
  colleagueKey,
  coverageRow,
  deltaLine,
  groupSentences,
  type Language,
  nextStatusHint,
  orderCoverage,
  sectionPreview,
  STATUSES,
  staleNote,
  statusName,
  stepName,
  text,
} from './model';
import type { SectionReview, StepId } from './types';
import '../../screens/result/result.css';
import './review.css';

/** The sentence step: off, running, ready (the whole PRD's preview), failed, or refused. */
export type Sentences =
  | { kind: 'off' }
  | { kind: 'running' }
  | { kind: 'ready'; preview: PreviewRecognition }
  | { kind: 'failed' }
  | { kind: 'submitted' }
  | { kind: 'no_decision' };

export type ReviewViewInput = {
  review: SectionReview;
  language: Language;
  /** The PRD version's seven section texts, as saved. */
  sections: Partial<Record<StepId, string>>;
  sentences: Sentences;
  /** The latest saved PRD version, to say "you have edited since". */
  currentPrdVersion?: number | null;
  previousVersion?: number | null;
  /** Whether a launch decision has been chosen on ⑦ (⑤⑥ rubric lines need it). */
  hasDecision?: boolean;
  onAsk?: (who: Colleague) => void;
  onBack?: () => void;
};

type Tag = keyof HTMLElementTagNameMap;

export function renderReview(doc: Document, input: ReviewViewInput): HTMLElement {
  const { review, language } = input;
  const t = (zh: string, en: string) => text(language, zh, en);
  const el = <K extends Tag>(tag: K, value = '', cls = '') => {
    const node = doc.createElement(tag);
    if (value) node.textContent = value;
    if (cls) node.className = cls;
    return node;
  };
  const button = (label: string, cls: string, onClick?: () => void) => {
    const node = el('button', label, cls);
    node.type = 'button';
    if (onClick) node.addEventListener('click', onClick);
    return node;
  };
  const ask = (who: Colleague) => input.onAsk?.(who);
  const open = new Set<string>();
  const hooks = {
    id: `aipm-review-${review.id}`,
    isOpen: (key: string) => open.has(key),
    onToggle: (key: string, value: boolean) => (value ? open.add(key) : open.delete(key)),
  };

  const root = el('section', '', 'aipm-review native-feedback');
  root.lang = language;
  root.dataset.aipmReview = review.step_id;
  root.dataset.status = review.status;
  const grid = el('div', '', 'aipm-review__grid');

  // ---- What you wrote ----
  const paper = el('article', '', 'aipm-review__paper');
  paper.append(
    el(
      'p',
      t(
        `你写的 · 第 ${review.prd_ref.version} 版（只读，回去修改可编辑）`,
        `What you wrote · version ${review.prd_ref.version} (read-only; go back to edit)`,
      ),
      'aipm-review__eyebrow',
    ),
    el('h2', stepName(review.step_id, language), 'aipm-review__title'),
  );
  const written = input.sections[review.step_id] ?? '';
  const plain = () => {
    const box = el('div', '', 'aipm-review__plain');
    const paragraphs = written.split(/\n+/).filter((line) => line.trim());
    if (!paragraphs.length)
      box.append(el('p', t('这一节还是空的。', 'This section is empty.'), 'aipm-review__muted'));
    for (const line of paragraphs) box.append(el('p', line));
    return box;
  };
  const pass = input.sentences;
  if (pass.kind === 'ready') {
    const groups = groupSentences(pass.preview.units ?? [], input.sections);
    const own = groups.bySection[review.step_id] ?? [];
    paper.append(
      own.length
        ? renderSentenceLens(doc, {
            language,
            preview: sectionPreview(pass.preview, own),
            frame: 'flat',
            replay: false,
          })
        : plain(),
    );
    if (groups.unassigned.length) {
      const rest = el('details', '', 'aipm-review__unassigned');
      rest.append(
        el(
          'summary',
          t(
            `另有 ${groups.unassigned.length} 句没能归到某一节`,
            `${groups.unassigned.length} sentence${groups.unassigned.length > 1 ? 's' : ''} not placed in a section`,
          ),
        ),
        renderSentenceLens(doc, {
          language,
          preview: sectionPreview(pass.preview, groups.unassigned),
          frame: 'flat',
          replay: false,
        }),
      );
      paper.append(rest);
    }
  } else {
    paper.append(plain());
  }
  const sentenceNote: Record<Sentences['kind'], string> = {
    ready: t(
      '逐句标注来自识别层（句子与资料对照，本地模型，不是语言模型）。',
      'Sentence marks come from the recognition layer (sentences against sources; a local model, not a language model).',
    ),
    off: t(
      '逐句标注未开启：识别层没有打开，这里不画线，只显示右侧的规则核对。',
      'Sentence marks are off: the recognition layer is not on, so nothing is underlined; the rule checks on the right still apply.',
    ),
    running: t('正在逐句对照资料…', 'Checking sentence by sentence against the sources…'),
    failed: t(
      '逐句对照这次没有完成，不能视为通过。右侧的规则核对不受影响。',
      'The sentence check did not finish; this is not a pass. The rule checks on the right are unaffected.',
    ),
    submitted: t(
      '这一局已交付。先在结果页开始修订，才能逐句对照。',
      'This practice is delivered. Start a revision on the result page to check sentences.',
    ),
    no_decision: t(
      '到 ⑦ 选一个拟定决定后，才能逐句对照。',
      'Choose a proposed decision on ⑦ to check sentences.',
    ),
  };
  paper.append(el('p', sentenceNote[pass.kind], 'aipm-review__note'));

  // ---- The review ----
  const sheet = el('article', '', 'aipm-review__sheet');
  const head = el('header', '', 'aipm-review__head');
  const heading = el('div', '', 'aipm-review__heading');
  const chip = el('span', statusName(review.status, language), 'aipm-review__chip');
  chip.dataset.status = review.status;
  heading.append(el('h3', t('批改单', 'Review'), 'aipm-review__name'), chip);
  const time = new Date(review.created_at);
  const clock = Number.isNaN(time.getTime())
    ? ''
    : ` · ${time.toLocaleTimeString(language === 'zh' ? 'zh-CN' : 'en-GB', { hour: '2-digit', minute: '2-digit' })}`;
  head.append(
    heading,
    el(
      'span',
      t(`对应第 ${review.prd_ref.version} 版`, `For version ${review.prd_ref.version}`) + clock,
      'aipm-review__meta',
    ),
  );
  sheet.append(head);

  const stale = staleNote(review, language, input.currentPrdVersion);
  if (stale) {
    const banner = el('p', stale.text, 'aipm-review__stale');
    banner.dataset.kind = stale.kind;
    banner.setAttribute('role', 'status');
    sheet.append(banner);
  }

  const steps = el('div', '', 'aipm-review__steps');
  steps.setAttribute('role', 'img');
  steps.setAttribute(
    'aria-label',
    t(
      `状态：${statusName(review.status, language)}`,
      `Status: ${statusName(review.status, language)}`,
    ),
  );
  STATUSES.forEach((status, index) => {
    if (index) steps.append(el('span', '', 'aipm-review__rule'));
    const pill = el('span', statusName(status, language), 'aipm-review__step');
    if (status === review.status) pill.dataset.current = '';
    else if (STATUSES.indexOf(status) < STATUSES.indexOf(review.status)) pill.dataset.passed = '';
    steps.append(pill);
  });
  steps.append(el('span', nextStatusHint(review, language), 'aipm-review__hint'));
  sheet.append(steps);
  const delta = deltaLine(review, language, input.previousVersion);
  if (delta) sheet.append(el('p', delta, 'aipm-review__delta'));

  const section = (title: string, ...nodes: Node[]) => {
    const box = el('section', '', 'aipm-review__part');
    box.append(el('h4', title, 'aipm-review__label'), ...nodes);
    sheet.append(box);
    return box;
  };

  // Misconceptions: the first one is what to fix first.
  if (review.misconceptions.length) {
    const cards = review.misconceptions.map((item, index) => {
      const card = el('div', '', 'aipm-review__mis');
      if (index === 0) card.dataset.first = '';
      card.dataset.finding = item.finding;
      card.append(el('p', item.message, 'aipm-review__mis-title'));
      for (const ref of item.basis_refs ?? [])
        if (ref.quote)
          card.append(
            el(
              'p',
              t(
                `资料原句：${ref.quote} · v${ref.version}`,
                `Source: ${ref.quote} · v${ref.version}`,
              ),
              'aipm-review__mis-line',
            ),
          );
      card.append(
        el(
          'p',
          t(`核对范围：${item.checked_scope}`, `Checked: ${item.checked_scope}`),
          'aipm-review__mis-line',
        ),
      );
      if (item.next_action?.label)
        card.append(
          el(
            'p',
            t(`再看看：${item.next_action.label}`, `Look again: ${item.next_action.label}`),
            'aipm-review__mis-line',
          ),
        );
      return card;
    });
    section(
      t('先改这一条 · 常见误区（规则判定）', 'Fix this first · common misconception (rule check)'),
      ...cards,
    );
  }

  // Coverage, worst first, as the result page's rows.
  if (review.coverage.length) {
    const list = el('ul', '', 'fb-list aipm-review__coverage');
    for (const item of orderCoverage(review.coverage)) {
      const row = coverageRow(item, language);
      const asked = row.mark === 'unknown' ? colleagueKey(item.owner) : null;
      list.append(
        renderItemRow(doc, row, language, {
          ...hooks,
          action: () =>
            asked
              ? button(
                  t(`问 ${COLLEAGUE_NAMES[asked]}`, `Ask ${COLLEAGUE_NAMES[asked]}`),
                  'btn quiet small',
                  () => ask(asked),
                )
              : null,
        }),
      );
    }
    section(
      t('要点覆盖（按严重程度，不给答案）', 'Coverage (most serious first; no answers given)'),
      list,
    );
  }

  // The formal criteria this section answers to: rule findings now, the rest at delivery.
  const items = review.rubric.map(
    (line) =>
      ({
        criterion: line.criterion,
        label: line.label,
        source: line.source,
        explanation: line.explanation,
        applicability: 'applicable',
      }) as unknown as Report['items'][number],
  );
  // Pending criteria are named once below, as judged at delivery.
  const verified = items.filter((item) => item.source === 'verified_rule');
  const lines = renderRuleLines(
    doc,
    ruleLines(verified, criterionLabels(language), language),
    language,
  );
  const pending = review.rubric.filter((line) => line.source !== 'verified_rule');
  const rubricNodes: Node[] = lines ? [lines] : [];
  if (pending.length)
    rubricNodes.push(
      el(
        'p',
        t(
          `交付时由正式反馈判断：${pending.map((p) => criterionLabels(language)[p.criterion] ?? p.criterion).join('、')}`,
          `Judged by the formal feedback at delivery: ${pending.map((p) => criterionLabels(language)[p.criterion] ?? p.criterion).join(', ')}`,
        ),
        'aipm-review__muted',
      ),
    );
  if (
    (review.step_id === 'solution' || review.step_id === 'assurance') &&
    input.hasDecision === false
  )
    rubricNodes.push(
      el(
        'p',
        t(
          '到 ⑦ 选一个拟定决定后，可以核对容量与资源。',
          'Choose a proposed decision on ⑦ to check capacity and resources.',
        ),
        'aipm-review__muted',
      ),
    );
  if (rubricNodes.length)
    section(t('对应的正式评价项', 'Formal criteria for this section'), ...rubricNodes);

  // What each colleague would ask: a preset question per person, then a way to really ask.
  if (review.mentor_prompts.length) {
    const columns = el('div', '', 'result-colleagues aipm-review__mentors');
    for (const who of ['manager', 'business', 'technical'] as Colleague[]) {
      const prompt = review.mentor_prompts.find((p) => colleagueKey(p.colleague) === who);
      if (!prompt) continue;
      const box = el('section', '', 'result-colleague aipm-review__mentor');
      box.dataset.person = who;
      const top = el('header', '', 'result-colleague__head');
      const avatar = el('span', COLLEAGUE_NAMES[who][0], 'result-colleague__avatar');
      avatar.setAttribute('aria-hidden', 'true');
      const id = el('div', '', 'result-colleague__who');
      id.append(
        el('h3', COLLEAGUE_NAMES[who], 'result-colleague__name'),
        el('p', colleagueRemit(who, language), 'result-colleague__remit'),
      );
      top.append(avatar, id);
      const quote = el('blockquote', prompt.question, 'aipm-review__question');
      const go = button(
        t(
          `问 ${COLLEAGUE_NAMES[who]}（附上第 ${review.prd_ref.version} 版）`,
          `Ask ${COLLEAGUE_NAMES[who]} (with version ${review.prd_ref.version})`,
        ),
        'aipm-review__ask',
        () => ask(who),
      );
      box.append(top, quote, go);
      columns.append(box);
    }
    section(
      t('同事会怎么看 · 预设提示', 'How colleagues would see it · preset prompts'),
      columns,
      el(
        'p',
        t(
          '按这次批改触发的预设提问，不是同事的实时回复；点「问」会打开对话，由同事真正回答。',
          'Preset questions triggered by this review, not live replies. “Ask” opens the conversation, where the colleague really answers.',
        ),
        'aipm-review__muted',
      ),
    );
  }

  const foot = el('footer', '', 'aipm-review__foot');
  foot.append(
    el(
      'p',
      t(
        '规则核对与识别标注，没有调用语言模型 · 不计入正式评分',
        'Rule checks and recognition marks; no language model was called · not part of the formal score',
      ),
      'aipm-review__muted',
    ),
  );
  const actions = el('div', '', 'aipm-review__actions');
  const top = orderCoverage(review.coverage).find((c) => c.mark !== 'covered');
  const first: Colleague = top ? colleagueKey(top.owner) : 'manager';
  actions.append(
    button(
      t(`请 ${COLLEAGUE_NAMES[first]} 看看这条`, `Ask ${COLLEAGUE_NAMES[first]} about this`),
      'btn',
      () => ask(first),
    ),
    button(t('回去修改', 'Back to edit'), 'btn primary', () => input.onBack?.()),
  );
  foot.append(actions);
  sheet.append(foot);

  grid.append(paper, sheet);
  root.append(grid);
  return root;
}

export type { ItemRow };
