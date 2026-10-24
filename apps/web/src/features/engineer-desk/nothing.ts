/** "Nothing to fix in this practice" (189's decision, rework r3 §1). Shown in the intro's place
 * when the person puts on the engineer's hat in a practice whose problem is gone: the index was
 * refreshed to the new policy, or the settings already warn. No ticket is opened (a delivered
 * practice opens no revision). The same sheet of paper as the intro, centred, with two ways on:
 * a new practice as the engineer (the problem is always there in a new one), or back to the test
 * bench as the product manager to hand over a failure of their own. The two ways are stacked,
 * the ink one first, both ending on the paper's right edge. */
import { T } from '../../app/i18n';
import { runAction } from '../../shell';
import { failureText } from './api';
import { chip, key, setBusy } from './bits';
import { el, iconNode } from './dom';
import { arrive, move, spring } from './motion';
import type { PracticeFacts } from './need';

export interface NothingContext {
  readonly doc: Document;
  /** The practice's facts as read now: why there is nothing to fix. */
  readonly facts: PracticeFacts;
  /** Product manager's hat, test bench. */
  toBench(): void;
  notify(text: string): void;
}

/** One short line on why: the index is current, or the settings warn about stale sources. */
function reason(f: PracticeFacts): string | null {
  if (f.policyVersion != null && f.indexVersion != null && f.indexVersion >= f.policyVersion)
    return T(
      `差旅政策 v${f.policyVersion} · 索引 v${f.indexVersion}，已是最新`,
      `Travel policy v${f.policyVersion} · index v${f.indexVersion}, up to date`,
    );
  if (f.freshnessGuard === 'warn')
    return T('设置会在资料过期时提醒', 'The settings warn when a source is out of date');
  if (f.freshnessGuard === 'fallback')
    return T('资料过期时转人工回答', 'Out-of-date sources go to a person');
  return null;
}

export class NothingScreen {
  readonly element: HTMLElement;

  constructor(private readonly ctx: NothingContext) {
    this.element = el(ctx.doc, 'div', { class: 'ed ed-intro ed-nothing' });
    this.draw();
    this.enter();
  }

  destroy() {}

  private draw() {
    const doc = this.ctx.doc;
    const start = key(
      doc,
      T('新开一局当工程师', 'Start a new practice as the engineer'),
      'primary',
      {
        id: 'ed-nothing-start',
      },
    );
    start.addEventListener('click', () => {
      if (start.getAttribute('aria-busy') === 'true') return;
      setBusy(start, true);
      start.disabled = true;
      runAction('engineer-start').catch((error: unknown) => {
        setBusy(start, false);
        start.disabled = false;
        this.ctx.notify(failureText(error));
      });
    });
    const bench = key(
      doc,
      T('去测试台，交一条失败给工程', 'Go to the test bench and hand over a failure'),
      'secondary',
      { id: 'ed-nothing-bench' },
    );
    bench.addEventListener('click', () => this.ctx.toBench());
    const why = reason(this.ctx.facts);
    this.element.replaceChildren(
      el(
        doc,
        'article',
        { class: 'ed-intro__paper ed-nothing__paper', 'aria-labelledby': 'ed-title' },
        el(doc, 'p', { class: 'ed-eyebrow' }, T('工程委托', 'Engineering ticket')),
        el(
          doc,
          'h1',
          { class: 'ed-intro__title', id: 'ed-title', tabindex: '-1' },
          T('这一局没有要修的委托', 'Nothing to fix in this practice'),
        ),
        el(
          doc,
          'p',
          { class: 'ed-intro__lead' },
          T(
            '这一局助手已经按新政策回答，没有要修的问题。',
            'In this practice the assistant already answers from the new policy; there’s nothing broken to fix.',
          ),
        ),
        why
          ? el(
              doc,
              'p',
              { class: 'ed-nothing__why' },
              chip(doc, [iconNode(doc, 'check', 'i-xs'), why], 'good'),
            )
          : null,
        el(doc, 'footer', { class: 'ed-nothing__keys' }, start, bench),
      ),
    );
  }

  /** Once: the paper rises (the same entrance as the intro). */
  private enter() {
    move(
      this.element.querySelector('.ed-intro__paper'),
      { opacity: [0, 1], transform: ['translateY(12px)', 'translateY(0)'] },
      { duration: 0.52, ease: spring },
    );
    arrive(this.element.querySelector('.ed-nothing__why'), 6, { delay: 0.12 });
  }
}
