/** Small inline-SVG charts for the recognition lab (no chart library).
 *
 * Every chart: thin marks, one axis, recessive grid, a legend for >= 2 series plus direct
 * labels, a native <title> tooltip on every mark, and a table view under it.
 */

const esc = (v: string) =>
  v.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);
const f2 = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : '–');

export interface Series {
  name: string;
  values: number[];
}

function legend(series: { name: string }[]) {
  if (series.length < 2) return '';
  return `<p class="rc-legend">${series
    .map((s, i) => `<span><i class="rc-swatch" data-s="${i + 1}"></i>${esc(s.name)}</span>`)
    .join('')}</p>`;
}

function table(head: string[], rows: (string | number)[][], caption: string) {
  return `<details class="rc-table"><summary>${esc(caption)}</summary><table><thead><tr>${head
    .map((h) => `<th>${esc(h)}</th>`)
    .join('')}</tr></thead><tbody>${rows
    .map((r) => `<tr>${r.map((c) => `<td>${esc(typeof c === 'number' ? f2(c) : c)}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></details>`;
}

/** Horizontal grouped bars on a 0..max scale (e.g. AUROC, accuracy). */
export function groupedBars(
  categories: string[],
  series: Series[],
  opts: { max?: number; min?: number; tableCaption: string },
) {
  const max = opts.max ?? 1;
  const min = opts.min ?? 0;
  const barH = 9;
  const gap = 2;
  const groupH = series.length * (barH + gap) + 10;
  const left = 150;
  const width = 520;
  const plotW = width - left - 48;
  const height = categories.length * groupH + 22;
  const x = (v: number) => left + ((Math.max(min, Math.min(max, v)) - min) / (max - min)) * plotW;
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((t) => {
      const v = min + t * (max - min);
      return `<line class="rc-grid" x1="${x(v)}" x2="${x(v)}" y1="0" y2="${height - 18}"/><text class="rc-tick" x="${x(v)}" y="${height - 4}" text-anchor="middle">${f2(v)}</text>`;
    })
    .join('');
  const bars = categories
    .map((cat, ci) => {
      const y0 = ci * groupH + 4;
      const label = `<text class="rc-cat" x="${left - 8}" y="${y0 + (series.length * (barH + gap)) / 2 + 3}" text-anchor="end">${esc(cat)}</text>`;
      const marks = series
        .map((s, si) => {
          const v = s.values[ci];
          const y = y0 + si * (barH + gap);
          const w = Math.max(1, x(v) - left);
          return `<g><rect class="rc-mark" data-s="${si + 1}" x="${left}" y="${y}" width="${w}" height="${barH}" rx="2"><title>${esc(`${cat} · ${s.name}: ${f2(v)}`)}</title></rect><text class="rc-value" x="${left + w + 4}" y="${y + barH - 1}">${f2(v)}</text></g>`;
        })
        .join('');
      return label + marks;
    })
    .join('');
  return `${legend(series)}<svg class="rc-chart" viewBox="0 0 ${width} ${height}" role="img">${grid}${bars}</svg>${table(
    ['', ...series.map((s) => s.name)],
    categories.map((c, i) => [c, ...series.map((s) => s.values[i])]),
    opts.tableCaption,
  )}`;
}

/** Lines over a shared numeric x (e.g. accuracy vs perturbation). */
export function lines(xs: number[], series: Series[], opts: { xLabel: string; tableCaption: string }) {
  const width = 520;
  const height = 220;
  const left = 40;
  const bottom = 34;
  const plotW = width - left - 90;
  const plotH = height - bottom - 10;
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const X = (v: number) => left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const Y = (v: number) => 10 + (1 - v) * plotH;
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((v) => `<line class="rc-grid" x1="${left}" x2="${left + plotW}" y1="${Y(v)}" y2="${Y(v)}"/><text class="rc-tick" x="${left - 6}" y="${Y(v) + 3}" text-anchor="end">${f2(v)}</text>`)
    .join('');
  const ticks = xs
    .map((v) => `<text class="rc-tick" x="${X(v)}" y="${height - 18}" text-anchor="middle">${v}</text>`)
    .join('');
  const paths = series
    .map((s, si) => {
      const d = s.values.map((v, i) => `${i ? 'L' : 'M'}${X(xs[i])},${Y(v)}`).join(' ');
      const dots = s.values
        .map((v, i) => `<circle class="rc-dot" data-s="${si + 1}" cx="${X(xs[i])}" cy="${Y(v)}" r="4"><title>${esc(`${s.name} · ${opts.xLabel} ${xs[i]}: ${f2(v)}`)}</title></circle>`)
        .join('');
      const last = s.values.length - 1;
      return `<path class="rc-line" data-s="${si + 1}" d="${d}"/>${dots}<text class="rc-direct" x="${X(xs[last]) + 8}" y="${Y(s.values[last]) + 3}">${esc(s.name)}</text>`;
    })
    .join('');
  return `${legend(series)}<svg class="rc-chart" viewBox="0 0 ${width} ${height}" role="img">${grid}${ticks}<text class="rc-tick" x="${left + plotW / 2}" y="${height - 3}" text-anchor="middle">${esc(opts.xLabel)}</text>${paths}</svg>${table(
    [opts.xLabel, ...series.map((s) => s.name)],
    xs.map((x, i) => [String(x), ...series.map((s) => s.values[i])]),
    opts.tableCaption,
  )}`;
}

/** Confusion matrix as a single-hue heatmap (row-normalised shading, counts printed). */
export function heatmap(labels: string[], matrix: number[][], opts: { tableCaption: string; rowLabel: string; colLabel: string }) {
  const cell = 46;
  const left = 120;
  const top = 26;
  const size = labels.length * cell;
  const steps = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'];
  const cells = matrix
    .map((row, r) => {
      const total = row.reduce((a, b) => a + b, 0) || 1;
      return row
        .map((v, c) => {
          const share = v / total;
          const level = Math.min(steps.length - 1, Math.floor(share * steps.length));
          const step = steps[level];
          // Ink follows the cell, not the page theme: dark text on the light steps.
          const ink = !v ? 'var(--ink-3)' : level >= 3 ? '#ffffff' : '#0b0b0b';
          return `<g><rect x="${left + c * cell + 1}" y="${top + r * cell + 1}" width="${cell - 2}" height="${cell - 2}" rx="3" fill="${v ? step : 'var(--fill)'}"><title>${esc(`${labels[r]} → ${labels[c]}: ${v} (${Math.round(share * 100)}%)`)}</title></rect><text x="${left + c * cell + cell / 2}" y="${top + r * cell + cell / 2 + 4}" text-anchor="middle" class="rc-cell" style="fill:${ink}">${v}</text></g>`;
        })
        .join('');
    })
    .join('');
  const rowsLab = labels
    .map((l, i) => `<text class="rc-cat" x="${left - 6}" y="${top + i * cell + cell / 2 + 3}" text-anchor="end">${esc(l)}</text>`)
    .join('');
  const colsLab = labels
    .map((l, i) => `<text class="rc-tick" x="${left + i * cell + cell / 2}" y="${top - 8}" text-anchor="middle">${esc(l.slice(0, 7))}</text>`)
    .join('');
  return `<svg class="rc-chart" viewBox="0 0 ${left + size + 10} ${top + size + 22}" role="img">${rowsLab}${colsLab}${cells}<text class="rc-tick" x="${left + size / 2}" y="${top + size + 16}" text-anchor="middle">${esc(opts.colLabel)}</text></svg>${table(
    [opts.rowLabel, ...labels],
    labels.map((l, i) => [l, ...matrix[i].map(String)]),
    opts.tableCaption,
  )}`;
}

/** 2-D scatter with up to three series (validated all-pairs). */
export function scatter(groups: { name: string; points: { x: number; y: number; label?: string }[] }[], opts: { tableCaption: string }) {
  const all = groups.flatMap((g) => g.points);
  const xs = all.map((p) => p.x);
  const ys = all.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const width = 520;
  const height = 300;
  const pad = 16;
  const X = (v: number) => pad + ((v - x0) / (x1 - x0 || 1)) * (width - 2 * pad);
  const Y = (v: number) => pad + (1 - (v - y0) / (y1 - y0 || 1)) * (height - 2 * pad);
  // The first group (the reference set) is drawn last so it stays visible on top.
  const dots = groups
    .map((g, gi) => ({ g, gi }))
    .reverse()
    .map(({ g, gi }) =>
      g.points
        .map((p) => `<circle class="rc-dot" data-s="${gi + 1}" cx="${X(p.x)}" cy="${Y(p.y)}" r="4"><title>${esc(`${g.name}${p.label ? `: ${p.label}` : ''}`)}</title></circle>`)
        .join(''),
    )
    .join('');
  return `${legend(groups)}<svg class="rc-chart" viewBox="0 0 ${width} ${height}" role="img"><rect class="rc-frame" x="1" y="1" width="${width - 2}" height="${height - 2}" rx="6"/>${dots}</svg>${table(
    ['series', 'x', 'y', ''],
    groups.flatMap((g) => g.points.slice(0, 40).map((p) => [g.name, p.x, p.y, p.label ?? ''])),
    opts.tableCaption,
  )}`;
}
