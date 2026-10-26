import type { Behavior } from './view';
import type { Language } from '../results-native/localization';
export function behaviorInsights(data: Behavior, language: Language) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const mine = data.sequence.map((r) => r.symbol),
    ref = data.strategy?.reference?.sequence;
  const count = (xs: string[], s: string) => xs.filter((x) => x === s).length;
  const valid =
    !!ref &&
    [...new Set([...mine, ...ref, ...data.alignment.missing, ...data.alignment.extra])].every(
      (s) =>
        count(data.alignment.missing, s) === Math.max(0, count(ref, s) - count(mine, s)) &&
        count(data.alignment.extra, s) === Math.max(0, count(mine, s) - count(ref, s)),
    );
  const suggestions: {
    title: string;
    observation: string;
    practice: string;
    basis: string;
    action?: 'test' | 'business' | 'technical';
    label?: string;
  }[] = [];
  if (!data.window || !ref || !valid) return { valid, suggestions };
  const anomaly: Record<string, [string, string, string]> = {
    policy_update_untested_submit: [
      t('变化后可以再测一次', 'Try another test after a change'),
      t(
        '这段记录标出了变化后直接提交。',
        'The rule flagged a submission after a change in this record.',
      ),
      t(
        '可以选一个受变化影响的问题，比较现在的回答。',
        'Choose a question affected by the change and compare its current answer.',
      ),
    ],
    request_before_technical: [
      t('申请前可以先看技术限制', 'Review technical limits before requesting resources'),
      t(
        '这段记录标出了先申请、后查技术资料。',
        'The rule flagged a request before technical reading.',
      ),
      t('可以先核对资源是否适合这次试点。', 'Check whether the resources fit this pilot.'),
    ],
    configured_before_approval: [
      t('核对尚未获批的配置', 'Review configuration awaiting approval'),
      t(
        '这段记录标出了申请数额尚未获批时的配置。',
        'The rule flagged configuration before approval.',
      ),
      t(
        '可以对照当前批准记录，再决定配置。',
        'Compare the approval record before choosing a configuration.',
      ),
    ],
    repeated_submit_same_config: [
      t('再次提交前，回看新依据', 'Review new evidence before resubmitting'),
      t(
        '这段记录标出了相同配置下的重复提交。',
        'The rule flagged repeated submission with the same configuration.',
      ),
      t(
        '可以看看两次之间新增了什么依据。',
        'Review what evidence changed between the submissions.',
      ),
    ],
  };
  for (const a of data.anomalies) {
    const copy = anomaly[a.rule];
    if (copy && !suggestions.some((s) => s.title === copy[0]))
      suggestions.push({
        title: copy[0],
        observation: copy[1],
        practice: copy[2],
        basis: t(`规则标记 · 记录序号 ${a.at_seq}`, `Rule flag · record sequence ${a.at_seq}`),
      });
  }
  if (!count(mine, 'test:normal') && count(ref, 'test:normal') && count(mine, 'test:policy'))
    suggestions.push({
      title: t('下次可以试一组日常问题', 'Try an everyday question next time'),
      observation: t(
        `你测过政策题。这段记录里还没有日常题，参考做法里有 ${count(ref, 'test:normal')} 次。`,
        `You tested a policy question. This record has no everyday-question tests; the reference has ${count(ref, 'test:normal')}.`,
      ),
      practice: t(
        '如果要判断助手能否承担日常问答，可以再选一个常见问题，写下预期，再看实际回答。',
        'To explore everyday use, choose a typical question, note what you expect, then compare the answer.',
      ),
      basis: t(
        `日常题测试 · 本次 0／参考 ${count(ref, 'test:normal')}`,
        `Everyday-question tests · This record: 0 / Reference: ${count(ref, 'test:normal')}`,
      ),
      action: 'test',
      label: t('去测试台看看', 'Open the test bench'),
    });
  if (
    !mine.some((s) => s.startsWith('ask:business_lead:')) &&
    ref.includes('ask:business_lead:other')
  )
    suggestions.push({
      title: t('需要业务视角时，可以问 Chen', 'Ask Chen if you need a business perspective'),
      observation: t(
        `这段记录没出现与 Chen 的对话；参考做法里有 ${ref.filter((s) => s.startsWith('ask:business_lead:')).length} 次。`,
        `No conversation with Chen appears in this record; the reference includes ${ref.filter((s) => s.startsWith('ask:business_lead:')).length}.`,
      ),
      practice: t('你可以请他补一个业务视角。', 'You can ask him for a business perspective.'),
      basis: t('对照本次与参考的提问记录', 'Based on the question records in both sequences'),
      action: 'business',
      label: t('打开 Chen 的对话', 'Open your conversation with Chen'),
    });
  if (!mine.includes('ask:tech_lead:ask_limit') && ref.includes('ask:tech_lead:ask_limit'))
    suggestions.push({
      title: t(
        '还想确认限制的话，可以问 Daniel',
        'Ask Daniel about limits you still need to clarify',
      ),
      observation: t(
        '这段记录未出现向 Daniel 询问限制；参考做法中有记录。',
        'This record has no question to Daniel about limits; the reference includes one.',
      ),
      practice: t(
        '可以从你还不清楚的限制问起。',
        'Start with a limit you still need to understand.',
      ),
      basis: t('对照本次与参考的限制提问记录', 'Based on recorded questions about limits'),
      action: 'technical',
      label: t('打开 Daniel 的对话', 'Open your conversation with Daniel'),
    });
  return { valid, suggestions: suggestions.slice(0, 2) };
}
