import { describe, expect, it } from 'vitest';
import { describeServerEvent, type EventLookups } from '../../app/event-copy';

const lookups: EventLookups = {
  materialTitle: () => undefined,
  testQuery: () => undefined,
  deliveryNumber: () => undefined,
};
// As the server records it when the engineer card puts the pilot live (engineer/golive.py).
const golive = (note: string) => ({
  type: 'config_applied',
  data: { config_id: 'pilot', config_version: 1, origin: 'engineer_ticket_setup', note },
});

describe('activity · the system go-live for an engineering ticket', () => {
  it('ED-10 says the system set it up for the ticket, not the learner, in both languages', () => {
    const zh = describeServerEvent(
      golive('试点配置已上线（系统为工程委托准备起始状态，不是学员的操作）'),
      lookups,
      'zh',
    );
    expect(zh.text).toBe('试点配置已上线为 v1：系统为工程委托准备的起始状态，不是你的操作');
    expect(zh.world).toBe(true);
    expect(zh.subject).toEqual({ kind: 'settings' });
    // A Chinese-work-language note still reads in the English interface.
    const en = describeServerEvent(golive('试点配置已上线'), lookups, 'en');
    expect(en.text).toBe(
      'Pilot configuration went live as v1: set up by the system for the engineering ticket, not by you',
    );
  });

  it('ED-11 the learner’s own save keeps its wording', () => {
    const own = describeServerEvent(
      { type: 'config_applied', data: { config_id: 'pilot', config_version: 2 } },
      lookups,
      'zh',
    );
    expect(own.text).toBe('试点设置已保存为配置 v2');
    expect(own.world).toBe(false);
  });
});
