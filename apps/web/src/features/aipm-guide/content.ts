/** The published company brief and reference patterns, one language each. Shown only beside a
 * guide of the same content revision; other lines use the fact keys, not their own copy. */
import companyZh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/company.zh.json';
import companyEn from '../../../../../scenarios/pm_pilot/aipm-phase1/public/company.en.json';
import patternsZh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/patterns.zh.json';
import patternsEn from '../../../../../scenarios/pm_pilot/aipm-phase1/public/patterns.en.json';
import type { GuideQuestion, Language } from './model';

// Every published file of the candidate present in this build (L2/L3 add design / evaluation).
const published = import.meta.glob<unknown>(
  '../../../../../scenarios/pm_pilot/aipm-phase1/public/*.json',
  { import: 'default' },
);
/** One published content file in one language, only if it belongs to this experience. Each
 * line versions its own file; the package manifest binds them to one scenario hash. */
export async function publishedContent(id: string, language: Language) {
  const load = Object.entries(published).find(([path]) =>
    path.endsWith(`/public/${id}.${language}.json`),
  )?.[1];
  if (!load) throw new Error(`AIPM content not in this build: ${id}`);
  const value = (await load()) as { experience_revision?: string };
  if (value.experience_revision !== undefined && value.experience_revision !== 'aipm-phase1-v1')
    throw new Error(`AIPM content is for another experience: ${id}`);
  return value;
}

export type CompanyBrief = {
  revision: string;
  title: string;
  statusLabel: string;
  pending: boolean;
  sentences: {
    key: string;
    text: string;
    materials: string[];
    status: string;
  }[];
  questions: GuideQuestion[];
};
export type PatternCard = {
  id: string;
  title: string;
  when: string;
  cost: string;
  whenNot: string;
  source: { title: string; url: string; accessed: string };
};

export function companyBrief(language: Language): CompanyBrief {
  const c = language === 'en' ? companyEn : companyZh;
  return {
    revision: c.content_revision,
    title: c.title,
    statusLabel: c.status_label,
    pending: c.status === 'pending_user_confirmation',
    sentences: c.sentences.map((s) => ({
      key: s.fact_key,
      text: s.text,
      materials: s.source_material_ids,
      status: s.source_status,
    })),
    questions: c.questions as GuideQuestion[],
  };
}

export function patterns(language: Language): {
  label: string;
  note: string;
  cards: PatternCard[];
} {
  const p = language === 'en' ? patternsEn : patternsZh;
  return {
    label: p.status_label,
    note: p.application_note,
    cards: p.cards.map((c) => ({
      id: c.id,
      title: c.title,
      when: c.when,
      cost: c.cost_dimensions,
      whenNot: c.when_not,
      source: {
        title: c.source.title,
        url: c.source.url,
        accessed: c.source.accessed_at,
      },
    })),
  };
}
