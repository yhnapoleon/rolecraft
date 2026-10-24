/** Small inline-SVG charts for the system profile page (no chart library).
 *
 * Every chart: a readable name (`role="img"` + `aria-label` + `<title>`), thin marks, one
 * axis, a recessive grid, a legend for >= 2 series plus direct value labels, a native
 * `<title>` tooltip on every mark, and a table view under it. Series are told apart by
 * ink weight and texture (solid ink, grey, outline, hatching), never by a new colour:
 * the product's colours each carry one meaning. `width` picks the viewBox, so a phone
 * gets a narrow chart whose text is not scaled down.
 */

const esc = (v: string) =>
  v.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
const f2 = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : '–');
const fmt = (v: number, digits: number) => (Number.isFinite(v) ? v.toFixed(digits) : '–');

export interface Series {
  name: string;
  values: number[];
}

interface Named {
  /** The chart's accessible name: what it shows, on which test set. */
  label: string;
  tableCaption: string;
  width?: number;
  digits?: number;
}

let patternSeq = 0;

/** Approximate rendered width of 10.5px text: CJK glyphs are about twice as wide. */
function textWidth(text: string) {
  let w = 0;
  for (const ch of text) w += /[⺀-鿿＀-￯]/.test(ch) ? 10.5 : 5.8;
  return w;
}
function clipText(text: string, max: number) {
  if (textWidth(text) <= max) return text;
  let out = '';
  for (const ch of text) {
    if (textWidth(`${out + ch}…`) > max) break;
    out += ch;
  }
  return `${out}…`;
}

function open(width: number, height: number, label: string, extra = '') {
  return `<svg class="rc-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}"${extra}><title>${esc(label)}</title>`;
}

function hatch(id: string) {
  return `<defs><pattern id="${id}" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="4" class="rc-hatch-bg"/><line x1="0" y1="0" x2="0" y2="4" class="rc-hatch-line"/></pattern></defs>`;
}

function legend(series: { name: string }[]) {
  if (series.length < 2) return '';
  return `<p class="rc-legend">${series
    .map((s, i) => `<span><i class="rc-swatch" data-s="${i + 1}"></i>${esc(s.name)}</span>`)
    .join('')}</p>`;
}

function table(head: string[], rows: (string | number)[][], caption: string, digits = 2) {
  return `<details class="rc-table"><summary>${esc(caption)}</summary><div class="rc-table-scroll"><table><thead><tr>${head
    .map((h) => `<th scope="col">${esc(h)}</th>`)
    .join('')}</tr></thead><tbody>${rows
    .map(
      (r) =>
        `<tr>${r.map((c, i) => (i === 0 ? `<th scope="row">${esc(String(c))}</th>` : `<td>${esc(typeof c === 'number' ? fmt(c, digits) : c)}</td>`)).join('')}</tr>`,
    )
    .join('')}</tbody></table></div></details>`;
}

