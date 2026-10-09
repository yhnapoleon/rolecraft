/** Read-only references and explicit evidence selection in the existing v4 surfaces. */
import type { V4HostAdapter } from './v4-host';
import type { EvidenceRefV2, ObjectRef } from './contracts-v2';
import { T } from './app/i18n';

const names = () => ({
  material: T('材料', 'Material'),
  product: T('作品', 'Work'),
  test: T('测试', 'Test'),
  config: T('配置', 'Configuration'),
  submission: T('提交记录', 'Submission'),
  review: T('评审', 'Review'),
  role_reply: T('同事回复', 'Colleague reply'),
  event: T('历史记录', 'History'),
});
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
  const n = document.createElement(tag);
  n.textContent = text;
  n.className = className;
  return n;
};
function dialog(title: string) {
  const element = node('dialog', '', 'sheet wide');
  const head = node('header', '', 'sheet-head');
  const heading = node('h2', title);
  heading.id = 'v4-reference-title';
  element.setAttribute('aria-labelledby', heading.id);
  const close = node('button', T('关闭', 'Close'), 'btn small quiet');
  close.type = 'button';
  close.onclick = () => element.close();
  head.append(heading, close);
  const body = node('div', '', 'sheet-body');
  const foot = node('footer', '', 'sheet-foot');
  element.append(head, body, foot);
  document.body.append(element);
  element.addEventListener('close', () => element.remove(), { once: true });
  return { element, body, foot };
}
function textOf(content: Record<string, any>): string[] {
  const strings = [
    content.text,
    content.body,
    content.content,
    content.query,
    content.answer,
    content.reason,
    content.question,
    content.decision,
  ];
  if (Array.isArray(content.fragments)) strings.push(...content.fragments.map((f: any) => f.text));
  return strings.filter((v): v is string => typeof v === 'string' && v.length > 0);
}
export function installV4References(getHost: () => V4HostAdapter | null) {
  const open = async (event: Event) => {
    const detail = (event as CustomEvent).detail,
      host = getHost();
    if (!host || host.snapshot().session?.protocol !== 2) return;
    detail.handled = true;
    try {
      const ref = detail.ref as ObjectRef | EvidenceRefV2;
      if (ref.session_id !== host.snapshot().session?.sessionId)
        throw Error(T('引用不属于当前练习。', 'This reference belongs to another practice.'));
      const record: any = await host.query('objects.read', ref);
      if (
        record.ref?.object_id !== ref.object_id ||
        record.ref.version !== ref.version ||
        record.ref.session_id !== ref.session_id
      )
        throw Error(T('原始版本无法核对。', 'The original version could not be verified.'));
      if (getHost()?.snapshot().session?.sessionId !== ref.session_id)
        throw Error('Practice changed');
      const title = (names() as Record<string, string>)[ref.kind] ?? T('依据', 'Evidence');
      const side = document.querySelector<HTMLElement>('[data-v4-reference-side]');
      const overlay = side ? null : dialog(title);
      const target = side ?? overlay!.body;
      target.replaceChildren();
      target.append(node('h2', `${record.content.title ?? title} · v${ref.version}`, 'title-s'));
      if ('quote' in ref && ref.quote) target.append(node('blockquote', ref.quote, 'prose'));
      const texts = textOf(record.content ?? {});
      for (const text of texts) {
        const p = node('p', text, 'prose');
        p.style.whiteSpace = 'pre-wrap';
        target.append(p);
      }
      if (!texts.length)
        target.append(
          node(
            'p',
            T(
              '已核对此版本的记录身份，暂无可展示的正文。',
              'This version is verified; no readable body is available.',
            ),
            'meta',
          ),
        );
      overlay?.element.showModal();
      target.tabIndex = -1;
      target.focus({ preventScroll: true });
      detail.resolve();
    } catch (error) {
      detail.reject(error);
    }
  };
  const choose = async (event: Event) => {
    const detail = (event as CustomEvent).detail,
      host = getHost();
    if (!host || host.snapshot().session?.protocol !== 2) return;
    detail.handled = true;
    try {
      if (detail.sessionId !== host.snapshot().session?.sessionId) throw Error('Practice changed');
      // Only actual read receipts are offered; a material catalogue is not proof of reading.
      const refs = host.draft<EvidenceRefV2[]>('workspace', 'evidence-cache') ?? [];
      const sheet = dialog(
        T('选择已读材料的原始依据', 'Choose original evidence from documents you read'),
      );
      const chosen = new Set<number>();
      let finished = false;
      for (const [index, ref] of refs.entries()) {
        if (ref.session_id !== detail.sessionId || !ref.quote) continue;
        const row = node('label', '', 'check');
        const checkbox = node('input');
        checkbox.type = 'checkbox';
        checkbox.onchange = () => {
          if (checkbox.checked) chosen.add(index);
          else chosen.delete(index);
        };
        row.append(checkbox, node('span', `${ref.quote} · v${ref.version}`));
        sheet.body.append(row);
      }
      if (!sheet.body.children.length)
        sheet.body.append(
          node(
            'p',
            T(
              '先打开并阅读一份材料，再选择其中的依据。',
              'Read a document first, then choose its evidence.',
            ),
            'meta',
          ),
        );
      const confirm = node('button', T('使用选中的依据', 'Use selected evidence'), 'btn primary');
      confirm.type = 'button';
      confirm.onclick = () => {
        finished = true;
        detail.resolve([...chosen].map((i) => refs[i]));
        sheet.element.close();
      };
      sheet.foot.append(confirm);
      sheet.element.addEventListener(
        'close',
        () => {
          if (!finished) detail.resolve([]);
        },
        { once: true },
      );
      sheet.element.showModal();
    } catch (error) {
      detail.reject(error);
    }
  };
  window.addEventListener('v4-open-reference', open);
  window.addEventListener('v4-choose-evidence', choose);
  return () => {
    window.removeEventListener('v4-open-reference', open);
    window.removeEventListener('v4-choose-evidence', choose);
  };
}
