import { useEffect, useState } from 'react';
import { companyBrief, patterns } from './content';
import { IDS, type GuideStepView, type GuideView, type ProgressView, type StepId } from './model';
import './guide.css';

export type GuideProps = {
  guide: GuideView;
  progress: ProgressView;
  /** The step's one screen; folded it leaves the ~50px bar. */
  open: boolean;
  /** Explicit fake data (development only), labelled as such. */
  fixture?: boolean;
  stale?: boolean;
  updatedAt?: string;
  busy?: boolean;
  error?: string;
  onChoose(id: StepId): void;
  onQuestion(role: GuideStepView['questions'][number]['role'], text: string): void;
  onMaterial(id: string): void;
  onPrimary(step: GuideStepView): void;
  onRefresh(): void;
  onToggle(): void;
};
export function SevenStepGuide(p: GuideProps) {
  const [map, setMap] = useState(false);
  const [agent, setAgent] = useState(false);
  // The sub-step the person chose for each step; otherwise it follows the server's record.
  const [chosen, setChosen] = useState<Partial<Record<StepId, Phase>>>({});
  const demo = useFirstVisitDemo();
  const en = p.guide.language === 'en';
  const t = (zh: string, english: string) => (en ? english : zh);
  // Both lists are the seven steps in order (model.ts refuses anything else).
  const current = p.guide.steps[IDS.indexOf(p.progress.focus)];
  const record = p.progress.steps[IDS.indexOf(p.progress.focus)];
  const suggestion = p.guide.steps[IDS.indexOf(p.progress.suggested)];
  // Step 1's company card already carries its two questions; never show the same one twice.
  const asked = current.id === 'business' ? companyBrief(p.guide.language).questions : [];
  const questions = current.questions.filter((q) => !asked.some((c) => c.text === q.text));
  const phase: Phase = chosen[current.id] ?? phaseOf(record.status);
  const choosePhase = (n: Phase) => {
    setChosen({ ...chosen, [current.id]: n });
    setAgent(false);
  };
  const phaseText: Record<Phase, [string, string, string]> = {
    1: [
      t('了解', 'Understand'),
      t('30 秒短卡，或问同事', 'A 30-second card, or ask'),
      t(
        '第一小步：先看短卡，或点一个问题直接问同事。',
        'First: read the short card, or tap a question to ask a colleague.',
      ),
    ],
    2: [
      t('动手', 'Do'),
      t('写下或选择', 'Write or choose'),
      t(
        '第二小步：动手写下或选择，旁边会说明为什么要做。',
        'Then: write or choose; it says why it matters.',
      ),
    ],
    3: [
      t('拿反馈', 'Get feedback'),
      t('看核对结果和下一步', 'See the check and what is next'),
      t(
        '第三小步：保存后在这里看反馈，再进入下一步。',
        'Last: after saving, see the feedback here and move on.',
      ),
    ],
  };
  const status = {
    not_started: t('尚未开始', 'Not started'),
    working: t('正在处理', 'Working'),
    recorded: t('已有工作记录', 'Work recorded'),
    recheck: t('需重新核对', 'Recheck needed'),
    uncovered: t('本局未覆盖', 'Not covered'),
  };
  const role = {
    manager: t('Grace · 经理', 'Grace · Manager'),
    business: t('Chen · 业务负责人', 'Chen · Business lead'),
    technical: t('Daniel · 技术负责人', 'Daniel · Technical lead'),
  };
  const source: Record<string, string> = {
    rule: t('规则核实', 'Rule check'),
    authored_guidance: t('场景引导', 'Authored guidance'),
    colleague_opinion: t('同事意见', 'Colleague opinion'),
    model_suggestion: t('模型建议', 'Model suggestion'),
    learner_assessment: t('本人判断', 'Your assessment'),
  };
  return (
    <section
      className={`aipm-guide ${p.open ? '' : 'aipm-guide--compact'}`}
      aria-label={t('七步工作引导', 'Seven-step work guide')}
    >
      <div className="aipm-guide__bar">
        <span className="aipm-guide__number">
          {String(current.order).padStart(2, '0')}
          <small> / 07</small>
        </span>
        <div className="aipm-guide__location">
          <span>{t('正在处理', 'Working on')}</span>
          <strong>{current.label}</strong>
        </div>
        {p.fixture && (
          <span className="aipm-guide__fixture">
            {t('假数据 · 接口未就绪', 'Fake data · not connected')}
          </span>
        )}
        <button
          type="button"
          className="btn quiet small"
          aria-expanded={p.open}
          onClick={p.onToggle}
        >
          {p.open ? t('收起引导', 'Fold the guide') : t('本步引导', 'Step guide')}
        </button>
        <button
          type="button"
          className="btn quiet small"
          aria-expanded={map}
          onClick={() => setMap(!map)}
        >
          {t('工作地图', 'Work map')}
        </button>
      </div>
      {map && (
        <nav
          className="aipm-guide__map"
          aria-label={t('选择正在处理的步骤', 'Choose the step to work on')}
        >
          <p>
            {t(
              '可随时跳转。已有记录不代表已经掌握。',
              'Move freely. Recorded work does not imply mastery.',
            )}
          </p>
          {p.progress.steps.map((s) => (
            <button
              type="button"
              key={s.id}
              aria-current={s.id === current.id ? 'step' : undefined}
              disabled={p.busy || p.stale}
              onClick={() => {
                p.onChoose(s.id);
                setMap(false);
              }}
            >
              <span>{s.order}</span>
              <strong>{s.label}</strong>
              <small>{status[s.status]}</small>
            </button>
          ))}
        </nav>
      )}
      {p.stale && (
        <p className="aipm-guide__notice" role="status">
          {t('进度暂未更新', 'Progress is not up to date')}
          {p.updatedAt ? ` · ${p.updatedAt}` : ''}{' '}
          <button type="button" className="btn quiet small" onClick={p.onRefresh}>
            {t('重新读取', 'Refresh')}
          </button>
        </p>
      )}
      {!p.progress.complete && (
        <p className="aipm-guide__notice">
          {t(
            '授权范围不足，无法确认完整进度。',
            'Permission scope is insufficient to confirm complete progress.',
          )}
        </p>
      )}
      {p.error && (
        <p role="alert" className="aipm-guide__notice">
          {p.error}
        </p>
      )}
      {p.open && (
        <div className="aipm-guide__paper" key={current.id}>
          <ol className="aipm-phases" aria-label={t('这一步怎么完成', 'How to finish this step')}>
            {PHASES.map((n) => (
              <li key={n}>
                <button
                  type="button"
                  aria-current={n === phase ? 'step' : undefined}
                  data-demo={demo === n || undefined}
                  onClick={() => choosePhase(n)}
                >
                  <span className="aipm-phases__n">{n}</span>
                  <strong>{phaseText[n][0]}</strong>
                  <small className="aipm-phases__hint">{phaseText[n][1]}</small>
                </button>
              </li>
            ))}
          </ol>
          {demo !== null && (
            <p className="aipm-phases__demo" role="status">
              {phaseText[demo][2]}
            </p>
          )}
          <h1>{current.goal}</h1>
          {phase === 1 && (
            <>
              <p className="aipm-guide__summary">{current.summary}</p>
              {current.id === 'business' && (
                <CompanyCard
                  guide={p.guide}
                  role={role}
                  onAsk={p.onQuestion}
                  onMaterial={p.onMaterial}
                />
              )}
              {current.id === 'solution' && <Patterns guide={p.guide} />}
              {questions.length > 0 && (
                <div className="aipm-guide__questions">
                  {questions.map((q) => (
                    <button type="button" key={q.text} onClick={() => p.onQuestion(q.role, q.text)}>
                      <span>{role[q.role]}</span>
                      {q.text}
                      <small>{t('点一下直接发送', 'Send now')} ↗</small>
                    </button>
                  ))}
                </div>
              )}
              <div className="aipm-guide__actions">
                <button type="button" className="btn primary" onClick={() => choosePhase(2)}>
                  {t('了解了，开始动手', 'Got it, start the work')}
                </button>
              </div>
            </>
          )}
          {phase === 2 && (
            <>
              {(current.why || current.feedback) && (
                <dl className="aipm-guide__why">
                  {current.why && (
                    <div>
                      <dt>{t('为什么做', 'Why')}</dt>
                      <dd>{current.why}</dd>
                    </div>
                  )}
                  {current.feedback && (
                    <div>
                      <dt>{t('保存后你会得到', 'What saving gives you')}</dt>
                      <dd>{current.feedback}</dd>
                    </div>
                  )}
                </dl>
              )}
              {current.example && <p className="aipm-guide__example">{current.example}</p>}
              <div className="aipm-guide__actions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={p.busy || p.stale}
                  onClick={() => p.onPrimary(current)}
                >
                  {current.primary.label}
                </button>
                {current.agentBrief && (
                  <button
                    type="button"
                    className="btn quiet"
                    aria-expanded={agent}
                    onClick={() => setAgent(!agent)}
                  >
                    {t('让我的 Agent 帮我写', 'Let my agent draft it')}
                  </button>
                )}
              </div>
              {agent && current.agentBrief && (
                <AgentBrief step={current} language={p.guide.language} />
              )}
            </>
          )}
          {phase === 3 && (
            <>
              {record.missing.length > 0 || record.feedback.length > 0 ? (
                <div className="aipm-guide__findings">
                  {record.feedback.slice(0, 2).map((f) => (
                    <p key={f.message}>
                      <b>
                        {source[f.source] ?? t('待核对', 'Unverified')}
                        {f.stale ? t(' · 已过期', ' · Outdated') : ''}
                      </b>{' '}
                      {f.message}
                    </p>
                  ))}
                  {record.missing.slice(0, 2).map((m) => (
                    <p key={m}>{m}</p>
                  ))}
                </div>
              ) : (
                <p className="aipm-guide__summary">
                  {record.status === 'recorded'
                    ? t(
                        '这一步已有工作记录，暂时没有需要处理的反馈。记录不代表已经掌握。',
                        'This step has recorded work and no open feedback. Recorded work does not mean mastery.',
                      )
                    : t(
                        '还没有可核对的内容。保存后，针对你内容的反馈会出现在这里。',
                        'Nothing to check yet. Once you save, feedback on your work appears here.',
                      )}
                </p>
              )}
              {current.feedback && record.status !== 'recorded' && (
                <p className="aipm-guide__example">{current.feedback}</p>
              )}
              <div className="aipm-guide__actions">
                {suggestion.id !== current.id ? (
                  <button
                    type="button"
                    className="btn primary"
                    disabled={p.busy || p.stale}
                    onClick={() => p.onChoose(suggestion.id)}
                  >
                    {t('下一步：', 'Next: ')}
                    {suggestion.label}
                  </button>
                ) : (
                  <button type="button" className="btn primary" onClick={() => choosePhase(2)}>
                    {t('回去修改', 'Back to the work')}
                  </button>
                )}
              </div>
            </>
          )}
          <details className="aipm-guide__help">
            <summary>{t('展开解释与依据', 'Explanation and sources')}</summary>
            <p>{current.explanation}</p>
            <p>{current.outputs.join(' · ')}</p>
            <div>
              {current.materialIds.map((id) => (
                <button
                  type="button"
                  className="btn quiet small"
                  key={id}
                  onClick={() => p.onMaterial(id)}
                >
                  {materialLabel(id, en)}
                </button>
              ))}
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
type Phase = 1 | 2 | 3;
const PHASES: Phase[] = [1, 2, 3];
// Nothing yet → understand; work under way → do; recorded or to recheck → feedback.
const phaseOf = (status: ProgressView['steps'][number]['status']): Phase =>
  status === 'recorded' || status === 'recheck' ? 3 : status === 'working' ? 2 : 1;

const DEMO = 'rolecraft.aipm.demo.v1';
/** On the very first guide this browser shows, light the three sub-steps one by one (about three
 * seconds), then stop for good. Reduced motion skips it. */
function useFirstVisitDemo(): Phase | null {
  const [at, setAt] = useState<Phase | null>(() => {
    try {
      if (localStorage.getItem(DEMO)) return null;
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return null;
      return 1;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (at === null) return;
    const timer = setTimeout(() => {
      if (at < 3) setAt((at + 1) as Phase);
      else {
        setAt(null);
        try {
          localStorage.setItem(DEMO, '1');
        } catch {
          /* this page only */
        }
      }
    }, 1100);
    return () => clearTimeout(timer);
  }, [at]);
  return at;
}

// What to hand the learner's own agent: what to write, where it goes, and that a person checks it.
function AgentBrief({ step, language }: { step: GuideStepView; language: GuideView['language'] }) {
  const en = language === 'en';
  const [copied, setCopied] = useState(false);
  const text = en
    ? `${step.agentBrief}\n\nWhere it goes: step ${step.order}, “${step.label}”, of my RoleCraft practice. If you are connected to RoleCraft (MCP), read this practice’s materials and progress first. Give me the draft; I will check it and save it myself.`
    : `${step.agentBrief}\n\n写到哪里：我的 RoleCraft 这一局第 ${step.order} 步「${step.label}」。如果你已连接 RoleCraft（MCP），先读取这一局的资料和进度。写好后把草稿交给我，由我核对后保存。`;
  return (
    <div className="aipm-agent">
      <p>
        {en
          ? 'Copy this to your agent. It drafts; you check and save.'
          : '把下面这段复制给你的 Agent。它起草，你核对后保存。'}
      </p>
      <pre>{text}</pre>
      <button
        type="button"
        className="btn small"
        onClick={() =>
          void navigator.clipboard?.writeText(text).then(
            () => setCopied(true),
            () => setCopied(false),
          )
        }
      >
        {copied ? (en ? 'Copied' : '已复制') : en ? 'Copy' : '复制'}
      </button>
    </div>
  );
}
// Step 1's short card: what the company sells, whom this pilot serves, and who decides.
function CompanyCard(p: {
  guide: GuideView;
  role: Record<GuideStepView['questions'][number]['role'], string>;
  onAsk: GuideProps['onQuestion'];
  onMaterial: GuideProps['onMaterial'];
}) {
  const c = companyBrief(p.guide.language);
  if (c.revision !== p.guide.revision) return null;
  const en = p.guide.language === 'en';
  const shown = c.sentences.slice(0, 3);
  const rest = c.sentences.slice(3);
  const sources = [...new Set(c.sentences.flatMap((s) => s.materials))];
  return (
    <aside className="aipm-company" aria-label={c.title}>
      <p className="aipm-company__head">
        <strong>{c.title}</strong>
        {c.pending && <span>{c.statusLabel}</span>}
      </p>
      <p>{shown.map((s) => s.text).join('')}</p>
      <details>
        <summary>{en ? 'Read the whole brief' : '展开全文'}</summary>
        <p>{rest.map((s) => s.text).join(en ? ' ' : '')}</p>
        <div>
          {sources.map((id) => (
            <button
              type="button"
              className="btn quiet small"
              key={id}
              onClick={() => p.onMaterial(id)}
            >
              {materialLabel(id, en)}
            </button>
          ))}
        </div>
      </details>
      <div className="aipm-company__ask">
        {c.questions.map((q) => (
          <button
            type="button"
            className="btn small"
            key={q.text}
            onClick={() => p.onAsk(q.role, q.text)}
          >
            {en ? 'Ask ' : '问 '}
            {p.role[q.role].split(' · ')[0]}
            <small>{q.text}</small>
          </button>
        ))}
      </div>
    </aside>
  );
}
// Step 5: four public reference patterns to compare against, each with its own source.
function Patterns({ guide }: { guide: GuideView }) {
  const set = patterns(guide.language);
  const en = guide.language === 'en';
  return (
    <details className="aipm-patterns">
      <summary>
        {en ? 'Compare four reference patterns' : '比较四种公开做法'}
        <small>{set.label}</small>
      </summary>
      <dl>
        {set.cards.map((c) => (
          <div key={c.id}>
            <dt>{c.title}</dt>
            <dd>{c.when}</dd>
            <dd>
              {en ? 'Cost: ' : '代价：'}
              {c.cost}
            </dd>
            <dd>
              {en ? 'Not for: ' : '不适用：'}
              {c.whenNot}
            </dd>
            <dd>
              <a href={c.source.url} target="_blank" rel="noreferrer">
                {c.source.title}
              </a>{' '}
              · {en ? 'accessed ' : '查阅于 '}
              {c.source.accessed}
            </dd>
          </div>
        ))}
      </dl>
      <p>{set.note}</p>
    </details>
  );
}
export function materialLabel(id: string, en: boolean) {
  const labels: Record<string, [string, string]> = {
    brief: ['经理委托与公司背景', 'Manager’s brief and company context'],
    user_groups: ['候选用户', 'Candidate users'],
    interviews: ['访谈原文', 'Interview notes'],
    approvals: ['资源与批准规则', 'Resources and approval rules'],
    demand: ['咨询样本与时间口径', 'Enquiry sample and time definitions'],
    business_case: ['收益测算', 'Benefit estimate'],
    policy: ['政策原文', 'Policy source'],
    faq: ['常见咨询', 'Common enquiries'],
    technical: ['技术说明', 'Technical notes'],
    failures: ['先前测试记录', 'Earlier test records'],
  };
  return labels[id]?.[en ? 1 : 0] ?? (en ? 'Open source material' : '打开原始资料');
}