/** Horizontal grouped bars on a min..max scale (e.g. macro-F1, AUROC, recall). */
export function groupedBars(
  categories: string[],
  series: Series[],
  opts: Named & { max?: number; min?: number },
) {
  const width = opts.width ?? 520;
  const digits = opts.digits ?? 2;
  const max = opts.max ?? 1;
  const min = opts.min ?? 0;
  const barH = 9;
  const gap = 2;
  const groupH = series.length * (barH + gap) + 10;
  // The label column fits the longest category, within limits, so names are rarely cut.
  const longest = Math.max(0, ...categories.map(textWidth));
  const left = Math.round(Math.min(width * 0.42, Math.max(64, longest + 18)));
  const plotW = width - left - 40;
  const height = categories.length * groupH + 22;
  const id = `rc-hatch-${++patternSeq}`;
  const x = (v: number) => left + ((Math.max(min, Math.min(max, v)) - min) / (max - min)) * plotW;
  // Ticks on round steps: quarters over 0..1, tenths over a half range such as 0.5..1.
  const step = max - min <= 0.5 ? 0.1 : 0.25;
  const ticks = Array.from(
    { length: Math.round((max - min) / step) + 1 },
    (_, i) => min + i * step,
  );
  const grid = ticks
    .map(
      (v) =>
        `<line class="rc-grid" x1="${x(v)}" x2="${x(v)}" y1="0" y2="${height - 18}"/><text class="rc-tick" x="${x(v)}" y="${height - 4}" text-anchor="middle">${f2(v)}</text>`,
    )
    .join('');
  const bars = categories
    .map((cat, ci) => {
      const y0 = ci * groupH + 4;
      const label = `<text class="rc-lab-cat" x="${left - 8}" y="${y0 + (series.length * (barH + gap)) / 2 + 3}" text-anchor="end">${esc(clipText(cat, left - 12))}<title>${esc(cat)}</title></text>`;
      const marks = series
        .map((s, si) => {
          const v = s.values[ci];
          const y = y0 + si * (barH + gap);
          if (!Number.isFinite(v))
            return `<text class="rc-value" x="${left + 4}" y="${y + barH - 1}">–<title>${esc(`${cat} · ${s.name}: –`)}</title></text>`;
          const w = Math.max(1, x(v) - left);
          const fill = si === 3 ? ` fill="url(#${id})"` : '';
          return `<g><rect class="rc-mark" data-s="${si + 1}"${fill} x="${left}" y="${y}" width="${w}" height="${barH}" rx="2"><title>${esc(`${cat} · ${s.name}: ${fmt(v, digits)}`)}</title></rect><text class="rc-value" x="${left + w + 4}" y="${y + barH - 1}">${fmt(v, digits)}</text></g>`;
        })
        .join('');
      return label + marks;
    })
    .join('');
  return `<figure class="rc-figure">${legend(series)}${open(width, height, opts.label)}${series.length > 3 ? hatch(id) : ''}${grid}${bars}</svg>${table(
    ['', ...series.map((s) => s.name)],
    categories.map((c, i) => [c, ...series.map((s) => s.values[i])]),
    opts.tableCaption,
    digits,
  )}</figure>`;
}

/** Lines over a shared numeric x (e.g. accuracy vs perturbation, error vs deferral). */
export function lines(xs: number[], series: Series[], opts: Named & { xLabel: string }) {
  const width = opts.width ?? 520;
  const digits = opts.digits ?? 2;
  const height = width >= 480 ? 220 : 200;
  const left = 40;
  const bottom = 34;
  const plotW = width - left - (width >= 480 ? 96 : 72);
  const plotH = height - bottom - 10;
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const X = (v: number) => left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const Y = (v: number) => 10 + (1 - v) * plotH;
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (v) =>
        `<line class="rc-grid" x1="${left}" x2="${left + plotW}" y1="${Y(v)}" y2="${Y(v)}"/><text class="rc-tick" x="${left - 6}" y="${Y(v) + 3}" text-anchor="end">${f2(v)}</text>`,
    )
    .join('');
  const ticks = xs
    .map(
      (v) =>
        `<text class="rc-tick" x="${X(v)}" y="${height - 18}" text-anchor="middle">${v}</text>`,
    )
    .join('');
  const paths = series
    .map((s, si) => {
      const d = s.values.map((v, i) => `${i ? 'L' : 'M'}${X(xs[i])},${Y(v)}`).join(' ');
      const dots = s.values
        .map(
          (v, i) =>
            `<circle class="rc-dot" data-s="${si + 1}" cx="${X(xs[i])}" cy="${Y(v)}" r="4"><title>${esc(`${s.name} · ${opts.xLabel} ${xs[i]}: ${fmt(v, digits)}`)}</title></circle>`,
        )
        .join('');
      const last = s.values.length - 1;
      return `<path class="rc-line" data-s="${si + 1}" d="${d}"/>${dots}<text class="rc-direct" x="${X(xs[last]) + 8}" y="${Y(s.values[last]) + 3}">${esc(clipText(s.name, width - X(xs[last]) - 10))}</text>`;
    })
    .join('');
  return `<figure class="rc-figure">${legend(series)}${open(width, height, opts.label)}${grid}${ticks}<text class="rc-tick" x="${left + plotW / 2}" y="${height - 3}" text-anchor="middle">${esc(opts.xLabel)}</text>${paths}</svg>${table(
    [opts.xLabel, ...series.map((s) => s.name)],
    xs.map((x, i) => [String(x), ...series.map((s) => s.values[i])]),
    opts.tableCaption,
    digits,
  )}</figure>`;
}

