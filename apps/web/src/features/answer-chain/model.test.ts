import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from '../recognition-native/badge';
import type * as C from '../../contracts-v2';
import { answerChain, fromTestResult, fromWorkbenchRun, type ChainInput } from './model';

const scope = (label: 'in' | 'out', extra: Partial<RecognitionRecord> = {}): RecognitionRecord => ({
  recognizer_id: 'scope.mahalanobis',
  revision: 'e5-small-fit-1',
  task: 'scope',
  label,
  score: label === 'out' ? 3.91234 : 1.2345,
  threshold: 2.8,
  outputs: { fit_key: 'pm_pilot/en/scope_on', rule_hit: true },
  ...extra,
});
const scopeFallback: RecognitionRecord = {
  recognizer_id: 'scope.mahalanobis',
  revision: 'rule-fallback',
  task: 'scope',
  label: 'in',
  outputs: { fit_key: 'k', rule: 'no_retrieval_hit' },
};
const retrieval = (method = 'rrf', fallback = false, passing = 3): RecognitionRecord => ({
  recognizer_id: 'retrieval.hybrid',
  revision: fallback ? 'rule-fallback' : method,
  task: 'retrieval',
  label: 'policy',
  fallback,
  outputs: { method, passing, min_score: 0.35 },
});
const config = {
  scope_filter: true,
  update_strategy: 'daily' as const,
  freshness_guard: 'none' as const,
  fallback: 'human' as const,
  generator: 'extractive' as const,
  retrieval_limit: 3,
  min_score: 0.35,
};
const run = (over: Partial<ChainInput> = {}): ChainInput => ({
  status: 'answered',
  errorCode: null,
  mode: 'extractive',
  stale: false,
  citations: [{ id: 'policy', version: 1, title: 'Expense notice: travel lodging' }],
  sourceVersions: { policy: 1, faq: 1 },
  indexedVersions: { policy: 1, faq: 1 },
  config,
  recognition: [scope('in'), retrieval()],
  currentVersions: { policy: 1, faq: 1 },
  ...over,
});
const states = (input: ChainInput) => answerChain(input, 'en').stages.map((s) => s.state);
const refused = (errorCode: string, status: ChainInput['status'] = 'fallback') =>
  run({ status, errorCode, citations: [], mode: 'extractive' });

