/** One worksheet = one PRD section. The big box is a list of blocks so that headings and
 * quotes keep their structure, and the PRD text stays plain for evaluation and colleagues. */
import type { AipmDesign, Decision, EvidenceRefV2, StepId } from '../../aipm/types';

export type Block =
  | { id: string; type: 'p'; text: string }
  | { id: string; type: 'h'; text: string }
  | { id: string; type: 'quote'; text: string; label: string; ref: EvidenceRefV2 };

/** The design with v2's section_refs and intended_decision (L4 types). */
export type SheetDesign = AipmDesign;

export type Angle = {
  id: string;
  label: string;
  hint: string;
  materials: string[];
  patterns?: boolean;
};
export type SheetChoice = {
  id: 'audience' | 'approver' | 'claim' | 'selected_approach' | 'intended_decision';
  label: string;
  options?: { id: string; label: string }[];
  from_headings?: boolean;
  empty?: string;
};
export type SheetContent = {
  order: number;
  segment: 'clarify' | 'design' | 'verify';
  goal: string;
  angles: Angle[];
  choice?: SheetChoice;
  structure?: 'triage' | 'diagram' | 'evaluation';
  colleagues: ('manager' | 'business' | 'tech')[];
};
export type DesignContent = { sheets: Record<StepId, SheetContent>; placeholder: string };

let seq = 0;
export const blockId = () => `b${Date.now().toString(36)}${(seq++).toString(36)}`;
export const emptyBlocks = (): Block[] => [{ id: blockId(), type: 'p', text: '' }];

const QUOTE_SOURCE = /^> — (.*)$/;
/** Plain PRD text: headings as `### `, quotes as `> ` lines ending with `> — source`. */
export function toText(blocks: Block[]): string {
  return blocks
    .map((b) =>
      b.type === 'h'
        ? `### ${b.text.trim()}`
        : b.type === 'quote'
          ? `${b.text
              .split('\n')
              .map((line) => `> ${line}`)
              .join('\n')}\n> — ${b.label}`
          : b.text.trim(),
    )
    .filter((chunk) => chunk && chunk !== '### ')
    .join('\n\n');
}
/** Reads saved text back; a quote keeps its exact reference only if one was saved for it. */
export function fromText(text: string, refs: readonly EvidenceRefV2[] = []): Block[] {
  const pool = [...refs];
  const blocks: Block[] = [];
  for (const chunk of text.split(/\n{2,}/)) {
    const lines = chunk.split('\n');
    if (chunk.startsWith('### ')) blocks.push({ id: blockId(), type: 'h', text: chunk.slice(4) });
    else if (lines.every((l) => l.startsWith('>')) && QUOTE_SOURCE.test(lines[lines.length - 1])) {
      const quote = lines
        .slice(0, -1)
        .map((l) => l.replace(/^> ?/, ''))
        .join('\n');
      const label = lines[lines.length - 1].replace(QUOTE_SOURCE, '$1');
      const at = pool.findIndex((r) => (r.quote ?? '').trim() === quote.trim());
      if (at >= 0)
        blocks.push({
          id: blockId(),
          type: 'quote',
          text: quote,
          label,
          ref: pool.splice(at, 1)[0],
        });
      else blocks.push({ id: blockId(), type: 'p', text: quote });
    } else if (chunk.trim()) blocks.push({ id: blockId(), type: 'p', text: chunk });
  }
  return blocks.length ? blocks : emptyBlocks();
}
export const quoteRefs = (blocks: Block[]) =>
  blocks.flatMap((b) => (b.type === 'quote' ? [b.ref] : []));
export const wordCount = (blocks: Block[]) =>
  blocks.reduce((n, b) => n + (b.type === 'p' ? b.text.replace(/\s/g, '').length : 0), 0);

/** Splits the paragraph at the caret and puts `insert` between the two halves. */
export function insertAt(
  blocks: Block[],
  at: { id: string; offset: number } | null,
  insert: Block,
): Block[] {
  const index = at ? blocks.findIndex((b) => b.id === at.id) : -1;
  if (index < 0) {
    // No caret yet: append, dropping a trailing empty paragraph so the box does not grow gaps.
    const last = blocks[blocks.length - 1];
    const kept = last?.type === 'p' && !last.text ? blocks.slice(0, -1) : blocks;
    return [...kept, insert, { id: blockId(), type: 'p', text: '' }];
  }
  const target = blocks[index];
  if (target.type !== 'p')
    return [...blocks.slice(0, index + 1), insert, ...blocks.slice(index + 1)];
  const before = target.text.slice(0, at?.offset ?? target.text.length).replace(/\s+$/, '');
  const after = target.text.slice(at?.offset ?? target.text.length).replace(/^\s+/, '');
  return [
    ...blocks.slice(0, index),
    ...(before ? [{ ...target, text: before }] : []),
    insert,
    { id: blockId(), type: 'p', text: after },
    ...blocks.slice(index + 1),
  ];
}

const APPROVER = 'approver-choice';
const MAIN_NEED = 'need-main';
/** The single choice of a sheet lives in the structured design, as the rules read it. */
export function readChoice(step: StepId, design: SheetDesign): string {
  switch (step) {
    case 'business':
      return design.business?.audience ?? '';
    case 'stakeholders':
      return design.stakeholders?.find((s) => s.id === APPROVER)?.name_or_role ?? '';
    case 'need':
      return design.needs?.find((n) => n.id === MAIN_NEED)?.claim_status ?? '';
    case 'solution':
      return design.solution?.selected_approach ?? '';
    case 'decision':
      return design.intended_decision ?? '';
    default:
      return '';
  }
}
export function writeChoice(step: StepId, design: SheetDesign, value: string): SheetDesign {
  switch (step) {
    case 'business':
      return {
        ...design,
        business: {
          offering_explanation: '',
          task_goal: '',
          ...design.business,
          audience: value as 'internal',
        },
      };
    case 'stakeholders': {
      const rest = (design.stakeholders ?? []).filter((s) => s.id !== APPROVER);
      return {
        ...design,
        stakeholders: [
          ...rest,
          {
            id: APPROVER,
            name_or_role: value,
            relationships: ['approver'],
            responsibility: '',
            fact_or_hypothesis: 'unknown',
          },
        ],
      };
    }
    case 'need': {
      const rest = (design.needs ?? []).filter((n) => n.id !== MAIN_NEED);
      const main = design.needs?.find((n) => n.id === MAIN_NEED);
      return {
        ...design,
        needs: [
          {
            id: MAIN_NEED,
            problem: '',
            counterevidence_or_unknown: '',
            next_validation: '',
            ...main,
            claim_status: value as 'hypothesis',
          },
          ...rest,
        ],
      };
    }
    case 'solution':
      return {
        ...design,
        solution: {
          rationale: '',
          alternative: '',
          dependencies: [],
          ...design.solution,
          selected_approach: value,
        },
      };
    case 'decision':
      return { ...design, intended_decision: value as Decision };
    default:
      return design;
  }
}
export const headings = (blocks: Block[]) =>
  blocks.flatMap((b) => (b.type === 'h' && b.text.trim() ? [b.text.trim()] : []));

/** What a sheet saves: the section text, its quotes and its choice. */
export type SheetDraft = { blocks: Block[]; choice: string };
export const sheetKey = (s: SheetDraft) =>
  JSON.stringify([toText(s.blocks), s.choice, quoteRefs(s.blocks)]);
