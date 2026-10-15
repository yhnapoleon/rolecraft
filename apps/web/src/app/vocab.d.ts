// Types for the parts of the plain-JavaScript vocabulary that TypeScript modules reuse.
export function UPDATE(key: string): string;
export function FALLBACK(key: string): string;
export function DOMAIN(key: string): string;
export function WORK_ITEM(key: string): string;
export const WORK_COST: Readonly<Record<string, number>>;
