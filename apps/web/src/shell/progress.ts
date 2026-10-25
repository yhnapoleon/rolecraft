// The six layers of the problem a practice works through (场景与训练闭环 §4.2): take the brief on,
// understand the problem and who it hits, form a candidate decision, verify and coordinate,
// deliver, then look back and carry on. Read from the person's own records only: a test, a
// note on it, a cited piece of work, an applied setting, a submission. Nothing here counts
// clicks, chat turns or pages read, and a draft on its own never passes a layer. A change in
// the world (a new policy version) reopens only the layer it affects; the frontier stays.
// Pure: the adapter in ui.js builds ProgressFacts from the attempt.

export type LayerId = 'own' | 'understand' | 'decide' | 'verify' | 'deliver' | 'reflect';
export type Text = [zh: string, en: string];

/**
 * done: the layer's evidence is in the records. current: the first layer that is not, the one to
 * work on. reopened: was done, a change since needs it looked at again (the frontier does not move
 * back). todo: ahead. uncovered: delivered without it; kept as a training point, not a failure.
 */
export type LayerState = 'done' | 'current' | 'reopened' | 'todo' | 'uncovered';

export type ProgressFacts = {
  /** The person took the brief on in the walk-in (this browser). */
  accepted?: boolean;
  tests: {
    id: string;
    question?: string;
    answer?: string;
    indexVersion?: number;
    previousTestId?: string;
    /** The policy source version the test ran against. */
    policyVersion: number;
    configVersion: number;
    /** The person wrote what they expected, or a diagnosis, on this run. */
    noted: boolean;
  }[];
  /** Colleagues the person has asked something. */
  asked: ('manager' | 'business' | 'technical')[];
  /** Saved work (server versions, not unsaved local drafts). */
  works: {
    id: string;
    /** The pilot decision (purpose 试点决定), as opposed to notes, plans and option comparisons. */
    decision: boolean;
    hasBody: boolean;
    /** Tests and documents the work cites. */
    evidence: { kind: 'test' | 'material'; id: string }[];
  }[];
  policyVersion: number;
  /** The config version the next test uses; above `baseConfigVersion` once the person applied one. */
  configVersion: number;
  baseConfigVersion: number;
  pendingRequests: number;
  approvedRequests: number;
  delivered: boolean;
  feedback: boolean;
};

export type Layer = {
  id: LayerId;
  n: number;
  label: Text;
  /** What this layer is for, in one line. */
  goal: Text;
  state: LayerState;
  /** What the records already show for this layer. */
  confirmed: Text[];
  /** What is still missing for it. */
  missing: Text[];
  /** Why a done layer needs another look. */
  reopened?: Text;
};

export type Progress = {
  layers: Layer[];
  current: LayerId;
  /** The two layers after the current one (fewer near the end). */
  next: LayerId[];
  /** Business answers still outstanding (requests waiting for a decision), kept across layers. */
  waiting: Text[];
};

const LABEL: Record<LayerId, Text> = {
  own: ['接手责任', 'Take it on'],
  understand: ['弄清问题与影响', 'Understand the problem'],
  decide: ['形成候选决定', 'Form a decision'],
  verify: ['验证与协调', 'Verify and coordinate'],
  deliver: ['明确交付', 'Deliver'],
  reflect: ['复盘与继续', 'Review and carry on'],
};
const GOAL: Record<LayerId, Text> = {
  own: ['弄清你负责什么，先动手试一次', 'Know what you own, then try it once'],
  understand: [
    '谁受影响、依据是什么，把判断和证据连起来',
    'Who it affects and on what evidence: tie a judgement to it',
  ],
  decide: [
    '比较可行方案，写下决定、取舍和成立条件',
    'Compare options; write the decision, the trade-off, what it rests on',
  ],
  verify: [
    '把方案放进实际配置，申请所需资源，再测一次',
    'Put the plan into the settings, ask for what it needs, test again',
  ],
  deliver: ['确认你承担哪些承诺，交给 Grace', 'Say what you commit to and hand it to Grace'],
  reflect: [
    '看反馈，提出异议或修订，换条件再练',
    'Read the feedback, object or revise, practise under new conditions',
  ],
};
export const ORDER: LayerId[] = ['own', 'understand', 'decide', 'verify', 'deliver', 'reflect'];

export const layerLabel = (id: LayerId) => LABEL[id];

