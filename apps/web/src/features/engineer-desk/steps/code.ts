/** The coding exercise under "fix & trial": the engineer (or their Coding Agent) writes
 * `current_limit`, the platform runs it in an isolated process on fixed cases, public ones row
 * by row and hidden ones as a count (engineer/coding.py). The latest run rides along the next
 * draft, so the sheet and the review name the code that was handed in. */
import { T } from '../../../app/i18n';
import { failureText, type EngineerApi } from '../api';
import { chip, key, setBusy } from '../bits';
import { el, fill } from '../dom';
import type { CodeCase, CodeRead, CodeRun, CodeRunSummary, CodeShape } from '../model';

const storeKey = (ticketId: string) => `rolecraft.engineer.code.${ticketId}`;

function remembered(ticketId: string): string | null {
  try {
    return localStorage.getItem(storeKey(ticketId));
  } catch {
    return null;
  }
}

function remember(ticketId: string, code: string) {
  try {
    localStorage.setItem(storeKey(ticketId), code);
  } catch {
    /* Private windows: the code still lives in the box. */
  }
}

/** A returned value as one line: `answered · 400 · policy v2`. */
export function shapeText(value: CodeShape | null | undefined): string {
  if (!value) return T('没有返回', 'nothing returned');
  const status = typeof value.status === 'string' ? value.status : JSON.stringify(value.status);
  if (status === 'fallback') return 'fallback';
  const where = value.source ? ` · ${value.source} v${value.version ?? '?'}` : '';
  return `${status} · ${value.value ?? '—'}${where}`;
}

export class CodePanel {
  readonly element: HTMLElement;
  private readonly box: HTMLTextAreaElement;
  private readonly runKey: HTMLButtonElement;
  private readonly resetKey: HTMLButtonElement;
  private readonly task: HTMLElement;
  private readonly status: HTMLElement;
  private readonly results: HTMLElement;
  private skeleton = '';
  private latest: CodeRun | null = null;
  private busy = false;
  /** The newest run the panel has drawn: a newer one (say, from the Agent) is read again. */
  private shownRun = '';

  constructor(
    private readonly doc: Document,
    private readonly api: EngineerApi,
    private readonly ticketId: string,
    title: string,
  ) {
    this.task = el(doc, 'p', { class: 'ed-code__task' });
    this.box = el(doc, 'textarea', {
      class: 'ed-code__box',
      id: 'ed-code-box',
      spellcheck: 'false',
      autocomplete: 'off',
      rows: 18,
      'aria-label': T('你的代码', 'Your code'),
      lang: 'en',
    });
    this.box.addEventListener('input', () => remember(this.ticketId, this.box.value));
    this.box.addEventListener('keydown', (event) => {
      if (event.key === 'Tab' && !event.shiftKey) {
        // Indent instead of leaving the box; Shift+Tab still leaves it.
        event.preventDefault();
        this.box.setRangeText('    ', this.box.selectionStart, this.box.selectionEnd, 'end');
        remember(this.ticketId, this.box.value);
      }
    });
    this.runKey = key(
      doc,
      T('运行用例', 'Run the cases'),
      'secondary',
      { id: 'ed-code-run' },
      'play',
    );
    this.runKey.addEventListener('click', () => void this.run());
    this.resetKey = key(
      doc,
      T('恢复骨架', 'Back to the skeleton'),
      'ghost',
      { id: 'ed-code-reset' },
      'refresh',
    );
    this.resetKey.addEventListener('click', () => {
      this.box.value = this.skeleton;
      remember(this.ticketId, this.box.value);
    });
    this.status = el(doc, 'p', { class: 'ed-meta', role: 'status' });
    this.results = el(doc, 'div', { class: 'ed-code__results' });
    this.element = el(
      doc,
      'section',
      { class: 'ed-code', 'aria-labelledby': 'ed-code-h' },
      el(doc, 'h3', { class: 'ed-label', id: 'ed-code-h' }, title),
      this.task,
      this.box,
      el(doc, 'div', { class: 'ed-step__do' }, this.runKey, this.resetKey),
      this.status,
      this.results,
    );
  }

  /** The run the next draft carries: the latest one, whoever ran it. */
  get runId(): string | null {
    return this.latest?.id ?? null;
  }

  async load() {
    try {
      this.accept(await this.api.code(this.ticketId), true);
    } catch (error) {
      this.status.textContent = failureText(error);
    }
  }

