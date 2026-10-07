/** Authored UI copy uses paired texts. Stored feedback and quotes are untouched. */
export type FeedbackLanguage = 'zh' | 'en';
export function feedbackText(language:FeedbackLanguage,zh:string,en:string) {
  return language==='en'?en:zh;
}