/** Confusion matrix as a single-hue ink ramp (row-normalised shading, counts printed). */
export function heatmap(
  labels: string[],
  matrix: number[][],
  opts: Named & { rowLabel: string; colLabel: string; columns?: string[] },
) {
  const columns = opts.columns ?? labels;
  const narrow = (opts.width ?? 520) < 480;
  const cell = narrow ? 40 : 46;
  const left = narrow ? 92 : 120;
  const top = 26;
  const size = labels.length * cell;
  const width = left + size + 10;
  const cells = matrix
    .map((row, r) => {
      const total = row.reduce((a, b) => a + b, 0) || 1;
      return row
        .map((v, c) => {
          const share = v / total;
          const level = Math.min(5, Math.floor(share * 6));
          // Ink follows the cell, not the page: light text on the two darkest steps.
          const shade = v
            ? `color-mix(in srgb, var(--ink) ${10 + level * 16}%, var(--paper))`
            : 'var(--fill)';
          const ink = !v ? 'var(--ink-3)' : level >= 3 ? 'var(--paper)' : 'var(--ink)';
          return `<g><rect x="${left + c * cell + 1}" y="${top + r * cell + 1}" width="${cell - 2}" height="${cell - 2}" rx="3" style="fill:${shade}"><title>${esc(`${labels[r]} → ${labels[c]}: ${v} (${Math.round(share * 100)}%)`)}</title></rect><text x="${left + c * cell + cell / 2}" y="${top + r * cell + cell / 2 + 4}" text-anchor="middle" class="rc-lab-cell" style="fill:${ink}">${v}</text></g>`;
        })
        .join('');
    })
    .join('');
  const rowsLab = labels
    .map(
      (l, i) =>
        `<text class="rc-lab-cat" x="${left - 6}" y="${top + i * cell + cell / 2 + 3}" text-anchor="end">${esc(clipText(l, left - 10))}<title>${esc(l)}</title></text>`,
    )
    .join('');
  const colsLab = columns
    .map(
      (l, i) =>
        `<text class="rc-tick" x="${left + i * cell + cell / 2}" y="${top - 8}" text-anchor="middle">${esc(clipText(l, cell - 2))}<title>${esc(labels[i] ?? l)}</title></text>`,
    )
    .join('');
  return `<figure class="rc-figure">${open(width, top + size + 22, opts.label, ` style="max-width:${width}px"`)}${rowsLab}${colsLab}${cells}<text class="rc-tick" x="${left + size / 2}" y="${top + size + 16}" text-anchor="middle">${esc(opts.colLabel)}</text></svg>${table(
    [opts.rowLabel, ...labels],
    labels.map((l, i) => [l, ...matrix[i].map(String)]),
    opts.tableCaption,
  )}</figure>`;
}

/** 2-D scatter with up to three series. */
export function scatter(
  groups: { name: string; points: { x: number; y: number; label?: string }[] }[],
  opts: Named,
) {
  const all = groups.flatMap((g) => g.points);
  const xs = all.map((p) => p.x);
  const ys = all.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const width = opts.width ?? 520;
  const height = width >= 480 ? 300 : 240;
  const pad = 16;
  const X = (v: number) => pad + ((v - x0) / (x1 - x0 || 1)) * (width - 2 * pad);
  const Y = (v: number) => pad + (1 - (v - y0) / (y1 - y0 || 1)) * (height - 2 * pad);
  // The first group (the reference set) is drawn last so it stays visible on top.
  const dots = groups
    .map((g, gi) => ({ g, gi }))
    .reverse()
    .map(({ g, gi }) =>
      g.points
        .map(
          (p) =>
            `<circle class="rc-dot" data-s="${gi + 1}" cx="${X(p.x)}" cy="${Y(p.y)}" r="4"><title>${esc(`${g.name}${p.label ? `: ${p.label}` : ''}`)}</title></circle>`,
        )
        .join(''),
    )
    .join('');
  return `<figure class="rc-figure">${legend(groups)}${open(width, height, opts.label)}<rect class="rc-frame" x="1" y="1" width="${width - 2}" height="${height - 2}" rx="6"/>${dots}</svg>${table(
    ['', 'x', 'y', ''],
    groups.flatMap((g) => g.points.slice(0, 40).map((p) => [g.name, p.x, p.y, p.label ?? ''])),
    opts.tableCaption,
  )}</figure>`;
}
