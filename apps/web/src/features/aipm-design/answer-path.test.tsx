import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AssistantConfig, EffectiveConfig } from '../../contracts-v2';
import type { AipmDesign } from '../../aipm/types';
import { stageName } from '../answer-chain/copy';
import {
  AnswerPath,
  AnswerPathView,
  answerPathView,
  nodeSentence,
  type PathNode,
  type PathRead,
  readPath,
  reasonText,
} from './answer-path';
import { copy } from './copy';
import { DiagramBlock } from './desk';
import { diagram, newRow } from './model';

const html = (node: React.ReactElement) => renderToString(node).replaceAll('<!-- -->', '');

/** FAKE DATA for unit tests only: the shape of the pm_pilot baseline configuration. */
const base: Required<AssistantConfig> = {
  schema_version: 2,
  id: 'pilot',
  session_id: 's',
  version: 1,
  config_version: 0,
  domains: ['stable_faq', 'onboarding', 'policy_travel', 'policy_meal', 'policy_leave'],
  scope_filter: true,
  update_strategy: 'daily',
  fallback: 'human',
  chunk_size: 500,
  retrieval_limit: 3,
  min_score: 0.35,
  min_score_calibration: null,
  freshness_guard: 'none',
  manual_domains: [],
  prohibited_topics: [],
  work_items: ['scope_filter', 'human_fallback'],
  generator: 'extractive',
  participants: 30,
  launch_day: 7,
};
const effective = (
  requested: Partial<AssistantConfig>,
  actual: Partial<AssistantConfig>,
  differences: Record<string, string>,
): EffectiveConfig => ({
  requested: { ...base, ...requested },
  effective: { ...base, ...actual },
  differences,
});
const read = (e: EffectiveConfig | null = effective({}, {}, {})): PathRead => ({ config: base, effective: e });
const nodeOf = (nodes: PathNode[], key: string) => {
  const found = nodes.find((n) => n.key === key);
  if (!found) throw new Error(`missing ${key}`);
  return found;
};

