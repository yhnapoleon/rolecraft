/** The section review screen: what was written (read-only, sentence by sentence when the
 * recognition layer is on) beside the review. The look follows the v2 wireframe (5-批改结果);
 * the structure is the result page's: its sentence tones, rule lines, item rows and colleague
 * colours, called here without changing how the result page uses them. */
import { renderEvidenceCheck } from '../recognition-native/evidence-check';
import { checkPresentation } from '../recognition-native/check-presentation';
import type { ChainUnit, PreviewRecognition } from '../recognition-native/chain';
import { toneOf } from '../recognition-native/sentence-view';
import { renderItemRow, type ItemRow } from '../feedback-native/feedback-items';
import { criterionLabels } from '../feedback-native/criteria';
import { renderRuleLines, ruleLines } from '../feedback-native/rule-lines';
import type { Report } from '../feedback-native/index';
import { COLLEAGUE_NAMES, type Colleague } from '../../screens/result/colleagues';
import {
  colleagueKey,
  defaultAngle,
  coverageRow,
  deltaLine,
  groupSentences,
  ownSentences,
  writtenBlocks,
  coverageMarkName,
  materialOf,
  mergedCoverage,
  modelPart,
  shownStatus,
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
import 'number-flow';
import './review.css';

/** The sentence step: off, running, ready (the whole PRD's preview), failed, or refused. */
export type Sentences =
  | { kind: 'off' }
  | { kind: 'running' }
  | { kind: 'ready'; preview: PreviewRecognition }
  | { kind: 'failed' }
  | { kind: 'submitted' };

export type ReviewViewInput = {
  review: SectionReview;
  language: Language;
  /** The PRD version's seven section texts, as saved. */
  sections: Partial<Record<StepId, string>>;
  sentences: Sentences;
  previousVersion?: number | null;
  /** Whether a launch decision has been chosen on ⑦ (⑤⑥ rubric lines need it). */
  hasDecision?: boolean;
  onAsk?: (who: Colleague) => void;
  onBack?: () => void;
  /** What this screen showed for the same review just before, so changes can move. */
  previous?: { status: SectionReview['status']; delta?: SectionReview['delta'] } | null;
  /** A running model look was followed for its time limit without a result. */
  modelTimedOut?: boolean;
  /** Opens a named material beside the sheet. */
  onOpenMaterial?: (id: string) => void;
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
  // The status with the model's verdicts counted, once its look has finished.
  const current = shownStatus(review);
  root.dataset.status = current;
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
  const blocks = writtenBlocks(written);
  // One line per sentence: underline and numbered mark by the recognizer's relation, the
  // matched source sentence opened in place (the lens's tones, drawn as the wireframe does).
  const sentenceList = (units: readonly ChainUnit[], start = 0) => {
    const list = el('ol', '', 'aipm-review__sentences');
    units.forEach((unit, at) => {
      const index = start + at;
      const presentation = checkPresentation(unit, input.sentences.kind === 'ready' ? input.sentences.preview : {}, language);
      const tone = presentation.state === 'unknown' ? 'insufficient' : toneOf(unit);
      const row = el('li', '', 'aipm-review__sent');
      row.dataset.tone = tone;
      const words = button('', 'aipm-review__s');
      words.append(
        el('span', `${index + 1}. ${presentation.status}: `, 'sr-only'),
        el('span', unit.quote, 'aipm-review__u'),
      );
      const mark = el('span', String(index + 1), 'aipm-review__n');
      mark.setAttribute('aria-hidden', 'true');
      const inspector = el('dialog', '', 'aipm-inspector');
      const heading = el('header', '', 'aipm-inspector__head');
      const meta = el('div', '', 'aipm-inspector__meta');
      const title = el('h3', unit.quote, 'aipm-inspector__quote');
      title.id = `inspect-${review.id}-${unit.index}-${index}`;
      inspector.setAttribute('aria-labelledby', title.id);
      const close = button(
        t('关闭', 'Close'),
        'aipm-inspector__close',
        () => inspector.close(),
      );
      meta.append(
        el('span', t(`第 ${review.prd_ref.version} 版`, `Version ${review.prd_ref.version}`)),
        el('span', presentation.status),
        close,
      );
      heading.append(meta, title);
      const body = el('div', '', 'aipm-inspector__body');
      if (input.sentences.kind === 'ready')
        body.append(renderEvidenceCheck(doc, unit, input.sentences.preview, language, unit.source?.kind === 'material' && !!unit.source.object_id && !!input.onOpenMaterial));
      body.addEventListener('click', event => {
        const sourceLink = (event.target as Element)?.closest?.('.ec-source');
        if (!sourceLink) return;
        const material = unit.source?.kind === 'material' ? unit.source.object_id : null;
        inspector.close();
        if (material && input.onOpenMaterial) {event.preventDefault();input.onOpenMaterial(material);}
      });
      inspector.append(heading, body);
      inspector.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') event.stopPropagation();
      });
      words.setAttribute('aria-haspopup', 'dialog');
      words.setAttribute('aria-expanded', 'false');
      let scroll: { node: Element; top: number; left: number }[] = [];
      inspector.addEventListener('close', () => {
        words.setAttribute('aria-expanded', 'false');
        words.focus({ preventScroll: true });
        for (const { node, top, left } of scroll) {
          node.scrollTop = top;
          node.scrollLeft = left;
        }
      });
      words.addEventListener('click', () => {
        scroll = [];
        for (let node = words.parentElement; node; node = node.parentElement) {
          scroll.push({ node, top: node.scrollTop, left: node.scrollLeft });
        }
        inspector.showModal();
        words.setAttribute('aria-expanded', 'true');
        title.tabIndex = -1;
        title.focus({ preventScroll: true });
      });
      row.append(words, mark, inspector);
      list.append(row);
    });
    return list;
  };
  const legend = (units: readonly ChainUnit[]) => {
    const box = el('p', '', 'aipm-review__legend');
    const tones = ['supported', 'contradicted', 'insufficient'] as const;
    for (const tone of [
      ...tones,
      ...(units.some((u) => toneOf(u) === 'deferred') ? (['deferred'] as const) : []),
    ]) {
      const key = el('span', '', 'aipm-review__key');
      key.dataset.tone = tone;
      key.append(el('i'), checkPresentation({label:tone,decision:tone==='deferred'?'defer':'decide'} as ChainUnit,{},language).status);
      box.append(key);
    }
    return box;
  };
  // What was written, block by block as the sheet shows it: headings and quotes keep their own
  // look and are never marked; only the learner's own sentences are numbered and underlined.
  const writtenView = (units: readonly ChainUnit[]) => {
    const box = el('div', '', 'aipm-review__written');
    if (!blocks.length)
      box.append(el('p', t('这一节还是空的。', 'This section is empty.'), 'aipm-review__muted'));
    const left = [...ownSentences(units, blocks)];
    let numbered = 0;
    for (const block of blocks) {
      if (block.type === 'h') box.append(el('h4', block.text, 'aipm-review__h'));
      else if (block.type === 'quote') {
        const quote = el('blockquote', '', 'aipm-review__quote');
        quote.append(el('p', block.text));
        if (block.source) quote.append(el('cite', `— ${block.source}`));
        box.append(quote);
      } else {
        const body = squashText(block.text);
        const mine = left.filter((unit) => body.includes(squashText(unit.quote)));
        for (const unit of mine) left.splice(left.indexOf(unit), 1);
        if (mine.length) {
          box.append(sentenceList(mine, numbered));
          numbered += mine.length;
        } else box.append(el('p', block.text, 'aipm-review__plain'));
      }
    }
    // Sentences the recognizer split differently from the paragraphs, kept rather than lost.
    if (left.length) box.append(sentenceList(left, numbered));
    return { box, numbered: numbered + left.length };
  };
  const pass = input.sentences;
  if (pass.kind === 'ready') {
    const groups = groupSentences(pass.preview.units ?? [], input.sections);
    const own = sectionPreview(pass.preview, groups.bySection[review.step_id] ?? []).units ?? [];
    const shown = writtenView(own);
    paper.append(shown.box, ...(shown.numbered ? [legend(own)] : []));
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
        sentenceList(sectionPreview(pass.preview, groups.unassigned).units ?? []),
      );
      paper.append(rest);
    }
  } else {
    paper.append(writtenView([]).box);
  }
  const sentenceNote: Record<Sentences['kind'], string> = {
    ready: t(
      '点一句话，看看本次选中的原文，再决定怎么改。',
      'Select a claim to compare its saved source, then decide what to change.',
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
  };
  paper.append(el('p', sentenceNote[pass.kind], 'aipm-review__note'));

  // ---- The review ----
  const sheet = el('article', '', 'aipm-review__sheet');
  const head = el('header', '', 'aipm-review__head');
  const heading = el('div', '', 'aipm-review__heading');
  const chip = el('span', statusName(current, language), 'aipm-review__chip');
  chip.dataset.status = current;
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
  if (input.sentences.kind === 'ready') {
    const targeted = sectionPreview(input.sentences.preview, groupSentences(input.sentences.preview.units ?? [], input.sections).bySection[review.step_id] ?? []).units ?? [];
    const summary = el('section', '', 'aipm-evidence-summary');
    summary.append(el('h4', t('依据核对', 'Evidence check')));
    const found = ownSentences(targeted.length ? targeted : (input.sentences.preview.units ?? []).filter(u => written.includes(u.quote)), blocks);
    const rank = (unit: ChainUnit) => unit.decision === 'defer' ? 0 : unit.label === 'contradicted' ? 1 : unit.label === 'insufficient' ? 2 : 3;
    const ordered = [...found].sort((a,b) => rank(a)-rank(b));
    for (const [at,unit] of ordered.entries()) {
      const p = checkPresentation(unit, input.sentences.preview, language);
      const open = () => {
        const triggers = [...paper.querySelectorAll<HTMLButtonElement>('.aipm-review__s')];
        triggers.find(key => key.textContent?.includes(unit.quote))?.click();
      };
      if (at) {
        const compact = button('', 'aipm-evidence-summary__compact', open);
        compact.append(el('span', unit.quote),el('small',p.status));
        summary.append(compact);
      } else {
        const item = el('div', '', 'aipm-evidence-summary__item');
        item.append(el('p', p.status, 'ec-caption'), el('h4', t('先核对这句话的依据', 'Review the source for this claim')), el('blockquote', unit.quote), el('p', p.hint));
        item.append(button(t('展开原句与依据 →', 'Compare claim and source →'), 'ec-source', open));
        summary.append(item);
      }
    }
    if(found.length) sheet.append(summary);
  }

  const stale = staleNote(review, language);
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
    t(`状态：${statusName(current, language)}`, `Status: ${statusName(current, language)}`),
  );
  // Three steps on one track; a dark knob marks the current one and slides (spring) when the
  // status changes. While the model is still looking, the third step says so instead.
  const looking = modelPart(review).status === 'running';
  const track = el('div', '', 'aipm-review__track');
  const knob = el('span', '', 'aipm-review__knob');
  knob.setAttribute('aria-hidden', 'true');
  track.append(knob);
  const pills = new Map<string, HTMLElement>();
  STATUSES.forEach((status, index) => {
    if (index) track.append(el('span', '', 'aipm-review__rule'));
    const label =
      looking && status === 'solid'
        ? t('模型细看中', 'Model looking')
        : statusName(status, language);
    const pill = el('span', label, 'aipm-review__step');
    if (status === current) pill.dataset.current = '';
    else if (STATUSES.indexOf(status) < STATUSES.indexOf(current)) pill.dataset.passed = '';
    if (looking && status === 'solid') pill.dataset.looking = '';
    pills.set(status, pill);
    track.append(pill);
  });
  steps.append(track, el('span', nextStatusHint(review, language), 'aipm-review__hint'));
  sheet.append(steps);
  slideKnob(doc, track, knob, pills.get(input.previous?.status ?? current), pills.get(current));
  const delta = deltaLine(review, language, input.previousVersion);
  if (delta) {
    const line = el('p', '', 'aipm-review__delta');
    // The before → after counts carry the weight of the line; a changed "after" rolls.
    const before = deltaLine({ ...review, delta: input.previous?.delta ?? null }, language);
    const was = before ? [...before.matchAll(/\d+ → (\d+)/g)].map((m) => Number(m[1])) : [];
    let at = 0;
    for (const part of delta.split(/(\d+ → \d+)/)) {
      const pair = part.match(/^(\d+) → (\d+)$/);
      if (!pair) {
        line.append(part);
        continue;
      }
      const b = el('b', `${pair[1]} → `);
      b.append(rollingCount(doc, Number(pair[2]), was[at++]));
      line.append(b);
    }
    sheet.append(line);
  }

  const section = (title: string, ...nodes: Node[]) => {
    const box = el('section', '', 'aipm-review__part');
    box.append(el('h4', title, 'aipm-review__label'), ...nodes);
    sheet.append(box);
    return box;
  };

  const tag = () =>
    el('span', t('模型判断 · 建议', 'Model judgement · advice'), 'aipm-review__model-tag');

  // Misconceptions: the first one is what to fix first. Rule findings come before the model's,
  // and a model finding is never presented as a rule check.
  const byModel = (item: { source: string }) => item.source === 'model_suggestion';
  const misconceptions = [
    ...(review.misconceptions ?? []).filter((m) => !byModel(m)),
    ...(review.misconceptions ?? []).filter(byModel),
  ];
  if (misconceptions.length) {
    const cards = misconceptions.map((item, index) => {
      const card = el('div', '', 'aipm-review__mis');
      if (index === 0) card.dataset.first = '';
      card.dataset.finding = item.finding;
      // Title: the point's name in red (a rule finding is its own short name); then the
      // model's words in plain ink, the source sentence in the serif, scope and next step.
      const model = byModel(item);
      const head = el('div', '', 'aipm-review__mis-head');
      head.append(
        el(
          'p',
          model && item.checked_scope ? item.checked_scope : item.message,
          'aipm-review__mis-title',
        ),
      );
      if (model) {
        card.dataset.source = 'model';
        head.append(tag());
      }
      card.append(head);
      if (model && item.checked_scope) card.append(el('p', item.message, 'aipm-review__mis-body'));
      for (const ref of item.basis_refs ?? [])
        if (ref.quote)
          card.append(
            el(
              'p',
              t(
                `资料原句：${ref.quote} · v${ref.version}`,
                `Source: ${ref.quote} · v${ref.version}`,
              ),
              'aipm-review__mis-quote',
            ),
          );
      if (!model)
        card.append(
          el(
            'p',
            t(`核对范围：${item.checked_scope}`, `Checked: ${item.checked_scope}`),
            'aipm-review__mis-line',
          ),
        );
      // The finding's own next step: a link to the material it names, or its words.
      const material = materialOf(item.basis_refs);
      if (item.next_action?.label)
        card.append(
          material && input.onOpenMaterial
            ? button(item.next_action.label, 'aipm-review__link', () =>
                input.onOpenMaterial?.(material),
              )
            : el('p', item.next_action.label, 'aipm-review__mis-line'),
        );
      return card;
    });
    section(
      misconceptionTitle(
        misconceptions.some((m) => !byModel(m)),
        misconceptions.some(byModel),
        language,
      ),
      ...cards,
    );
  }

  // Coverage, worst first, as the result page's rows. Rule results show at once; the model's
  // look fills in the points only it can judge, marked as advice, without holding the rest.
  const model = modelPart(review);
  const coverage = mergedCoverage(review);
  const modelLine =
    model.status === 'running' && input.modelTimedOut
      ? t(
          '模型还在看，稍后回来查看。规则判定已在下面。',
          'The model is still looking; come back later. Rule results are below.',
        )
      : model.status === 'running'
        ? t(
            '模型细看中…规则判定已先列出，模型的判断稍后补进来。',
            'The model is looking… Rule results are listed first; the model’s judgement follows.',
          )
        : model.status === 'failed'
          ? // The server's reason is its own sentence (an interrupted look says to send it again).
            t(
              `模型细看没有完成。${sentence(model.error ?? '原因未返回', '。')}下面是规则判定。`,
              `The model look did not finish. ${sentence(model.error ?? 'No reason was returned', '.')} Rule results are below.`,
            )
          : null;
  if (coverage.length || modelLine) {
    const list = el('ul', '', 'fb-list aipm-review__coverage');
    for (const item of orderCoverage(coverage)) {
      const row = coverageRow(item, language, model.status);
      const asked = row.mark === 'unknown' ? colleagueKey(item.owner) : null;
      const shown = row.mark === 'unknown' ? 'to_check' : item.mark;
      const li = renderItemRow(doc, row, language, {
        ...hooks,
        action: () => {
          if (asked)
            return button(
              t(`问 ${COLLEAGUE_NAMES[asked]}`, `Ask ${COLLEAGUE_NAMES[asked]}`),
              'btn quiet small',
              () => ask(asked),
            );
          const material = materialOf(item.pointer?.refs);
          return material && input.onOpenMaterial
            ? button(t('看资料', 'Open source'), 'btn quiet small', () =>
                input.onOpenMaterial?.(material),
              )
            : null;
        },
      });
      // The row's round mark becomes the wireframe's word pill: 有误 / 缺了 / 待核对 / 覆盖了.
      li.dataset.coverage = shown;
      const mark = findClass(li, 'fb-mark');
      if (mark) {
        mark.textContent = coverageMarkName(shown, language);
        mark.className = 'fb-mark aipm-review__pill';
      }
      if (item.byModel) {
        li.dataset.source = 'model';
        findClass(li, 'fb-item__name')?.append(tag());
      }
      list.append(li);
    }
    const status = modelLine ? el('p', modelLine, 'aipm-review__model-status') : null;
    if (status) {
      status.dataset.model = model.status;
      status.setAttribute('role', 'status');
    }
    section(
      t('要点覆盖（按严重程度，不给答案）', 'Coverage (most serious first; no answers given)'),
      ...(status ? [status] : []),
      ...(coverage.length ? [list] : []),
    );
  }

  // The formal criteria this section answers to: rule findings now, the rest at delivery.
  const items = (review.rubric ?? []).map(
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
  // The model's reading of criteria the rules leave to delivery, kept apart from rule findings.
  const advised = model.status === 'done' ? model.rubric : [];
  const advisedLines = renderRuleLines(
    doc,
    ruleLines(
      advised.map(
        (line) =>
          ({
            ...line,
            source: 'verified_rule',
            applicability: 'applicable',
          }) as unknown as Report['items'][number],
      ),
      criterionLabels(language),
      language,
    ),
    language,
  );
  const pending = (review.rubric ?? []).filter(
    (line) =>
      line.source !== 'verified_rule' && !advised.some((a) => a.criterion === line.criterion),
  );
  const rubricNodes: Node[] = lines ? [lines] : [];
  if (advisedLines) {
    const box = el('div', '', 'aipm-review__advised');
    box.dataset.source = 'model';
    box.append(tag(), advisedLines);
    rubricNodes.push(box);
  }
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

  // What each colleague would ask: all three are always there. A preset question shows when
  // this review triggered one; otherwise the colleague's usual angle on this sheet, and a
  // lighter way to ask.
  {
    const columns = el('div', '', 'aipm-review__mentors');
    for (const who of ['manager', 'business', 'technical'] as Colleague[]) {
      const prompt = (review.mentor_prompts ?? []).find((p) => colleagueKey(p.colleague) === who);
      // The result page's person colours (data-person) on the wireframe's compact card.
      const box = el('section', '', 'result-colleague aipm-review__mentor');
      box.dataset.person = who;
      if (!prompt) box.dataset.preset = 'none';
      const top = el('p', '', 'aipm-review__who');
      const avatar = el('span', COLLEAGUE_NAMES[who][0], 'result-colleague__avatar');
      avatar.setAttribute('aria-hidden', 'true');
      top.append(avatar, el('b', COLLEAGUE_NAMES[who]));
      const said = prompt
        ? el('blockquote', `“${prompt.question}”`, 'aipm-review__question')
        : el(
            'p',
            t(
              `常从「${defaultAngle(review.step_id, who, language)}」看这张纸`,
              `Usually looks at ${defaultAngle(review.step_id, who, language).toLowerCase()}`,
            ),
            'aipm-review__angle',
          );
      const go = button(
        t(`问 ${COLLEAGUE_NAMES[who]}`, `Ask ${COLLEAGUE_NAMES[who]}`),
        prompt ? 'aipm-review__ask' : 'aipm-review__ask aipm-review__ask--light',
        () => ask(who),
      );
      const hint = prompt?.pointer?.text
        ? el(
            'p',
            t(`再看看：${prompt.pointer.text}`, `Look again: ${prompt.pointer.text}`),
            'aipm-review__muted',
          )
        : null;
      box.append(top, said, ...(hint ? [hint] : []), go);
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
      misconceptions.some(byModel) ||
        (model.status === 'done' && (model.coverage.length || model.rubric.length))
        ? t(
            '规则核对、识别标注与模型建议 · 模型的判断只是建议 · 不计入正式评分',
            'Rule checks, recognition marks and model advice · the model’s judgements are advice · not part of the formal score',
          )
        : t(
            '规则核对与识别标注，没有调用语言模型 · 不计入正式评分',
            'Rule checks and recognition marks; no language model was called · not part of the formal score',
          ),
      'aipm-review__muted',
    ),
  );
  const actions = el('div', '', 'aipm-review__actions');
  const top = orderCoverage(coverage).find((c) => c.mark !== 'covered');
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

/** The "fix this first" heading names where its findings come from. */
function misconceptionTitle(rule: boolean, model: boolean, language: Language) {
  const t = (zh: string, en: string) => text(language, zh, en);
  const from =
    rule && model
      ? t('规则判定与模型建议', 'rule check and model advice')
      : model
        ? t('模型建议', 'model advice')
        : t('规则判定', 'rule check');
  return t(`先改这一条 · 常见误区（${from}）`, `Fix this first · common misconception (${from})`);
}

const squashText = (value: string) => value.replace(/\s+/g, '');

/** Places the knob on the current step; from the previous step it slides there on the spring. */
function slideKnob(
  doc: Document,
  track: HTMLElement,
  knob: HTMLElement,
  from: HTMLElement | undefined,
  to: HTMLElement | undefined,
) {
  const frame = doc.defaultView?.requestAnimationFrame?.bind(doc.defaultView);
  if (!frame || !to) return;
  const place = (pill: HTMLElement) => {
    knob.style.width = `${pill.offsetWidth}px`;
    knob.style.transform = `translateX(${pill.offsetLeft}px)`;
  };
  frame(() => {
    if (!track.isConnected) return;
    knob.dataset.still = '';
    place(from ?? to);
    frame(() => {
      delete knob.dataset.still;
      place(to);
    });
  });
}

/** A count that rolls from its previous value with number-flow; plain text without it. */
function rollingCount(doc: Document, value: number, previous?: number) {
  const node = doc.createElement('number-flow') as HTMLElement & { update?: (v: number) => void };
  if (typeof node.update !== 'function') {
    node.textContent = String(value);
    return node;
  }
  node.update(previous ?? value);
  if (previous != null && previous !== value)
    doc.defaultView?.requestAnimationFrame(() => node.update?.(value));
  return node;
}

/** A reason as one sentence, ending with exactly one full stop. */
const sentence = (text: string, stop: string) =>
  `${text.trim().replace(/[。.！!；;]+$/, '')}${stop}`;

/** The first descendant with this class, in the page's DOM or the tests' text DOM. */
function findClass(node: Element, name: string): Element | null {
  for (const child of Array.from((node as { children?: ArrayLike<Element> }).children ?? [])) {
    if (
      String(child.className ?? '')
        .split(' ')
        .includes(name)
    )
      return child;
    const found = findClass(child, name);
    if (found) return found;
  }
  return null;
}

export type { ItemRow };
