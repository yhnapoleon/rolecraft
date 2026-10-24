import { describe, expect, it } from 'vitest';
import { groupedBars, heatmap, lines, scatter } from './charts';

const svgOf = (html: string) => html.match(/<svg[^>]*>/)?.[0] ?? '';

describe('system profile charts', () => {
  it('give every chart a readable name and a table view', () => {
    const charts = [
      groupedBars(['BM25', 'e5'], [{ name: '中文', values: [0.49, 0.82] }], {
        label: 'E3 改写问题 Recall@5',
        tableCaption: '表格视图',
      }),
      lines([0, 0.5], [{ name: 'DTW', values: [1, 0.71] }], {
        label: 'E6 扰动下的策略准确率',
        xLabel: '扰动概率',
        tableCaption: '表格视图',
      }),
      heatmap(
        ['A', 'B'],
        [
          [3, 1],
          [0, 4],
        ],
        {
          label: 'E7 混淆矩阵',
          tableCaption: '表格视图',
          rowLabel: '真实',
          colLabel: '预测',
        },
      ),
      scatter(
        [
          {
            name: '单元',
            points: [
              { x: 0, y: 1 },
              { x: 1, y: 0 },
            ],
          },
        ],
        {
          label: 'E5 PCA 投影',
          tableCaption: '表格视图',
        },
      ),
    ];
    const names = ['E3 改写问题 Recall@5', 'E6 扰动下的策略准确率', 'E7 混淆矩阵', 'E5 PCA 投影'];
    charts.forEach((html, i) => {
      const svg = svgOf(html);
      expect(svg).toContain('role="img"');
      expect(svg).toContain(`aria-label="${names[i]}"`);
      expect(html).toContain(`<title>${names[i]}</title>`);
      expect(html).toContain('<summary>表格视图</summary>');
    });
  });

  it('draws narrow charts on a narrow viewBox so labels stay legible on a phone', () => {
    const wide = svgOf(
      groupedBars(['a'], [{ name: 's', values: [0.5] }], { label: 'x', tableCaption: 't' }),
    );
    const narrow = svgOf(
      groupedBars(['a'], [{ name: 's', values: [0.5] }], {
        label: 'x',
        tableCaption: 't',
        width: 340,
      }),
    );
    expect(wide).toMatch(/viewBox="0 0 520 /);
    expect(narrow).toMatch(/viewBox="0 0 340 /);
  });

  it('escapes names that come from data', () => {
    const html = groupedBars(['<b>'], [{ name: '"s"', values: [0.5] }], {
      label: '<i>',
      tableCaption: 't',
    });
    expect(html).not.toContain('<b>');
    expect(html).not.toContain('<i>');
  });
});
