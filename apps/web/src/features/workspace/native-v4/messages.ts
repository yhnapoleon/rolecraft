type Translate = (zh: string, en: string) => string;

/** Shared workspace action errors for the native slot and its shell controls. */
export function workspaceActionMessage(code: string, T: Translate): string {
  return (
    (
      {
        restore_failed: T(
          '恢复失败。请查看原请求结果后再决定是否重试。',
          'Restoration failed. Check the original request result before retrying.',
        ),
        restore_pending: T(
          '恢复正在处理中，请查看原请求结果。',
          'Restoration is pending. Check the original request result.',
        ),
        restore_unconfirmed: T(
          '恢复尚未确认，请查看原请求结果。',
          'Restoration is unconfirmed. Check the original request result.',
        ),
        product_unavailable: T('找不到这份作品。', 'This work is unavailable.'),
        draft_conflict: T(
          '工作区有新版本；草稿已保留，请比较后保存或另存。',
          'The workspace has a newer version. Compare before saving, or save a copy.',
        ),
        comparison_changed: T(
          '比较期间内容又有变化；请重新核对。',
          'Content changed during comparison. Review it again.',
        ),
        save_before_sharing: T(
          '请先保存这份草稿，再分享确切版本。',
          'Save this draft before sharing its exact version.',
        ),
        save_before_removing: T(
          '请先保存草稿，再移除或恢复作品。',
          'Save your draft before removing or restoring the product.',
        ),
        draft_storage_failed: T(
          '本机保存失败，请保留本页文字。',
          'Local saving failed. Keep your text on this page.',
        ),
        action_unavailable: T(
          '这项操作目前不可用，请保留输入。',
          'This action is unavailable. Your input is retained.',
        ),
        workspace_changed_during_read: T(
          '读取期间工作区有变化，请重新读取。',
          'The workspace changed while reading. Refresh to read it again.',
        ),
        task_title_required: T('先写事项名称。', 'Enter a task title first.'),
        session_changed: T(
          '练习已切换；原输入已保留。',
          'The session changed. The original input is retained.',
        ),
        unconfirmed_saved_content: T(
          '保存结果尚未确认，原草稿仍保留。',
          'The saved result is not confirmed. Your draft is retained.',
        ),
      } as Record<string, string>
    )[code] ?? T('操作未完成，输入已保留。', 'The action did not complete. Your input is retained.')
  );
}
