import { useState } from 'react';
import type { GuideStepView, GuideView, ProgressView, StepId } from './model';
import './guide.css';

export type GuideProps = {
  guide: GuideView;
  progress: ProgressView;
  compact?: boolean;
  stale?: boolean;
  updatedAt?: string;
  busy?: boolean;
  error?: string;
  onChoose(id: StepId): void;
  onQuestion(role: GuideStepView['questions'][number]['role'], text: string): void;
  onMaterial(id: string): void;
  onPrimary(step: GuideStepView): void;
  onRefresh(): void;
  onCompany(): void;
  onPatterns(): void;
};
export function SevenStepGuide(p: GuideProps) {
  const [map, setMap] = useState(false);
  const en = p.guide.language === 'en';
  const t = (zh: string, english: string) => (en ? english : zh);
  const current = p.guide.steps.find((s) => s.id === p.progress.focus)!;
  const record = p.progress.steps.find((s) => s.id === current.id)!;
  const suggestion = p.guide.steps.find((s) => s.id === p.progress.suggested)!;
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
      className={`aipm-guide ${p.compact ? 'aipm-guide--compact' : ''}`}
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
      {!p.compact && (
        <div className="aipm-guide__paper" key={current.id}>
          <p className="aipm-guide__eyebrow">
            {t('场景引导', 'Authored guidance')} · {status[record.status]}
          </p>
          <h1>{current.goal}</h1>
          <p className="aipm-guide__summary">{current.summary}</p>
          {current.id === 'business' && (
            <button type="button" className="btn quiet small" onClick={p.onCompany}>
              {t('公司一页纸 · 待用户确认', 'Company brief · Pending user confirmation')}
            </button>
          )}
          {current.id === 'solution' && (
            <button type="button" className="btn quiet small" onClick={p.onPatterns}>
              {t('比较四种公开做法', 'Compare four reference patterns')}
            </button>
          )}
          <div className="aipm-guide__questions">
            {current.questions.map((q) => (
              <button type="button" key={q.text} onClick={() => p.onQuestion(q.role, q.text)}>
                <span>{role[q.role]}</span>
                {q.text}
                <small>{t('放入提问框', 'Draft a question')} ↗</small>
              </button>
            ))}
          </div>
          {(record.missing.length > 0 || record.feedback.length > 0) && (
            <div className="aipm-guide__findings">
              {record.feedback.slice(0, 1).map((f) => (
                <p key={f.message}>
                  <b>
                    {source[f.source] ?? t('待核对', 'Unverified')}
                    {f.stale ? t(' · 已过期', ' · Outdated') : ''}
                  </b>{' '}
                  {f.message}
                </p>
              ))}
              {record.missing.slice(0, 1).map((m) => (
                <p key={m}>{m}</p>
              ))}
            </div>
          )}
          <div className="aipm-guide__actions">
            <button
              type="button"
              className="btn primary"
              disabled={p.busy || p.stale}
              onClick={() => p.onPrimary(current)}
            >
              {current.primary.label}
            </button>
            <span>{t('可求助、回看或提前作决定', 'Ask for help, revisit or decide early')}</span>
          </div>
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
          {suggestion.id !== current.id && (
            <p className="aipm-guide__suggestion">
              {t('建议下一步：', 'Suggested next: ')}
              <button
                type="button"
                disabled={p.busy || p.stale}
                onClick={() => p.onChoose(suggestion.id)}
              >
                {suggestion.label}
              </button>
            </p>
          )}
        </div>
      )}
    </section>
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
