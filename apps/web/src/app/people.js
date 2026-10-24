// The three colleagues, in one place (user decision 2026-10-24): each has one name, the same in
// Chinese and English, and a role. Every screen that names a colleague reads it from here; the
// scenario materials keep their own wording. Each person's hue is a style token (--p-manager,
// --p-business, --p-technical), unchanged by the names.

/** Person key (the workbench's) for each server role id. */
export const PERSON_OF_ROLE = { supervisor: 'manager', business_lead: 'business', tech_lead: 'technical' };

const PEOPLE_TABLE = {
  manager: { name: 'Grace', title: { zh: '经理', en: 'manager' } },
  business: { name: 'Chen', title: { zh: '业务负责人', en: 'business lead' } },
  technical: { name: 'Daniel', title: { zh: '技术负责人', en: 'technical lead' } },
};

const entry = (who) => PEOPLE_TABLE[PERSON_OF_ROLE[who] ?? who];

/** A colleague's name, by person key (manager) or server role id (supervisor). */
export const personName = (who) => entry(who)?.name ?? '';

/** The role, lower case in English for use inside a sentence ("business lead"). */
export const personTitle = (who, language) => entry(who)?.title[language === 'en' ? 'en' : 'zh'] ?? '';

/** Name and role together, the one way a colleague is listed: 「Grace（经理）」, "Grace (manager)". */
export const personLabel = (who, language) => {
  const p = entry(who);
  if (!p) return '';
  return language === 'en' ? `${p.name} (${p.title.en})` : `${p.name}（${p.title.zh}）`;
};
