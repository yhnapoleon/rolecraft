/** Read-only frontend metrics and formatting equivalence against a fixed Git revision. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseSync, transformSync } from 'rolldown/utils';
import { transform as transformCss } from 'lightningcss';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const base = process.argv[2];
if (!base) throw new Error('Pass the fixed comparison commit.');
const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' });
const files = git('ls-tree', '-r', '--name-only', base, '--', 'apps/web')
  .trim()
  .split('\n')
  .filter((path) => !path.startsWith('apps/web/tests/screenshots/'));
const before = (path) => git('show', `${base}:${path}`);
const after = (path) => readFileSync(resolve(root, path), 'utf8');
const code = files.filter((path) => /\.(?:[cm]?js|tsx?|css|html)$/.test(path));

function tree(value, jsxBindings) {
  if (Array.isArray(value)) return value.map((child) => tree(child, jsxBindings));
  if (!value || typeof value !== 'object') return value;
  const result = Object.fromEntries(
    Object.entries(value)
      .filter(
        ([key]) =>
          !['start', 'end', 'loc', 'range'].includes(key) &&
          !(key === 'raw' && value.type === 'Literal'),
      )
      .map(([key, child]) => [key, tree(child, jsxBindings)]),
  );
  if (result.type === 'Property' && !result.computed) {
    const key = result.key;
    if (key.type === 'Identifier' || key.type === 'Literal') {
      result.key = { type: 'StaticPropertyKey', value: String(key.name ?? key.value) };
    }
  }
  if (
    result.type === 'CallExpression' &&
    result.callee.type === 'Identifier' &&
    jsxBindings.functions.has(result.callee.name) &&
    ((result.arguments[0]?.type === 'Literal' && typeof result.arguments[0].value === 'string') ||
      (result.arguments[0]?.type === 'Identifier' &&
        jsxBindings.fragments.has(result.arguments[0].name)))
  ) {
    // Only native DOM elements and React fragments; never application component data.
    const children = result.arguments[1]?.properties?.find(
      (property) => property.key?.value === 'children',
    )?.value;
    if (children?.type === 'ArrayExpression') {
      const merged = [];
      for (const child of children.elements) {
        const prior = merged.at(-1);
        if (
          child?.type === 'Literal' &&
          typeof child.value === 'string' &&
          prior?.type === 'Literal' &&
          typeof prior.value === 'string'
        ) {
          prior.value += child.value;
        } else merged.push(child);
      }
      children.elements = merged;
    }
  }
  return result;
}
function parse(path, source) {
  const parsed = parseSync(path, source);
  if (parsed.errors.length) throw new Error(`Cannot parse ${path}`);
  return parsed.program;
}
function runtimeTree(path, source) {
  const transformed = transformSync(path, source);
  if (transformed.errors.length) throw new Error(`Cannot transform ${path}`);
  const program = parse(path.replace(/\.(?:tsx?|jsx)$/, '.js'), transformed.code);
  const specifiers = program.body
    .filter(
      (node) => node.type === 'ImportDeclaration' && node.source.value === 'react/jsx-runtime',
    )
    .flatMap((node) => node.specifiers);
  const names = (imported) =>
    new Set(
      specifiers
        .filter((specifier) => imported.includes(specifier.imported?.name))
        .map((specifier) => specifier.local.name),
    );
  const jsxBindings = { functions: names(['jsx', 'jsxs']), fragments: names(['Fragment']) };
  return tree(program, jsxBindings);
}
function countAny(value) {
  if (!value || typeof value !== 'object') return 0;
  return (
    Number(value.type === 'TSAnyKeyword') +
    Object.values(value).reduce((total, child) => total + countAny(child), 0)
  );
}
function metrics(read, paths) {
  const measuredCode = paths.filter((path) => /\.(?:[cm]?js|tsx?|css|html)$/.test(path));
  const ts = measuredCode.filter(
    (path) =>
      path.startsWith('apps/web/src/') &&
      /\.tsx?$/.test(path) &&
      !/\.(test|spec)\.|\/test-support\.ts$/.test(path),
  );
  return {
    ui_lines: read('apps/web/src/app/ui.js').trimEnd().split('\n').length,
    non_test_ts_any_keywords: ts.reduce((sum, path) => sum + countAny(parse(path, read(path))), 0),
    long_lines_over_100: measuredCode.reduce(
      (sum, path) =>
        sum +
        read(path)
          .split('\n')
          .filter((line) => [...line].length > 100).length,
      0,
    ),
    code_files: measuredCode.length,
    files_without_screenshots: paths.length,
  };
}
const comparisons = [];
for (const path of code) {
  const left = before(path),
    right = after(path);
  if (left === right) continue;
  let equal;
  if (/\.(?:[cm]?js|tsx?)$/.test(path)) {
    equal = JSON.stringify(runtimeTree(path, left)) === JSON.stringify(runtimeTree(path, right));
  } else if (path.endsWith('.css')) {
    const minify = (text) =>
      transformCss({ filename: path, code: Buffer.from(text), minify: true }).code;
    // Normalize optional comma/slash spacing in var-dependent CSS values only.
    // Quoted text, escaped delimiters and selectors keep their exact contents.
    const spacing = (text) =>
      text
        .toString()
        .replace(
          /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\*[\s\S]*?\*\/)|\s*(?<!\\)([,/])\s*/g,
          (_match, quoted, delimiter) => quoted ?? delimiter,
        );
    equal = spacing(minify(left)) === spacing(minify(right));
  } else {
    // HTML is checked by the normal browser flows and visual comparison, not a whitespace heuristic.
    comparisons.push({ path, check: 'browser_and_screenshot' });
    continue;
  }
  comparisons.push({ path, check: 'runtime_ast_or_css', equal });
}
const currentFiles = [
  ...new Set(
    git('ls-files', '--cached', '--others', '--exclude-standard', 'apps/web').trim().split('\n'),
  ),
].filter(
  (path) => !path.startsWith('apps/web/tests/screenshots/') && existsSync(resolve(root, path)),
);
const report = {
  base,
  scope:
    'Tracked frontend code; screenshots excluded. Non-test TS excludes .test/.spec and test-support.',
  before: metrics(before, files),
  after: metrics(after, currentFiles),
  comparisons,
  comparison_digest: createHash('sha256').update(JSON.stringify(comparisons)).digest('hex'),
};
console.log(JSON.stringify(report, null, 2));
if (comparisons.some((result) => result.equal === false)) process.exitCode = 1;
