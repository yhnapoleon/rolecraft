/** The compass (v2 spec §2): three segments, seven points lit by real work, one suggested next
 * step and the whole PRD. It never locks a step or shows a score; a point opens its sheet. */
import { Check, ChevronRight, Sparkle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Language } from './model';
import { type SheetRow, orderGlyph, sheetWords } from './sheets';
import './compass.css';
import './screen.css';

export type CompassProps = {
  language: Language;
  rows: SheetRow[];
  /** review: the suggestion points at the step's latest review rather than its sheet. */
  suggestion: { step: string; text: string; review?: boolean } | null;
  /** The sheet open in the main screen, if any. */
  current?: string;
  fixture?: boolean;
  stale?: boolean;
  updatedAt?: string;
  onOpen(step: string): void;
  onReview?(step: string): void;
  onPrd(): void;
  onRefresh(): void;
};

export function Compass(p: CompassProps) {
  const w = sheetWords(p.language);
  const en = p.language === 'en';
  const segments = (['clarify', 'design', 'verify'] as const).map((s) => ({
    id: s,
    label: w.segment[s],
    rows: p.rows.filter((r) => r.segment === s),
  }));
  const here = p.rows.find((r) => r.id === p.current) ?? p.rows.find((r) => r.suggested);
  const [list, setList] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!list) return;
    const down = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setList(false);
    };
    document.addEventListener('pointerdown', down, true);
    return () => document.removeEventListener('pointerdown', down, true);
  }, [list]);
  const say = (r: SheetRow) =>
    `${orderGlyph(r.order)} ${r.label} · ${r.statusText}${r.recheckReason ? ` · ${r.recheckReason}` : ''}`;
  return (
    <nav
      className="aipm-compass"
      aria-label={en ? 'Seven points of this practice' : '这一局的七个能力点'}
      ref={box}
    >
      <div className="aipm-compass__points">
        {segments.map((seg, i) => (
          <div className="aipm-compass__segment" key={seg.id} data-segment={seg.id}>
            {i > 0 && <span className="aipm-compass__rule" aria-hidden="true" />}
            <span className="aipm-compass__segment-label">{seg.label}</span>
            {seg.rows.map((r) => (
              <button
                type="button"
                key={r.id}
                className="aipm-compass__point"
                data-status={r.status}
                aria-current={r.id === p.current ? 'page' : undefined}
                aria-label={say(r)}
                title={say(r)}
                onClick={() => p.onOpen(r.id)}
              >
                <span className="aipm-compass__dot" data-status={r.status}>
                  {r.status === 'solid' ? (
                    <Check size={11} strokeWidth={3} aria-hidden="true" />
                  ) : r.status === 'recheck' ? (
                    '!'
                  ) : (
                    r.order
                  )}
                </span>
                {r.agentDraft && (
                  <span className="aipm-compass__agent" aria-hidden="true">
                    <Sparkle size={7} strokeWidth={2.4} />
                  </span>
                )}
              </button>
            ))}
          </div>
        ))}
      </div>
      {/* Phone: one line for where you are; the seven points open below it. */}
      {here && (
        <button
          type="button"
          className="aipm-compass__here"
          aria-expanded={list}
          onClick={() => setList(!list)}
        >
          <span className="aipm-compass__dot" data-status={here.status}>
            {here.order}
          </span>
          {here.label} · {here.statusText}
          <ChevronRight size={14} aria-hidden="true" />
        </button>
      )}
      {list && (
        <ul className="aipm-compass__list">
          {p.rows.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => {
                  setList(false);
                  p.onOpen(r.id);
                }}
              >
                <span className="aipm-compass__dot" data-status={r.status}>
                  {r.status === 'solid' ? (
                    <Check size={11} strokeWidth={3} />
                  ) : r.status === 'recheck' ? (
                    '!'
                  ) : (
                    r.order
                  )}
                </span>
                <span>{r.label}</span>
                <small>{r.statusText}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {p.stale ? (
        <p className="aipm-compass__next" role="status">
          {en ? 'Progress is not up to date' : '进度暂未更新'}
          {p.updatedAt ? ` · ${p.updatedAt}` : ''}{' '}
          <button type="button" className="aipm-compass__link" onClick={p.onRefresh}>
            {en ? 'Refresh' : '重新读取'}
          </button>
        </p>
      ) : (
        p.suggestion && (
          <p className="aipm-compass__next">
            <span className="aipm-compass__next-label">{w.next}</span>
            <button
              type="button"
              className="aipm-compass__link"
              onClick={() => {
                const s = p.suggestion;
                if (s?.review && p.onReview) p.onReview(s.step);
                else if (s) p.onOpen(s.step);
              }}
            >
              {p.suggestion.text}
            </button>
          </p>
        )
      )}
      {p.fixture && (
        <span className="aipm-compass__fixture">
          {en ? 'Fake data · not connected' : '假数据 · 接口未就绪'}
        </span>
      )}
      <button type="button" className="aipm-compass__prd" onClick={p.onPrd}>
        {en ? 'Whole PRD' : '整份 PRD'}
        <ChevronRight size={14} aria-hidden="true" />
      </button>
    </nav>
  );
}