  /** The ticket's run list changed (the person, or their Agent over MCP): read the newest. */
  sync(runs: readonly CodeRunSummary[] | undefined) {
    const newest = runs?.at(-1)?.id ?? '';
    if (!newest || newest === this.shownRun || this.busy) return;
    void this.api
      .code(this.ticketId)
      .then((read) => this.accept(read, false))
      .catch(() => undefined);
  }

  private accept(read: CodeRead, first: boolean) {
    const { exercise } = read;
    this.skeleton = exercise.skeleton;
    this.task.textContent = exercise.task;
    const run = read.latest_code_run;
    if (first) {
      this.box.value = remembered(this.ticketId) ?? run?.code ?? exercise.skeleton;
    } else if (run && run.executor.kind !== 'human' && run.code) {
      // The Agent's newest code replaces the box, so the person reads what was run.
      this.box.value = run.code;
      remember(this.ticketId, run.code);
    }
    this.latest = run;
    this.shownRun = run?.id ?? '';
    this.draw(exercise.public_cases, exercise.hidden_cases);
  }

  private cases: readonly CodeCase[] = [];
  private hiddenTotal = 0;

  private draw(cases?: readonly CodeCase[], hidden?: number) {
    if (cases) this.cases = cases;
    if (hidden !== undefined) this.hiddenTotal = hidden;
    const doc = this.doc;
    const run = this.latest;
    const rows = new Map((run?.public ?? []).map((row) => [row.id, row]));
    const byAgent = run && run.executor.kind !== 'human';
    this.status.textContent = run
      ? [
          byAgent
            ? T('最近一次由你的 Agent 运行：', 'Last run by your agent: ')
            : T('最近一次运行：', 'Last run: '),
          T(
            `公开 ${run.counts.passed}/${run.counts.total}，隐藏 ${run.hidden.passed}/${run.hidden.total}`,
            `public ${run.counts.passed}/${run.counts.total}, hidden ${run.hidden.passed}/${run.hidden.total}`,
          ),
          run.status === 'completed' ? '' : T('（没有跑完）', ' (did not finish)'),
          run.all_passed
            ? T('。保存草稿时会附进交回单。', '. It rides along your next draft.')
            : T('。还有没过的用例。', '. Some cases still fail.'),
        ].join('')
      : T(
          `还没运行。公开用例 ${this.cases.length} 条，另有 ${this.hiddenTotal} 条隐藏用例只给通过数。`,
          `Not run yet. ${this.cases.length} public cases; ${this.hiddenTotal} hidden ones report only a count.`,
        );
    fill(
      this.results,
      el(
        doc,
        'ol',
        { class: 'ed-code__list' },
        ...this.cases.map((c) => {
          const row = rows.get(c.id);
          return el(
            doc,
            'li',
            { class: 'ed-code__row', 'data-result': row?.result ?? 'unknown' },
            el(doc, 'code', { class: 'ed-key', lang: 'en' }, c.id),
            el(
              doc,
              'div',
              { class: 'ed-code__what' },
              el(doc, 'span', { class: 'ed-code__point' }, c.point),
              el(doc, 'span', { class: 'ed-code__q' }, c.question),
              el(
                doc,
                'span',
                { class: 'ed-code__io', lang: 'en' },
                T('应返回 ', 'should return ') + shapeText(c.should_return),
                row && row.result !== 'pass'
                  ? el(
                      doc,
                      'span',
                      { class: 'ed-code__got' },
                      row.error ? row.error : T('实际 ', 'got ') + shapeText(row.actual),
                    )
                  : null,
              ),
            ),
            row
              ? chip(
                  doc,
                  row.result === 'pass'
                    ? T('通过', 'Pass')
                    : row.result === 'error'
                      ? T('出错', 'Error')
                      : T('不对', 'Wrong'),
                  row.result === 'pass' ? 'good' : 'warn',
                )
              : chip(doc, T('未运行', 'Not run'), 'unknown'),
          );
        }),
      ),
      run?.printed ? el(doc, 'pre', { class: 'ed-code__printed', lang: 'en' }, run.printed) : null,
    );
  }

  private async run() {
    if (this.busy) return;
    this.busy = true;
    setBusy(this.runKey, true);
    this.status.textContent = T('在隔离进程里运行…', 'Running in an isolated process…');
    try {
      this.latest = await this.api.codeRun(this.ticketId, this.box.value);
      this.shownRun = this.latest.id;
      this.draw();
    } catch (error) {
      this.status.textContent = failureText(error);
    } finally {
      this.busy = false;
      setBusy(this.runKey, false);
    }
  }
}
