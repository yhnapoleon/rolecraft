import { personName, personTitle } from '../../app/people.js';
export type Job = 'pm' | 'engineer';
export type Person = 'manager' | 'business' | 'technical';
export type Language = 'zh' | 'en';
export const orderFor = (job: Job): Person[] =>
  job === 'pm' ? ['manager', 'business', 'technical'] : ['manager', 'technical', 'business'];
export const ARRIVAL_DELAYS = [0, 2600, 5400] as const;

/** Authored openings, not turns or model input. No scenario-specific numbers are assumed. */
export function introduction(job: Job, person: Person, language: Language) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const name = personName(person);
  const title = personTitle(person, language);
  const hello = t(`你好，我是 ${name}，${title}。`, `Hi, I’m ${name}, the ${title}.`);
  const body =
    person === 'manager'
      ? job === 'pm'
        ? t(
            '这次由你判断知识助手能不能试点。先试一个员工会问的问题，再带着证据告诉我怎么推进。目标、优先级或资源拿不准，就来找我。',
            'You’re deciding whether the knowledge assistant is ready for a pilot. Try a question an employee would ask, then bring me your recommendation and evidence. Come to me about priorities, resources, or what we need before launch.',
          )
        : t(
            '我负责产品侧，也会接收你的修复报告。先复现委托里的问题，再做改动、试跑并签字。要确认修到什么程度、报告交回后怎么处理，直接问我。',
            'I’m your contact on the product side, and I’ll receive your repair report. Reproduce the issue in the ticket, make a change, test it and sign your report. Ask me what the repair needs to achieve or what happens when you hand it back.',
          )
      : person === 'business'
        ? job === 'pm'
          ? t(
              '我关心首批用户到底需要什么，以及助手能不能帮上忙。选先服务谁、理清使用流程或判断试点有没有用时，找我一起看。',
              'I focus on what our first users need and whether the assistant will help. Talk to me when choosing whom to start with, understanding their workflow, or deciding what a useful pilot would look like.',
            )
          : t(
              '我关心改动会怎样影响使用助手的同事。要了解员工怎么提问、遇到问题怎样接管，或者修复会不会妨碍正常使用，可以来问我。',
              'I care about how a change affects the people using the assistant. Ask me how employees use it, what happens when an answer needs a person, or whether a fix could get in their way.',
            )
        : job === 'pm'
          ? t(
              '我管系统限制、索引和测试证据。回答不对、政策变了，或者你想确认改动有没有用，带着问题和那次测试来找我。需要工程修复也可以交给我。',
              'I look after system limits, the index and test evidence. If an answer looks wrong, policy has changed, or you need to check a change, bring me the question and its test run. You can also hand me a repair to investigate.',
            )
          : t(
              '我负责技术边界、索引和测试证据。先分清问题能否复现、改动有没有修好它、是否带来回归。卡在配置或结果解释上，就带着测试来问我。',
              'I’m here for technical constraints, indexing and test evidence. Keep reproduction, the fix and regression checks separate. If a setting or a result is unclear, bring me the test and we’ll look at it.',
            );
  const questions =
    person === 'manager'
      ? job === 'pm'
        ? [
            t(
              '这次试点你最希望我先确认什么？',
              'What should I establish first before recommending a pilot?',
            ),
            t(
              '当前的资源和期限有哪些限制？',
              'What resource and timing constraints should I work within?',
            ),
          ]
        : [
            t(
              '这张委托修到什么程度才算完成？',
              'What would count as a completed repair for this ticket?',
            ),
            t(
              '签字报告交回后，你会怎样决定是否采用？',
              'How will you decide whether to adopt the change after I hand back my signed report?',
            ),
          ]
      : person === 'business'
        ? [
            t(
              '首批用户是谁，他们最需要解决什么问题？',
              'Who are the first users, and what problems most need solving?',
            ),
            t(
              '助手答不了时，业务上怎样接管？',
              'What should happen in the workflow when the assistant cannot answer?',
            ),
          ]
        : [
            t(
              '我应该先核对哪些系统限制和测试证据？',
              'Which system limits and test evidence should I check first?',
            ),
            t(
              '政策更新后，为什么回答还可能用旧资料？',
              'Why might an answer still use old material after a policy update?',
            ),
          ];
  return { name, title, hello, body, questions };
}
const KEY = 'rolecraft.colleague-greetings.v1';
type Entry = { job: Job; entered: boolean };
type StoragePort = Pick<Storage, 'getItem' | 'setItem'>;
/** Only an explicit new-practice action enrols a session. Recovery and old sessions never do. */
export function greetingStore(storage?: StoragePort) {
  let fallback: Record<string, Entry> = {};
  const read = (): Record<string, Entry> => {
    try {
      const v = JSON.parse(storage?.getItem(KEY) || '{}');
      return v && typeof v === 'object' && !Array.isArray(v) ? { ...fallback, ...v } : fallback;
    } catch {
      return fallback;
    }
  };
  const save = (all: Record<string, Entry>) => {
    fallback = all;
    try {
      storage?.setItem(KEY, JSON.stringify(all));
    } catch {
      /* remains valid for this page */
    }
  };
  return {
    prepare(id: string, job: Job) {
      const all = read();
      if (!all[id]) save({ ...all, [id]: { job, entered: false } });
    },
    job(id: string): Job | null {
      const value = read()[id]?.job;
      return value === 'pm' || value === 'engineer' ? value : null;
    },
    claim(id: string): Job | null {
      const all = read(),
        entry = all[id];
      if (!entry || entry.entered || !['pm', 'engineer'].includes(entry.job)) return null;
      save({ ...all, [id]: { ...entry, entered: true } });
      return entry.job;
    },
  };
}