describe('answer chain: where each run stops and why', () => {
  it('walks a current, cited answer to the end', () => {
    const view = answerChain(run(), 'en');
    expect(view.stopAt).toBe(4);
    expect(view.tone).toBe('plain');
    expect(states(run())).toEqual(['passed', 'passed', 'passed', 'passed', 'stop']);
    expect(view.reason).toBe(
      'Answered from Expense notice: travel lodging v1, the current version.',
    );
    expect(answerChain(run(), 'zh').reason).toBe(
      '作答：引用《Expense notice: travel lodging》v1，与现行版本一致。',
    );
    expect(view.handover).toBe(false);
  });

  it.each([
    [
      'prohibited_topic',
      0,
      '没有作答：问题碰到了禁区话题，按规则不答。',
      'Not answered: the question touches a restricted topic, so the rules stop it.',
    ],
    [
      'outside_scope_ood',
      0,
      '没有作答：范围检测认为它不是这个助手该答的问题。',
      'Not answered: scope detection judged it outside what this assistant should answer.',
    ],
    [
      'outside_scope',
      0,
      '没有作答：它属于你没开放的知识范围。',
      'Not answered: it belongs to a knowledge area you have not opened.',
    ],
    [
      'no_retrieval_hit',
      1,
      '没有作答：在开放的资料里没找到足够相关的段落。',
      'Not answered: nothing relevant enough was found in the open sources.',
    ],
    [
      'manual_verification_required',
      2,
      '转给人工：按你的设置，这类政策问题由人工核验。',
      'Handed to a person: your settings send this kind of policy question to manual checking.',
    ],
    [
      'stale_source_guard',
      2,
      '转给人工：引用的资料比现行版本旧，按设置转人工。',
      'Handed to a person: the cited source is older than the current version, so it was handed over.',
    ],
  ])('%s stops at step %i', (code, at, zh, en) => {
    const input = refused(code);
    const view = answerChain(input, 'en');
    expect(view.stopAt).toBe(at);
    expect(view.reason).toBe(en);
    expect(answerChain(input, 'zh').reason).toBe(zh);
    const s = states(input);
    for (let i = at + 1; i < 4; i++) expect(s[i]).toBe('skipped');
    expect(s[4]).toBe(at === 4 ? 'stop' : 'passed');
    expect(view.handover).toBe(at === 1 || at === 2);
  });

  it('marks the stale-source guard amber and the manual check plain', () => {
    expect(states(refused('stale_source_guard'))[2]).toBe('warn');
    expect(answerChain(refused('stale_source_guard'), 'en').tone).toBe('warn');
    expect(states(refused('manual_verification_required'))[2]).toBe('stop');
    expect(answerChain(refused('manual_verification_required'), 'en').tone).toBe('plain');
  });

  it('carries an outdated citation through to the end, amber at Up to date?', () => {
    const input = run({
      sourceVersions: { policy: 2 },
      indexedVersions: { policy: 1 },
      stale: true,
    });
    const view = answerChain(input, 'en');
    expect(view.stopAt).toBe(4);
    expect(view.tone).toBe('warn');
    expect(states(input)).toEqual(['passed', 'passed', 'warn', 'passed', 'stop']);
    expect(view.reason).toBe(
      'Answered from an outdated source: Expense notice: travel lodging is now v2, but the answer cites v1.',
    );
    expect(answerChain(input, 'zh').reason).toBe(
      '作答，但资料过期：《Expense notice: travel lodging》现行是 v2，回答引用了 v1。',
    );
    expect(view.handover).toBe(true);
    expect(view.rows[2]).toBe(
      'Up to date? · updates: Daily · when outdated: no action · Expense notice: travel lodging at run time v2, index v1',
    );
  });

  it('answered with a warning', () => {
    const input = run({
      status: 'answered_with_warning',
      sourceVersions: { policy: 2 },
      stale: true,
    });
    const view = answerChain(input, 'en');
    expect(view.reason).toBe(
      'Answered with a warning: it used an older source version and says the source may have changed.',
    );
    expect(answerChain(input, 'zh').reason).toBe(
      '作答并提醒：用的是旧版本资料，回答前加了「资料可能已更新」。',
    );
    expect(view.stages[2].state).toBe('warn');
    expect(view.stages[2].handled).toBe(true);
    expect(view.stages[2].sr).toBe('Up to date?: warned');
    expect(view.tone).toBe('warn');
    // The warning is the fix at work: only an outdated source left as is goes to Daniel.
    expect(view.handover).toBe(false);
  });

  it('answered without a citation', () => {
    const input = run({ citations: [] });
    expect(answerChain(input, 'en').reason).toBe('Answered without a citation.');
    expect(answerChain(input, 'zh').reason).toBe('作答：这次回答没有附引用。');
    expect(answerChain(input, 'en').rows[2]).toContain(
      'no citation, so the version cannot be checked',
    );
  });

  it('appends the missing human fallback when the run failed', () => {
    const input = run({
      status: 'failed',
      errorCode: 'no_retrieval_hit',
      citations: [],
      config: { ...config, fallback: 'none' },
    });
    expect(answerChain(input, 'en').reason).toBe(
      'Not answered: nothing relevant enough was found in the open sources. Human fallback is off, so this run failed.',
    );
    expect(answerChain(input, 'zh').reason).toBe(
      '没有作答：在开放的资料里没找到足够相关的段落。没开人工兜底，所以这次失败。',
    );
    expect(answerChain(input, 'en').rows[4]).toBe('Result · failed · human fallback off');
  });

  it('stops at Answer when generation failed or no model was connected', () => {
    const failed = run({
      status: 'failed',
      mode: 'failed',
      errorCode: 'assistant_generation_failed',
      citations: [],
    });
    expect(answerChain(failed, 'en').stopAt).toBe(3);
    expect(answerChain(failed, 'en').reason).toBe(
      "Sources were found, but the model's answer failed validation, so there is no answer.",
    );
    expect(answerChain(failed, 'zh').reason).toBe('找到了资料，但模型生成没有通过校验，没有回答。');
    const missing = run({
      status: 'failed',
      mode: 'unavailable',
      errorCode: 'assistant_model_unavailable',
      citations: [],
    });
    expect(answerChain(missing, 'en').reason).toBe(
      'Model generation was selected, but no model was connected, so there is no answer.',
    );
    expect(answerChain(missing, 'zh').reason).toBe('选了模型生成，但当时没有接入模型，没有回答。');
    expect(answerChain(missing, 'en').handover).toBe(false);
    // An empty-retrieval run with model generation records mode "failed": the earlier step decides.
    const empty = run({
      status: 'fallback',
      mode: 'failed',
      errorCode: 'no_retrieval_hit',
      citations: [],
    });
    expect(answerChain(empty, 'en').stopAt).toBe(1);
  });

  it('says so when an old record keeps neither status nor error code', () => {
    const input = run({ status: null, errorCode: null });
    const view = answerChain(input, 'en');
    expect(view.tone).toBe('unknown');
    expect(view.reason).toBe('This record does not say which path it took.');
    expect(answerChain(input, 'zh').reason).toBe('这条记录没有记下它走了哪条路。');
    expect(view.stages.every((s) => s.state === 'unrecorded')).toBe(true);
    expect(view.handover).toBe(false);
  });

  it('marks a step without its recognition record as unrecorded, keeps the reason from the error code', () => {
    const input = run({ recognition: [] });
    const view = answerChain(input, 'en');
    expect(view.stages[0].state).toBe('unrecorded');
    expect(view.stages[1].state).toBe('unrecorded');
    expect(view.stages[0].sr).toBe(
      'In scope?: this record does not cover this step, this step was not recorded',
    );
    expect(view.rows[0]).toBe(
      'In scope? · This record does not include scope detection · scope filter on',
    );
    expect(view.rows[1]).toBe('Found · This record does not cover this step');
    const stopped = answerChain(refused('outside_scope_ood'), 'en');
    expect(stopped.stages[0].state).toBe('stop');
  });

  it('reads screen-reader sentences and marks the stop', () => {
    const view = answerChain(refused('outside_scope_ood'), 'zh');
    expect(view.stages[0].sr).toBe('能不能答：不在范围内，在这里停下');
    expect(view.stages[1].sr).toBe('找到什么：没走到这一步');
    const en = answerChain(run(), 'en');
    expect(en.stages[0].sr).toBe('In scope?: in scope');
    expect(en.stages[4].sr).toBe('Result: answered, stopped here');
  });

  it('writes the expanded rows from the record', () => {
    const view = answerChain(run(), 'en');
    expect(view.rows[0]).toBe(
      'In scope? · out-of-scope detection: in scope (distance 1.23, threshold 2.80) · scope filter on',
    );
    expect(view.rows[1]).toBe(
      'Found · Semantic + keyword retrieval (fused): 3 passages cleared 0.35; top 3 used',
    );
    expect(view.rows[3]).toBe('Answer · Extractive');
    expect(view.rows[4]).toBe('Result · answered · human fallback on');
    const zh = answerChain(run(), 'zh');
    expect(zh.rows[1]).toBe('找到什么 · 语义检索 + 关键词检索融合：3 段过了阈值 0.35，取前 3 段');
    expect(zh.rows[0]).toBe(
      '能不能答 · 范围外检测：在范围内（距离 1.23，阈值 2.80） · 范围过滤：开',
    );
  });

  it('names the fallback retrieval and scope honestly', () => {
    const input = run({
      recognition: [scopeFallback, retrieval('bm25', true, 2)],
    });
    const view = answerChain(input, 'en');
    expect(view.rows[0]).toContain('Scope model not loaded; judged from retrieval (rule)');
    expect(view.rows[1]).toBe(
      'Found · Keyword retrieval (semantic model not loaded): 2 passages cleared 0.35; top 3 used',
    );
    expect(
      answerChain(run({ recognition: [scope('in'), retrieval('dense')] }), 'zh').rows[1],
    ).toContain('语义检索：3 段');
    const unknown = answerChain(run({ recognition: [scope('in'), retrieval('other')] }), 'en');
    expect(unknown.rows[1]).toBe('Found · This record does not say which retrieval method ran');
  });

  it('links each inspectable step to its own record only', () => {
    const view = answerChain(run(), 'en');
    expect(view.stages.map((s) => s.inspect)).toEqual(['scope', 'retrieval', null, null, null]);
    const drift: RecognitionRecord = {
      recognizer_id: 'drift',
      revision: 'x',
      task: 'drift',
      score: 0.1,
    };
    expect(
      answerChain(run({ recognition: [scope('in'), retrieval(), drift] }), 'en').stages[2].inspect,
    ).toBe('drift');
  });

  it('keeps two side-by-side runs independent', () => {
    const before = run();
    const after = run({ sourceVersions: { policy: 2 }, stale: true });
    const views = [after, before].map((x) => answerChain(x, 'en'));
    expect(views[0].tone).toBe('warn');
    expect(views[1].tone).toBe('plain');
    expect(before.sourceVersions.policy).toBe(1);
  });

  it('offers the handover only at Found and Up to date?', () => {
    const handover = (x: ChainInput) => answerChain(x, 'en').handover;
    expect(handover(refused('prohibited_topic'))).toBe(false);
    expect(handover(refused('outside_scope_ood'))).toBe(false);
    expect(handover(refused('no_retrieval_hit'))).toBe(true);
    expect(handover(refused('manual_verification_required'))).toBe(true);
    expect(handover(run())).toBe(false);
    expect(handover(run({ sourceVersions: { policy: 2 } }))).toBe(true);
  });
});

