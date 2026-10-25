/** Server (v2) timeline events in plain words: one sentence, an icon and the object it is about.
 * Pure: callers supply the titles and test questions they can read, so an event code is never
 * shown and nothing is inferred from server prose. Shared by the activity tab, the Agent log and
 * the evidence reader. */
import { outcomeTerm } from '../features/workspace/native-v4/outcome-copy';
import { personName } from './people.js';

// Colleagues by name (people.js): the manager decides requests, the business lead forwards scope.
const G = personName('manager');
const C = personName('business');

export type CopyLanguage = 'zh' | 'en';
export type EventRef = {
  readonly kind: string;
  readonly object_id: string;
  readonly version?: number;
};
export type ServerEvent = {
  readonly type: string;
  readonly data?: Readonly<Record<string, unknown>>;
  readonly refs?: readonly EventRef[];
};
export type EventLookups = {
  /** The document's one name (see reference-catalog `documentName`), whichever version is meant. */
  materialTitle(id: string): string | undefined;
  testQuery(id: string): string | undefined;
  /** Which delivery of this practice a submission was (1-based), when known. */
  deliveryNumber(submissionId: string): number | undefined;
};
export type EventSubject =
  | { kind: 'material'; id: string; version?: number; compare: boolean }
  | { kind: 'test'; id: string }
  | { kind: 'settings' }
  | { kind: 'resources' }
  | { kind: 'bench' }
  | { kind: 'review' };
export type EventCopy = {
  text: string;
  icon: string;
  tone?: 'warn' | 'good';
  /** A change from outside the learner's own task: shown in every task scope. */
  world: boolean;
  subject?: EventSubject;
};

type Pair = readonly [zh: string, en: string];
const RESOURCES = ['capacity', 'dev_days', 'deadline_day'];

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const count = (value: unknown): number | undefined =>
  Number.isInteger(value) ? (value as number) : undefined;

/** Resource terms in words (the outcome preview's names); unknown keys are left out rather
 * than shown as codes. */
export function termsText(value: unknown, language: CopyLanguage): string {
  const parts = Object.entries(record(value)).flatMap(([key, raw]) => {
    const n = count(raw);
    return RESOURCES.includes(key) && n !== undefined
      ? [`${outcomeTerm(language, 'resource', key)} ${n}`]
      : [];
  });
  return parts.join(language === 'en' ? ', ' : '、');
}

/** Documents whose version moved between the two version maps, in map order. */
function changedDocuments(data: Readonly<Record<string, unknown>>) {
  const before = record(data.before_versions),
    after = record(data.after_versions);
  return Object.entries(after).flatMap(([id, raw]) => {
    const version = count(raw);
    return version !== undefined && version !== count(before[id]) ? [{ id, version }] : [];
  });
}

