// Types for the colleague table that TypeScript modules reuse from the plain-JavaScript people.
export const PERSON_OF_ROLE: Readonly<Record<string, string>>;
export function personName(who: string): string;
export function personTitle(who: string, language: string): string;
export function personLabel(who: string, language: string): string;
