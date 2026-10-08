/** Canonical business values at the boundary of the unchanged v4 controls. */
const purposes: Record<string, string> = {
  探索笔记: 'exploration',
  测试计划: 'test_plan',
  方案比较: 'option',
  试点决定: 'commitment',
  自由作品: 'freeform',
  结果报告: 'result',
  计划: 'plan',
};
export const canonicalPurpose = (value: string) => purposes[value] ?? value;
export function taskPriority(value: string): number {
  const mapped = (
    { first: 0, next: 1, later: 2, '0': 0, '1': 1, '2': 2 } as Record<string, number>
  )[value];
  if (mapped === undefined) throw Error('invalid_task_priority');
  return mapped;
}
export function controlValue(node: HTMLElement | undefined): string | undefined {
  if (!node) return;
  if (node.tagName === 'INPUT' && (node as HTMLInputElement).type === 'radio')
    return (node as HTMLInputElement).checked ? (node as HTMLInputElement).value : undefined;
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(node.tagName))
    return (node as HTMLInputElement).value;
  return node.querySelector<HTMLInputElement>('input:checked')?.value;
}
export function writePurpose(node: HTMLElement | undefined, value: string) {
  if (!node) return;
  if (node.tagName === 'SELECT') {
    const select = node as HTMLSelectElement;
    let option = [...select.options].find(
      (o) => canonicalPurpose(o.value) === canonicalPurpose(value),
    );
    if (!option) {
      option = node.ownerDocument.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    if (select.value !== option.value) select.value = option.value;
  } else {
    const radios =
      node.tagName === 'INPUT'
        ? [node as HTMLInputElement]
        : [...node.querySelectorAll<HTMLInputElement>('input[type=radio]')];
    for (const radio of radios)
      radio.checked = canonicalPurpose(radio.value) === canonicalPurpose(value);
  }
}
export function disableControl(node: HTMLElement | undefined, disabled: boolean) {
  if (!node) return;
  if ('disabled' in node) (node as HTMLInputElement).disabled = disabled;
  node
    .querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
      'input,select,textarea',
    )
    .forEach((n) => {
      n.disabled = disabled;
    });
}
