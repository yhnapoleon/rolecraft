import { describe, expect, it } from 'vitest';
import { asFake, fakeDocument, FakeElement } from '../features/results-native/fake-dom';
import { hasMarkdownStructure, markdownHtml, markdownNodes } from './markdown';

const render = (raw: string, options?: { dropTitle?: boolean }) =>
  markdownNodes(fakeDocument(), raw, options).map(asFake);
/** [tag, text] for a leaf; [tag, ...children] when it holds elements. */
const shape = (node: FakeElement): unknown =>
  node.children.some((child) => child instanceof FakeElement)
    ? [
        node.tagName,
        ...node.children.map((child) =>
          child instanceof FakeElement ? shape(child) : child.textContent,
        ),
      ]
    : [node.tagName, node.textContent];
const tags = (node: FakeElement): string[] => [
  node.tagName,
  ...node.children.flatMap((child) => (child instanceof FakeElement ? tags(child) : [])),
];

describe('Markdown in work previews and colleague replies', () => {
  it('shows headings and list items as structure, not as marker characters', () => {
    expect(render('## 决定\n- 先给 20 人\n- 保留人工兜底').map(shape)).toEqual([
      ['h3', '决定'],
      ['ul', ['li', '先给 20 人'], ['li', '保留人工兜底']],
    ]);
  });

  it('keeps subheadings, ordered lists and paragraphs apart', () => {
    expect(render('### 小节\n1. 第一\n2) 第二\n- 另一种\n\n普通一段').map(shape)).toEqual([
      ['h4', '小节'],
      ['ol', ['li', '第一'], ['li', '第二']],
      ['ul', ['li', '另一种']],
      ['p', '普通一段'],
    ]);
  });

  it('never turns text into markup: tags in the text stay visible text', () => {
    const nodes = render('<img src=x onerror=alert(1)>\n- <b>粗</b>');
    expect(nodes.map((node) => node.textContent)).toEqual([
      '<img src=x onerror=alert(1)>',
      '<b>粗</b>',
    ]);
    expect(nodes.flatMap(tags)).toEqual(['p', 'ul', 'li']);
  });

  it('marks bold and inline code within a line', () => {
    expect(render('先测 **政策 v2** 再看 `配置`').map(shape)).toEqual([
      ['p', '先测 ', ['strong', '政策 v2'], ' 再看 ', ['code', '配置']],
    ]);
  });

  it('can leave out a leading document title', () => {
    expect(render('# 标题\n正文', { dropTitle: true }).map(shape)).toEqual([['p', '正文']]);
    expect(render('# 标题\n正文').map(shape)).toEqual([
      ['h3', '标题'],
      ['p', '正文'],
    ]);
  });

  it('writes the same escaped HTML the workbench pages already use', () => {
    const cases: [string, { dropTitle?: boolean }, string][] = [
      [
        '## 决定\n- 先给 20 人\n- 保留人工兜底',
        {},
        '<h3>决定</h3><ul><li>先给 20 人</li><li>保留人工兜底</li></ul>',
      ],
      ['# 标题\n正文', { dropTitle: true }, '<p>正文</p>'],
      ['# 标题\n正文', {}, '<h3>标题</h3><p>正文</p>'],
      [
        '### 小节\n1. 第一\n2) 第二\n- 混合',
        {},
        '<h4>小节</h4><ol><li>第一</li><li>第二</li></ol><ul><li>混合</li></ul>',
      ],
      [
        'a <b> & "c" \'d\'\n\n  * 星号 **粗** `代码`',
        {},
        '<p>a &lt;b&gt; &amp; &quot;c&quot; &#39;d&#39;</p><ul><li>星号 <strong>粗</strong> <code>代码</code></li></ul>',
      ],
      ['**a `b` c**', {}, '<p><strong>a <code>b</code> c</strong></p>'],
      ['#没有空格\n####### 七级', {}, '<p>#没有空格</p><p>####### 七级</p>'],
      ['  - 缩进项\n普通', {}, '<ul><li>缩进项</li></ul><p>普通</p>'],
      ['1.不是列表', {}, '<p>1.不是列表</p>'],
      ['- a\n\n- b', {}, '<ul><li>a</li></ul><ul><li>b</li></ul>'],
      ['- a\n1. b\n- c', {}, '<ul><li>a</li></ul><ol><li>b</li></ol><ul><li>c</li></ul>'],
      ['##  双空格\n   \n正文  ', {}, '<h3> 双空格</h3><p>正文  </p>'],
      ['', {}, ''],
    ];
    for (const [raw, options, html] of cases) expect(markdownHtml(raw, options)).toBe(html);
  });

  it('keeps the numbers an ordered list was written with', () => {
    // The number each ordered list shows first: its start, 1 when none is given.
    const starts = (raw: string) =>
      render(raw)
        .filter((node) => node.tagName === 'ol')
        .map((ol) => ol.getAttribute('start') ?? '1');
    // Items split by blank lines or by a nested bullet each keep their own number.
    expect(starts('1. A\n\n2. B\n\n3. C')).toEqual(['1', '2', '3']);
    expect(starts('1. A\n   - 细节\n2. B')).toEqual(['1', '2']);
    expect(starts('3. 仅第三条')).toEqual(['3']);
    expect(markdownHtml('1. A\n\n2. B')).toBe('<ol><li>A</li></ol><ol start="2"><li>B</li></ol>');
    expect(markdownHtml('3. 仅第三条')).toBe('<ol start="3"><li>仅第三条</li></ol>');
  });

  it('keeps asterisks inside code literal', () => {
    expect(markdownHtml('`**x**`')).toBe('<p><code>**x**</code></p>');
    expect(markdownHtml('**x** 和 `**y**`')).toBe(
      '<p><strong>x</strong> 和 <code>**y**</code></p>',
    );
  });

  it('tells plain text apart from text that has Markdown structure', () => {
    expect(hasMarkdownStructure('只是一句话。\n第二行也是。')).toBe(false);
    expect(hasMarkdownStructure('## 决定')).toBe(true);
    expect(hasMarkdownStructure('前言\n- 一项')).toBe(true);
    expect(hasMarkdownStructure('请看 **这里**')).toBe(true);
  });
});
