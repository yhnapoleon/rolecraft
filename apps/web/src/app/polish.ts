/** 237 opt-in visual comparison. No business state, persistence or selector changes. */
import './polish.css';
import { onLocaleChange, T } from './i18n';
if (
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('polish') === '1'
) {
  document.documentElement.dataset.polish = '1';
  const mount = () => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'hx-polish-control';
    const label = () => {
      const on = document.documentElement.dataset.polish === '1';
      button.textContent = T(
        `局内精修：${on ? '开' : '关'}`,
        `Workspace polish: ${on ? 'on' : 'off'}`,
      );
      button.setAttribute('aria-pressed', String(on));
      button.title = T('原位对比，不改变工作记录', 'Compare in place without changing your work');
    };
    button.addEventListener('click', () => {
      document.documentElement.dataset.polish =
        document.documentElement.dataset.polish === '1' ? '0' : '1';
      label();
    });
    onLocaleChange(label);
    label();
    document.body.append(button);
  };
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  else mount();
}
