/** Work provenance uses the saved author's identity; a browser transfer link is optional. */
export function workSourceLabel(work, language, authorKind) {
  const text = (zh, en) => language === 'en' ? en : zh;
  if (authorKind === 'external_agent' || (!authorKind && work.requestId)) {
    return work.adopted
      ? text('Agent 制作 · 本人采用', 'Made by an Agent · Adopted by you')
      : text('Agent 制作 · 待本人采用', 'Made by an Agent · Awaiting your adoption');
  }
  return work.source === 'user' ? text('你写的', 'By you') : work.requestId ? text('来自你的 Agent', 'From your agent') : text('导入的作品', 'Imported work');
}