const ROLE: Record<string, Text> = {
  manager: ['Grace', 'Grace'],
  business: ['Chen', 'Chen'],
  technical: ['Daniel', 'Daniel'],
};

export function progressOf(f: ProgressFacts): Progress {
  const cited = f.works.filter((w) => w.hasBody && w.evidence.length > 0);
  const noted = f.tests.filter((t) => t.noted);
  const decision = f.works.find((w) => w.decision && w.hasBody);
  const firstPolicy = f.tests.length ? Math.min(...f.tests.map((t) => t.policyVersion)) : null;
  const policyMoved = firstPolicy != null && f.policyVersion > firstPolicy;
  const testedNow = f.tests.some((t) => t.policyVersion === f.policyVersion);
  const applied = f.configVersion > f.baseConfigVersion;
  const retested = applied && f.tests.some((t) => t.configVersion === f.configVersion);
  const T = (zh: string, en: string): Text => [zh, en];

  const own = {
    done: !!f.accepted || f.tests.length > 0 || f.asked.length > 0 || cited.length > 0,
    confirmed: [
      ...(f.accepted ? [T('接下了 Grace 的委托', 'Took on Grace’s brief')] : []),
      ...(f.tests.length ? [T('试过一次助手', 'Tried the assistant once')] : []),
      ...(f.asked.length
        ? [
            T(
              `问过 ${f.asked.map((r) => ROLE[r][0]).join('、')}`,
              `Asked ${f.asked.map((r) => ROLE[r][1]).join(', ')}`,
            ),
          ]
        : []),
    ],
    missing: [T('先试一次助手，或问一位同事', 'Try the assistant once, or ask a colleague')],
  };

  const understand = {
    done: f.tests.length > 0 && (noted.length > 0 || cited.length > 0),
    confirmed: [
      ...(() => {
        const last = f.tests.at(-1);
        if (!last?.answer) return f.tests.length ? [T('测试结果已记录；结论待核对', 'Test results saved; conclusions need checking')] : [];
        const before = last.previousTestId ? f.tests.find(t => t.id === last.previousTestId) : undefined;
        return [before, last].flatMap(t => {
          if (!t?.answer) return [];
          const quote = t.answer.replace(/^#+\s*/, '').replace(/\*\*|__/g, '').trim().split(/[。；;\n]/)[0].slice(0, 90);
          return [T(`索引 v${t.indexVersion ?? '—'} 回答「${quote}」`, `Index v${t.indexVersion ?? '—'} answered “${quote}”`)];
        });
      })(),
      ...(noted.length ? [T('记录含期望或诊断；是否符合仍由你核对', 'Expectations or diagnoses are recorded; you still judge the match')] : []),
      ...(cited.length
        ? [
            T(
              `${cited.length} 份作品引用了依据`,
              `${cited.length} piece${cited.length > 1 ? 's' : ''} of work cite evidence`,
            ),
          ]
        : []),
    ],
    missing: [
      ...(f.tests.length ? [] : [T('还没有测试记录', 'No test on record yet')]),
      ...(noted.length || cited.length
        ? []
        : [
            T(
              '把判断和证据连起来：在测试上写下期望，或在作品里引用它',
              'Tie a judgement to evidence: note what you expected on a test, or cite it in your work',
            ),
          ]),
    ],
    reopened:
      policyMoved && !testedNow
        ? T(
            `差旅政策已更新到 v${f.policyVersion}，还没有在新版本下测过`,
            `The travel policy is now v${f.policyVersion}; nothing tested against it yet`,
          )
        : undefined,
  };

  const decisionOldEvidence =
    !!decision &&
    policyMoved &&
    decision.evidence.some((e) => e.kind === 'test') &&
    !decision.evidence.some(
      (e) =>
        e.kind === 'test' && f.tests.find((t) => t.id === e.id)?.policyVersion === f.policyVersion,
    );
  const decide = {
    done: !!decision && decision.evidence.length > 0,
    confirmed: [
      ...(decision ? [T('写下了试点决定', 'Wrote the pilot decision')] : []),
      ...(decision?.evidence.length
        ? [
            T(
              `决定引用了 ${decision.evidence.length} 条依据`,
              `The decision cites ${decision.evidence.length} piece${decision.evidence.length > 1 ? 's' : ''} of evidence`,
            ),
          ]
        : []),
    ],
    missing: decision
      ? decision.evidence.length
        ? []
        : [
            T(
              '决定还没有引用依据：一篇草稿不算形成决定',
              'The decision cites nothing yet: a draft alone is not a decision',
            ),
          ]
      : [
          T(
            '写下你的试点决定，说明取舍和成立条件',
            'Write your pilot decision: the trade-off and what it rests on',
          ),
        ],
    reopened: decisionOldEvidence
      ? T('决定引用的测试来自旧版政策', 'The decision cites tests run on the old policy')
      : undefined,
  };

  const waiting: Text[] = f.pendingRequests
    ? [
        T(
          `${f.pendingRequests} 项申请还在等批复`,
          `${f.pendingRequests} request${f.pendingRequests > 1 ? 's' : ''} still waiting`,
        ),
      ]
    : [];
  const verify = {
    done: retested,
    confirmed: [
      ...(applied
        ? [T(`配置已应用到 v${f.configVersion}`, `Settings applied as v${f.configVersion}`)]
        : []),
      ...(f.approvedRequests
        ? [
            T(
              `${f.approvedRequests} 项申请已获批`,
              `${f.approvedRequests} request${f.approvedRequests > 1 ? 's' : ''} approved`,
            ),
          ]
        : []),
      ...(retested ? [T('在当前配置下复测过', 'Retested on the current settings')] : []),
    ],
    missing: [
      ...(applied ? [] : [T('把方案应用到设置', 'Apply the plan to the settings')]),
      ...(applied && !retested
        ? [T(`在配置 v${f.configVersion} 下再测一次`, `Test again on settings v${f.configVersion}`)]
        : []),
      ...waiting,
    ],
  };

  const deliver = {
    done: f.delivered,
    confirmed: f.delivered ? [T('已交付', 'Delivered')] : [],
    missing: f.delivered ? [] : [T('选定一个版本，点「交付」', 'Pick a version and press Submit')],
  };

  const reflect = {
    done: false,
    confirmed: f.feedback ? [T('收到了反馈', 'Feedback is in')] : [],
    // Whether the semantic review has finished is only known on the result page; say where to look.
    missing: f.delivered
      ? [T('到结果页读反馈，可以提出异议或修订', 'Read the feedback on the result page; you may object or revise')]
      : [T('交付之后才有反馈', 'Feedback comes after you deliver')],
  };


  const parts: Record<
    LayerId,
    { done: boolean; confirmed: Text[]; missing: Text[]; reopened?: Text }
  > = {
    own,
    understand,
    decide,
    verify,
    deliver,
    reflect,
  };
  // The frontier: delivered means reviewing; otherwise the first layer whose evidence is missing.
  // A reopened layer keeps its place (done) and is flagged; it does not pull the frontier back.
  const current: LayerId = f.delivered
    ? 'reflect'
    : (ORDER.slice(0, 5).find((id) => !parts[id].done) ?? 'deliver');
  const at = ORDER.indexOf(current);
  const layers: Layer[] = ORDER.map((id, i) => {
    const p = parts[id];
    const state: LayerState =
      id === current
        ? 'current'
        : p.done
          ? p.reopened
            ? 'reopened'
            : 'done'
          : f.delivered && i < at
            ? 'uncovered'
            : 'todo';
    return {
      id,
      n: i + 1,
      label: LABEL[id],
      goal: GOAL[id],
      state,
      confirmed: p.confirmed,
      missing: p.done ? [] : p.missing,
      ...(p.done && p.reopened ? { reopened: p.reopened } : {}),
    };
  });
  return { layers, current, next: ORDER.slice(at + 1, at + 3), waiting };
}

/** What carries into the current layer from reopened ones, for its "still missing" line. */
export function carried(p: Progress): Text[] {
  return p.layers
    .filter((l) => l.state === 'reopened' && l.reopened)
    .map((l) => l.reopened as Text);
}

/**
 * The short distillation shown when a layer is passed: what is confirmed, and what is kept open
 * into the next one (missing pieces and pending requests, reopened layers). Built from the same
 * records; it never infers what the person understood.
 */
export function distillation(p: Progress, id: LayerId): { confirmed: Text[]; kept: Text[] } | null {
  const l = p.layers.find((x) => x.id === id);
  if (!l || (l.state !== 'done' && l.state !== 'reopened')) return null;
  return { confirmed: l.confirmed, kept: [...carried(p), ...p.waiting] };
}
