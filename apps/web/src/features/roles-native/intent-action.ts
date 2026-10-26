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
      label: t('打开申请表', 'Open the request form'),
      reason:
        record.label === 'seek_approval'
          ? t(
              '这次提问看起来在询问批准。你可以从申请表继续，内容由你决定。',
              'It looks like you’re asking for approval. Use the form to make a request in your own words.',
            )
          : t(
              '这次提问看起来在询问资源。你可以从申请表继续。',
              'It looks like you’re asking about resources. The request form is a possible next step.',
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
        '这条回复引用了申请说明，可以继续查看。',
        'You asked about the process. Open the request instructions cited in this reply.',
      ),
    };
  return null;
}
