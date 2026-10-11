/** Paired copy tables: both languages carry exactly the same keys (checked by tsc and tests). */
export type Language = 'zh' | 'en';
export type CopyTable<K extends string> = Readonly<Record<Language, Readonly<Record<K, string>>>>;

/** Pick one entry and fill `{name}` placeholders. Values are plain text, never markup. */
export function copyText<K extends string>(
  table: CopyTable<K>,
  language: Language,
  key: K,
  values: Readonly<Record<string, string | number>> = {},
): string {
  return table[language][key].replace(/\{(\w+)\}/g, (_, name: string) =>
    String(values[name] ?? ''),
  );
}
