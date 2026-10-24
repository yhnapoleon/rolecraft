// Types for the parts of the plain-JavaScript vocabulary that TypeScript modules reuse.
export function UPDATE(key: string): string;
export function FALLBACK(key: string): string;
export function DOMAIN(key: string): string;
export function WORK_ITEM(key: string): string;
export const WORK_COST: Readonly<Record<string, number>>;
export const PRODUCT_NAME: string;
export function workVersion(n: number | string): string;
export function DECISION(key: string): string;
export const HIDDEN_CASES: ReadonlySet<string>;
export const HIDDEN_SCENARIOS: ReadonlySet<string>;
export function caseShown(id: string): boolean;