describe('answer chain: flagged or left as is, then and now', () => {
  it('fills the Up to date? ring only when the outdated source was flagged', () => {
    const left = answerChain(run({ sourceVersions: { policy: 2 } }), 'en');
    expect(left.stages[2].state).toBe('warn');
    expect(left.stages[2].handled).toBe(false);
    expect(left.stages[2].sr).toBe('Up to date?: source out of date');
    const guard = answerChain(refused('stale_source_guard'), 'en');
    expect(guard.stages[2].handled).toBe(false);
  });

  it('does not call a version current when today’s versions were not read', () => {
    const unchecked = answerChain(run({ currentVersions: undefined }), 'en');
    expect(unchecked.reason).toBe(
      'Answered from Expense notice: travel lodging v1, current when it ran; whether it is still current was not checked.',
    );
    expect(unchecked.reason).not.toContain('the current version.');
    expect(unchecked.stages[2].sr).toBe('Up to date?: current when it ran');
    expect(answerChain(run({ currentVersions: undefined }), 'zh').reason).toBe(
      '作答：引用《Expense notice: travel lodging》v1，运行时是现行版本；现在是否仍是最新没有核对。',
    );
  });

  it('says "the current version at the time" once the source has changed since the run', () => {
    const then = run({ currentVersions: { policy: 2 } });
    expect(answerChain(then, 'en').reason).toBe(
      'Answered from Expense notice: travel lodging v1, the current version at the time.',
    );
    expect(answerChain(then, 'zh').reason).toBe(
      '作答：引用《Expense notice: travel lodging》v1，当时的现行版本。',
    );
    expect(answerChain(run({ currentVersions: { policy: 1 } }), 'en').reason).toBe(
      'Answered from Expense notice: travel lodging v1, the current version.',
    );
  });
});

