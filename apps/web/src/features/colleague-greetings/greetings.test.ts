import { expect, it, vi } from 'vitest';
import { askGreeting, introductionHtml } from './index';
it('labels the opening as preset content instead of a generated reply', () => {
  const html = introductionHtml('session', 'pm', 'manager', 'en', true);
  expect(html).toContain('preset scene content');
  expect(html).toContain('data-action="greet-ask"');
  expect(html).not.toContain('rc-msg--them');
  expect(html).not.toContain('typing');
});
it('sends the chosen question only once while another click is pending', async () => {
  let resolve: (ok: boolean) => void = () => {};
  const send = vi.fn(
    (_question: string) =>
      new Promise<boolean>((r) => {
        resolve = r;
      }),
  );
  const first = askGreeting('test', 'pm', 'manager', 0, 'en', send);
  await askGreeting('test', 'pm', 'manager', 0, 'en', send);
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0]?.[0]).toContain('establish first');
  resolve(false);
  await first;
  await askGreeting('test', 'pm', 'manager', 99, 'en', send);
  expect(send).toHaveBeenCalledTimes(1);
});
