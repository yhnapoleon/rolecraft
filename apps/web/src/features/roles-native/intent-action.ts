/** A saved intent can offer an entry point, never a command or an approval. */
import type { RecognitionRecord } from '../recognition-native/badge';
import type { Language } from '../results-native/localization';
import type { MaterialReference } from './index';

/** A conservative UI gate, not a calibrated confidence claim. */
export const INTENT_ACTION_MIN_SCORE = 0.7;
export function intentAction(
  records: readonly RecognitionRecord[] | undefined,
  materials: readonly MaterialReference[] | undefined,
  language: Language,
) {
  const record = [...(records ?? [])].reverse().find((r) => r.task === 'intent');
  if (
    !record ||
    typeof record.score !== 'number' ||
    !Number.isFinite(record.score) ||
    record.score < INTENT_ACTION_MIN_SCORE ||
    record.score > 1
  )
    return null;
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  if (record.label === 'seek_approval' || record.label === 'ask_resource')
    return {
      kind: 'request' as const,
      label: t('查看申请入口', 'Open the request form'),
      reason:
        record.label === 'seek_approval'
          ? t(
              '因为你在问批准。打开你自己的申请表，由你填写和发送。',
              'You asked about approval. Open your request form; you decide what to write and send.',
            )
          : t(
              '因为你在问资源。打开你自己的申请表，由你填写和发送。',
              'You asked about resources. Open your request form; you decide what to write and send.',
            ),
    };
  // Only the exact process source cited in this reply is offered; never guess a destination.
  const process = materials?.find((m) => m.id === 'approvals');
  if (record.label === 'ask_process' && process)
    return {
      kind: 'material' as const,
      material: process,
      label: t('查看申请流程', 'Read the request process'),
      reason: t(
        '因为你在问流程。打开这条回复引用的申请说明。',
        'You asked about the process. Open the request instructions cited in this reply.',
      ),
    };
  return null;
}
