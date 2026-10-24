// The manager's brief on the board (decision 8). On a new practice it is the first screen: the
// letter and four large readouts. Once the full brief has been read it rolls into one line and
// the readouts shrink to a row, so the board moves up. The learner can unroll it again.
import { T } from '../../app/i18n';

const unrolled = new Set<string>();
let rolling: string | null = null;

export const briefRolled = (attemptId: string, briefRead: boolean) =>
  briefRead && !unrolled.has(attemptId);

/** Flips the brief for this practice; the next board render plays the roll once. */
export function toggleBrief(attemptId: string) {
  if (unrolled.has(attemptId)) unrolled.delete(attemptId);
  else unrolled.add(attemptId);
  rolling = attemptId;
}
/** The brief was just read for the first time: roll it when the board shows again. */
export const briefJustRead = (attemptId: string) => {
  rolling = attemptId;
};
/** True once per roll: the render that should animate it. */
export function takeRoll(attemptId: string) {
  if (rolling !== attemptId) return false;
  rolling = null;
  return true;
}

// The one sentence that says what the job is: the one that hands the call to you
// ("… is your call.", "你来定"), cut to its first clause; else the first sentence.
export function briefKeyLine(quote: string) {
  const text = String(quote || '').trim();
  const sentences = text.split(/(?<=[。！？])|(?<=[.!?])\s+/).filter(Boolean);
  const pick = sentences.find((s) => /your call|you decide|你来定/i.test(s)) || sentences[0] || '';
  const zh = /[一-鿿]/.test(pick);
  if (zh) {
    const parts = pick.split('，');
    const own = parts.find((p) => /你来定/.test(p));
    return own ? `${parts[0]}，${own.replace(/[。]$/, '')}。` : pick;
  }
  // "Who it serves first, what it covers … is your call." -> "Who it serves first is your call."
  const m = /^([^,]+),[\s\S]*?(\bis your call\b|\byou decide\b)(.*)$/i.exec(pick);
  return m ? `${m[1]} ${m[2]}${m[3]}` : pick;
}

export function rolledBrief(o: {
  avatar: string;
  line: string;
  lang: string;
  readouts: string;
  roll: boolean;
  esc: (v: unknown) => string;
}) {
  return `<section class="brief-band is-rolled${o.roll ? ' rolling' : ''}" data-brief-rolled style="view-transition-name: case-surface">
    <div class="brief-line">${o.avatar}<p class="brief-line-text"${o.lang}>${o.esc(o.line)}</p>
      <button type="button" class="brief-line-read" data-action="open-doc" data-id="brief">${T('看完整委托', 'Read the full brief')}</button>
      <button type="button" class="btn icon quiet small brief-line-toggle" data-action="board-brief-toggle" aria-expanded="false" aria-label="${o.esc(T('展开委托和条件', 'Show the brief and conditions'))}"><svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg></button></div>
    ${o.readouts}
  </section>`;
}
