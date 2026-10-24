import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from './i18n';
import { fakeDocument } from '../features/results-native/fake-dom';
import {
  modelChipHtml,
  modelStatus,
  modelWaitHtml,
  modelWaitName,
  modelWaitNode,
  type Semantic,
} from './model-status';

afterEach(() => setPreference('zh'));

/** The status, which these inputs always produce. */
function must<T>(value: T | null): T {
  if (value === null) throw Error('no status');
  return value;
}
const local: Semantic = {
  roles: 'waiting_model',
  feedback: 'waiting_model',
  assistant: 'waiting_model',
};

describe('the one model status of a practice', () => {
  it('says nothing until the server has reported a status', () => {
    expect(modelStatus(null)).toBeNull();
    expect(modelStatus(undefined)).toBeNull();
    expect(modelStatus({ roles: 'model' } as unknown as Semantic)).toBeNull();
  });

  it.each([
    ['zh', '模型：本地模式'],
    ['en', 'Model: local mode'],
  ] as const)('names a deployment without any model as local mode (%s)', (language, label) => {
    const status = must(modelStatus(local, language));
    expect(status.kind).toBe('local');
    expect(status.label).toBe(label);
    expect(status.waiting.map((part) => part.key)).toEqual(['roles', 'assistant', 'feedback']);
  });

  it('tells a partly connected deployment from a fully connected one', () => {
    const partial = must(modelStatus({ ...local, roles: 'model' }, 'en'));
    expect(partial.kind).toBe('partial');
    expect(partial.label).toBe('Model: partly connected');
    expect(partial.waiting.map((part) => part.key)).toEqual(['assistant', 'feedback']);
    const all = must(modelStatus({ roles: 'model', feedback: 'model', assistant: 'model' }, 'zh'));
    expect(all.kind).toBe('model');
    expect(all.label).toBe('模型：已接入');
    expect(all.waiting).toEqual([]);
  });

  it('says what stands in for each part that waits, and treats unavailable as not connected', () => {
    const status = must(modelStatus({ ...local, roles: 'unavailable' }, 'zh'));
    expect(status.kind).toBe('local');
    expect(status.parts.map((part) => [part.name, part.now])).toEqual([
      ['同事回复', '暂不可用，已有记录保留'],
      ['知识助手', '给出检索到的原文片段'],
      ['反馈', '只判规则能核实的项'],
    ]);
  });

  it('renders the toolbar chip closed, and its popover with every part when open', () => {
    const status = must(modelStatus(local, 'zh'));
    const closed = modelChipHtml(status, false, 'zh');
    expect(closed).toContain('aria-expanded="false"');
    expect(closed).toContain('aria-label="模型：本地模式"');
    expect(closed).not.toContain('model-pop');
    const open = modelChipHtml(status, true, 'zh');
    expect(open).toContain('role="dialog"');
    expect(open.match(/data-model-part=/g)).toHaveLength(3);
  });
});

describe('the grey mark on an item that waits for a model', () => {
  it.each([
    ['zh', '等待模型接入'],
    ['en', 'Awaiting model connection'],
  ] as const)('keeps a readable name in both forms (%s)', (language, name) => {
    setPreference(language);
    expect(modelWaitName()).toBe(name);
    expect(modelWaitHtml()).toContain(`>${name}</span>`);
    const node = modelWaitNode(fakeDocument(), 'One sentence.');
    expect(node.textContent).toBe(name);
    expect(node.title).toBe(`${name} · One sentence.`);
    expect(node.dataset.modelWait).toBe('');
  });

  it('escapes the hover sentence', () => {
    expect(modelWaitHtml('<b>"x"</b>', 'en')).not.toContain('<b>');
  });
});
