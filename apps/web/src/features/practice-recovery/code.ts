/** Continue codes: 20 Crockford Base32 symbols (100 bits), shown in five groups of four. */
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const LENGTH = 20;
const DASHES = /[-‐-―−]/;
const READS_AS: Readonly<Record<string, string>> = { O: '0', I: '1', L: '1' };

/** The code as the server stores it, or null. The server applies the same rule. */
export function normalizeContinueCode(typed: string): string | null {
  let code = '';
  for (const character of typed.normalize('NFKC').toUpperCase()) {
    if (/\s/.test(character) || DASHES.test(character)) continue;
    const symbol = READS_AS[character] ?? character;
    if (!ALPHABET.includes(symbol)) return null;
    code += symbol;
  }
  return code.length === LENGTH ? code : null;
}

export function groupContinueCode(code: string): string {
  return code.match(/.{1,4}/g)?.join('-') ?? code;
}

/** What may stay in the field between renders; nothing here needs escaping. */
export function continueCodeDraft(typed: string): string {
  return typed
    .normalize('NFKC')
    .replace(/[^0-9A-Za-z\s\-‐-―−]/g, '')
    .slice(0, 64);
}