export function describeServerEvent(
  event: ServerEvent,
  lookups: EventLookups,
  language: CopyLanguage,
): EventCopy {
  const say = ([zh, en]: Pair) => (language === 'en' ? en : zh);
  const data = event.data ?? {};
  const first = (kind: string) => event.refs?.find((ref) => ref.kind === kind);
  const quoted = (title: string) => (language === 'en' ? `“${title}”` : `《${title}》`);
  // Chinese closes the title mark without a space: 《差旅政策》v2; English: “Travel policy” v2.
  const versioned = (title: string, version?: number) =>
    quoted(title) + (version === undefined ? '' : (language === 'en' ? ' v' : 'v') + version);
  const documents = (list: { id: string; version: number }[]) =>
    list
      .map(({ id, version }) => {
        const title = lookups.materialTitle(id);
        return title ? versioned(title, version) : '';
      })
      .filter(Boolean)
      .join(language === 'en' ? ', ' : '、');
  const withTerms = (lead: Pair, bare: Pair, value: unknown) => {
    const terms = termsText(value, language);
    return terms ? say(lead) + terms : say(bare);
  };
  const resources: EventSubject = { kind: 'resources' };

  switch (event.type) {
    case 'material_read':
    case 'read_material': {
      const id = typeof data.material_id === 'string' ? data.material_id : '';
      const version = count(data.version);
      const title = id ? lookups.materialTitle(id) : undefined;
      return {
        text: title
          ? say(['读了', 'Read ']) + versioned(title, version)
          : say(['读了一份资料', 'Read a document']),
        icon: 'doc',
        world: false,
        ...(id ? { subject: { kind: 'material', id, version, compare: false } } : {}),
      };
    }
    case 'test_assistant': {
      const test = first('test');
      const query = test ? lookups.testQuery(test.object_id) : undefined;
      return {
        text: query ? say(['测试：', 'Test: ']) + query : say(['运行了一次测试', 'Ran a test']),
        icon: 'flask',
        world: false,
        ...(test && query ? { subject: { kind: 'test', id: test.object_id } } : {}),
      };
    }
    case 'config_applied': {
      const version = count(data.config_version);
      // The engineer card's system go-live (engineer/golive.py): the system put the pilot live so
      // the ticket's failure exists; it is not the learner's action. Its own note is in the work
      // language only, so the line is written here in both.
      if (data.origin === 'engineer_ticket_setup')
        return {
          text:
            (version === undefined
              ? say(['试点配置已上线', 'Pilot configuration went live'])
              : say(['试点配置已上线为 v', 'Pilot configuration went live as v']) + version) +
            say([
              '：系统为工程委托准备的起始状态，不是你的操作',
              ': set up by the system for the engineering ticket, not by you',
            ]),
          icon: 'gear',
          world: true,
          subject: { kind: 'settings' },
        };
      return {
        text:
          version === undefined
            ? say(['试点设置已保存', 'Pilot settings saved'])
            : say(['试点设置已保存为配置 v', 'Pilot settings saved as config v']) + version,
        icon: 'gear',
        world: false,
        subject: { kind: 'settings' },
      };
    }
    case 'index_refreshed': {
      const moved = documents(changedDocuments(data));
      return {
        text: moved
          ? say(['助手索引已刷新：', 'Assistant index refreshed: ']) + moved
          : say(['助手索引已刷新', 'Assistant index refreshed']),
        icon: 'refresh',
        world: false,
        subject: { kind: 'bench' },
      };
    }
    case 'business_requested':
      return {
        text: withTerms(
          [`向 ${G} 申请：`, `Asked ${G} for: `],
          [`向 ${G} 提交了申请`, `Sent ${G} a request`],
          data.requested,
        ),
        icon: 'hand',
        world: false,
        subject: resources,
      };
    case 'business_decided': {
      const status = data.status;
      if (status === 'approved' || status === 'accepted')
        return {
          text:
            status === 'approved'
              ? withTerms(
                  [`${G} 批准了申请：`, `${G} approved: `],
                  [`${G} 批准了申请`, `${G} approved the request`],
                  data.granted,
                )
              : withTerms(
                  ['还价已确认：', 'Counteroffer confirmed: '],
                  ['还价已确认', 'Counteroffer confirmed'],
                  data.granted,
                ),
          icon: 'check',
          tone: 'good',
          world: true,
          subject: resources,
        };
      return {
        text:
          status === 'rejected'
            ? say([`${G} 没有批准这次申请`, `${G} did not approve the request`])
            : status === 'countered'
              ? withTerms(
                  [`${G} 给出还价：`, `${G} countered: `],
                  [`${G} 给出了还价`, `${G} made a counteroffer`],
                  data.countered,
                )
              : say([`${G} 回复了申请`, `${G} answered the request`]),
        icon: 'hand',
        world: true,
        subject: resources,
      };
    }
    case 'business_counteroffer_accepted':
      return {
        text: say([`你接受了 ${G} 的还价`, `You accepted ${G}’s counteroffer`]),
        icon: 'check',
        world: true,
        subject: resources,
      };
    case 'resource_grant_committed':
      return {
        text: withTerms(
          ['资源已生效：', 'Resources in effect: '],
          ['资源已生效', 'Resources in effect'],
          data.granted,
        ),
        icon: 'check',
        tone: 'good',
        world: true,
        subject: resources,
      };
    case 'submitted': {
      const submission = first('submission');
      const n = submission ? lookups.deliveryNumber(submission.object_id) : undefined;
      return {
        text:
          n === undefined
            ? say(['交付已提交', 'Delivery submitted'])
            : language === 'en'
              ? `Delivery ${n} submitted`
              : `第 ${n} 次交付已提交`,
        icon: 'stamp',
        world: false,
        subject: { kind: 'review' },
      };
    }
    case 'revision_opened':
      return {
        text: say(['开始修订', 'Started a revision']),
        icon: 'edit',
        world: false,
        subject: { kind: 'review' },
      };
    case 'pause':
      return { text: say(['暂停了练习', 'Paused the practice']), icon: 'pause', world: false };
    case 'resume':
      return { text: say(['恢复了练习', 'Resumed the practice']), icon: 'play', world: false };
  }
  const moved = changedDocuments(data);
  if (moved.length) {
    // A scenario's business event: the world changed one or more documents.
    const named = documents(moved);
    const lead: Pair =
      event.type === 'demo_schedule_changed'
        ? [`${G} 改了演示安排`, `${G} changed the demo schedule`]
        : event.type === 'business_scope_requested'
          ? [`${C} 转来新的范围请求`, `${C} forwarded a new scope request`]
          : ['资料更新', 'Document updated'];
    const { id, version } = moved[0];
    return {
      text: named ? say(lead) + say(['：', ': ']) + named : say(lead),
      icon: event.type === 'demo_schedule_changed' ? 'calendar' : 'bolt',
      tone: 'warn',
      world: true,
      subject: { kind: 'material', id, version, compare: version > 1 },
    };
  }
  return { text: say(['记录了一项变化', 'A change was recorded']), icon: 'info', world: false };
}