describe('answer path (design view)', () => {
  it('shows eight nodes in two rows with the values in effect', () => {
    const view = answerPathView(read(), 'zh');
    expect(view.offline.map((n) => n.name)).toEqual(['开放哪些资料', '多久更新索引', '段落怎么切']);
    expect(view.online.map((n) => n.name)).toEqual(['能不能答', '找到什么', '资料新不新', '怎么答', '答不了谁接']);
    expect(nodeOf(view.offline, 'sources')).toMatchObject({ value: '5 个知识域', settable: true });
    expect(nodeOf(view.offline, 'sources').note).toBe('办公 FAQ、入职指引、差旅政策、餐费政策、请假政策');
    expect(nodeOf(view.offline, 'index')).toMatchObject({ value: '每日', note: '最长滞后 24 小时' });
    expect(nodeOf(view.offline, 'passages')).toMatchObject({ value: '每段 500 字 · 取前 3 段', settable: false });
    expect(nodeOf(view.online, 'scope')).toMatchObject({ value: '范围过滤：开', note: '范围外检测', settable: true });
    expect(nodeOf(view.online, 'found')).toMatchObject({ value: '阈值 0.35', note: '语义检索', settable: false });
    expect(nodeOf(view.online, 'fresh')).toMatchObject({ value: '过期处理：不处理', settable: false });
    expect(nodeOf(view.online, 'answer').value).toBe('原文摘录');
    expect(nodeOf(view.online, 'result').value).toBe('人工兜底：开');
    expect([...view.offline, ...view.online].every((n) => n.amber === null)).toBe(true);
  });

  it('names the online steps exactly as the test chain does', () => {
    const view = answerPathView(read(), 'en');
    expect(view.online.slice(0, 4).map((n) => n.name)).toEqual(
      (['scope', 'found', 'fresh', 'answer'] as const).map((k) => stageName(k, 'en')),
    );
    expect(nodeOf(view.online, 'result').name).toBe(stageName('result', 'en', true));
    expect(nodeOf(view.offline, 'index').value).toBe('Daily');
    expect(nodeOf(view.online, 'scope').value).toBe('Scope filter on');
  });

  it.each([
    [
      'realtime_sync_not_provisioned',
      'index',
      { update_strategy: 'realtime' as const },
      { update_strategy: 'daily' as const },
      '你请求：实时 → 实际：每日',
      '实时同步要 5 人日，还没批到。',
      'Real-time sync needs 5 person-days that are not approved yet.',
    ],
    [
      'scope_filter_not_provisioned',
      'scope',
      { scope_filter: true },
      { scope_filter: false },
      '你请求：范围过滤：开 → 实际：范围过滤：关',
      '范围过滤要 1 人日，还没批到。',
      'The scope filter needs 1 person-day that is not approved yet.',
    ],
    [
      'human_fallback_not_provisioned',
      'result',
      { fallback: 'human' as const },
      { fallback: 'none' as const },
      '你请求：人工兜底：开 → 实际：人工兜底：关',
      '人工兜底要 1 人日，还没批到。',
      'Human fallback needs 1 person-day that is not approved yet.',
    ],
    [
      'manual_policy_not_provisioned',
      'index',
      { update_strategy: 'manual_policy' as const },
      { update_strategy: 'daily' as const },
      '你请求：政策人工核 → 实际：每日',
      '政策人工核需要范围过滤和人工兜底，还没批到。',
      'Manual policy checks need the scope filter and human fallback, not approved yet.',
    ],
    [
      'requested_work_not_fully_provisioned',
      'index',
      { update_strategy: 'realtime' as const },
      { update_strategy: 'daily' as const },
      '你请求：实时 → 实际：每日',
      '这项设置还没生效。',
      'This setting is not in effect yet.',
    ],
  ])('turns the node amber for %s', (code, key, requested, actual, change, zh, en) => {
    const field = Object.keys(requested)[0];
    const e = effective(requested, actual, { [field]: code });
    const view = answerPathView(read(e), 'zh');
    const node = nodeOf([...view.offline, ...view.online], key);
    expect(node.amber).toEqual({ change, reason: zh });
    expect(reasonText(code, 'en')).toBe(en);
    expect(nodeSentence(node, 'zh')).toContain('未生效');
    expect(html(<AnswerPathView state={{ kind: 'ready', view }} language="zh" onSettings={vi.fn()} onOpenSettings={vi.fn()} onRetry={vi.fn()} />)).toContain(
      'data-state="amber"',
    );
  });

  it('keeps every node plain when requested equals effective', () => {
    const view = answerPathView(read(effective({ update_strategy: 'realtime' }, { update_strategy: 'realtime' }, {})), 'zh');
    expect([...view.offline, ...view.online].some((n) => n.amber)).toBe(false);
    expect(nodeOf(view.offline, 'index').value).toBe('实时');
  });

  it('does not call a canonicalized knowledge area "not in effect"', () => {
    const view = answerPathView(read(effective({ domains: ['faq'] }, { domains: ['stable_faq'] }, {})), 'zh');
    expect(nodeOf(view.offline, 'sources').amber).toBeNull();
    const narrowed = answerPathView(read(effective({ domains: ['faq', 'onboarding'] }, { domains: ['faq'] }, {})), 'zh');
    expect(nodeOf(narrowed.offline, 'sources').amber).toEqual({
      change: '你请求：2 个知识域 → 实际：1 个知识域',
      reason: '这项设置还没生效。',
    });
  });

  it('reads a node aloud as one sentence', () => {
    const view = answerPathView(read(), 'zh');
    expect(nodeSentence(nodeOf(view.offline, 'index'), 'zh')).toBe('多久更新索引：每日，最长滞后 24 小时，你的设置');
  });

  it('says what was not recorded instead of guessing', () => {
    const view = answerPathView({ config: { domains: ['faq'] }, effective: null }, 'en');
    expect(view.effectiveKnown).toBe(false);
    expect(nodeOf(view.online, 'found').value).toBe('Not recorded');
    expect(nodeOf(view.offline, 'sources').value).toBe('1 knowledge area');
    const page = html(
      <AnswerPathView state={{ kind: 'ready', view }} language="en" onSettings={null} onOpenSettings={vi.fn()} onRetry={vi.fn()} />,
    );
    expect(page).toContain('what is in effect cannot be read right now');
  });

  it('makes only "Your setting" nodes buttons, and none in a read-only session', () => {
    const view = answerPathView(read(), 'zh');
    const props = { state: { kind: 'ready', view } as const, language: 'zh' as const, onOpenSettings: vi.fn(), onRetry: vi.fn() };
    const live = html(<AnswerPathView {...props} onSettings={vi.fn()} />);
    // sources, index, scope, answer, takeover; plus the footer's "open actual settings".
    expect(live.match(/<button[^>]*class="aipm-path__node"/g)).toHaveLength(5);
    expect(live).toContain('要调整，从测试台把失败的题交给 Daniel');
    const sealed = html(<AnswerPathView {...props} onSettings={null} />);
    expect(sealed.match(/<button[^>]*class="aipm-path__node"/g)).toBeNull();
    expect(sealed).toContain('打开实际设置');
  });

  it('shows loading frames, then a retry when the read fails', async () => {
    const loading = html(<AnswerPath data={{ query: () => new Promise(() => {}), subscribe: () => () => {}, snapshot: () => ({ asOf: null }) as never }} language="zh" readOnly={false} onSettings={vi.fn()} />);
    expect(loading).toContain('aipm-path__node--blank');
    expect(loading).toContain('aria-busy="true"');
    const failed = html(<AnswerPath data={null} language="zh" readOnly={false} onSettings={vi.fn()} />);
    expect(failed).toContain('暂时读不到当前设置');
    expect(failed).toContain('重试');
  });

  it('reads the workspace configuration and what is in effect', async () => {
    const e = effective({}, {}, {});
    const query = vi.fn(async () => ({ timeline: { workspace: { config: base, effective_config: e } } }));
    expect(await readPath({ query } as never)).toEqual({ config: base, effective: e });
    expect(query).toHaveBeenCalledWith('workbench.read');
  });
});

describe('diagram block', () => {
  /** FAKE DATA for component tests only. */
  const design: AipmDesign = {
    id: 'aipm-design',
    session_id: 's',
    revision: 1,
    rows: [
      { ...newRow('r1'), user_request: 'How much is the hotel limit?', route: 'retrieval_generation' },
      { ...newRow('r2'), user_request: 'Approve my claim', route: 'human' },
    ],
  };
  const host = {
    getDataHost: () => null,
    getSessionContext: () => ({ readOnly: false }),
    openSettings: vi.fn(),
  };

  it('draws the answer path first and sends retrieval rows to it', () => {
    const page = html(
      <DiagramBlock
        c={copy('en')}
        host={host as never}
        saved={{ ref: {} as never, design, feedback: [] }}
        language="en"
      />,
    );
    expect(page.indexOf("The assistant's answer path")).toBeLessThan(page.indexOf('Proposed design'));
    expect(page).toContain('This route runs on the answer path above');
    // The human route keeps its own nodes; the retrieval route's generic nodes are gone.
    expect(page).not.toContain('Index and retrieval');
    expect(page).toContain('Request and evidence');
  });

  it('leaves the proposal summary unchanged', () => {
    expect(diagram(design, 'en')[0].nodes).toEqual(['Public sources', 'Index and retrieval', 'Cited answer']);
  });
});