describe('answer chain: expanded rows', () => {
  it('counts one passage in the singular', () => {
    const one = answerChain(run({ recognition: [scope('in'), retrieval('rrf', false, 1)] }), 'en');
    expect(one.rows[1]).toContain('1 passage cleared 0.35');
    expect(answerChain(run(), 'en').rows[1]).toContain('3 passages cleared 0.35');
  });
});

describe('answer chain adapters', () => {
  it('reads a workbench run', () => {
    const input = fromWorkbenchRun({
      status: 'answered',
      errorCode: null,
      mode: 'local-extractive-v2',
      stale: true,
      citations: [{ id: 'policy', version: 1, title: 'Travel' }],
      sourceVersions: { policy: 2 },
      indexedVersions: { policy: 1 },
      effectiveConfig: config,
      recognition: [scope('in')],
    });
    expect(input.mode).toBe('extractive');
    expect(input.status).toBe('answered');
    expect(answerChain(input, 'en').tone).toBe('warn');
    const old = fromWorkbenchRun({ mode: 'unknown', citations: [] });
    expect(old.status).toBeNull();
    expect(old.mode).toBeNull();
    expect(old.recognition).toEqual([]);
  });

  it('reads a raw test result with document titles', () => {
    const raw = {
      id: 't1',
      session_id: 's',
      query: 'q',
      answer: 'a',
      status: 'answered',
      error_code: null,
      citations: [
        {
          kind: 'material',
          object_id: 'policy',
          version: 1,
          session_id: 's',
          observed_at_seq: 1,
        },
        {
          kind: 'config',
          object_id: 'c',
          version: 1,
          session_id: 's',
          observed_at_seq: 1,
        },
      ],
      execution: {
        source_versions: { policy: 2 },
        indexed_versions: { policy: 1 },
      },
      config: { effective: config, requested: config },
      recognition: [scope('in'), retrieval()],
    } as unknown as C.TestResultV2;
    const input = fromTestResult(raw, { 'policy:1': 'Travel lodging' });
    expect(input.citations).toEqual([{ id: 'policy', version: 1, title: 'Travel lodging' }]);
    expect(input.stale).toBe(true);
    expect(input.mode).toBeNull();
    expect(answerChain(input, 'en').reason).toBe(
      'Answered from an outdated source: Travel lodging is now v2, but the answer cites v1.',
    );
    expect(answerChain(input, 'en').rows[3]).toBe('Answer · Extractive');
  });
});
