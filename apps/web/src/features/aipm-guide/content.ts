/** The published company brief and reference patterns, one language each. Shown only beside a
 * guide of the same content revision; other lines use the fact keys, not their own copy. */
import companyZh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/company.zh.json';
import companyEn from '../../../../../scenarios/pm_pilot/aipm-phase1/public/company.en.json';
import patternsZh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/patterns.zh.json';
import patternsEn from '../../../../../scenarios/pm_pilot/aipm-phase1/public/patterns.en.json';
import type { GuideQuestion, Language } from './model';

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
