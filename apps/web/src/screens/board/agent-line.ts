import { T } from '../../app/i18n';
import { agentStatus } from '../../features/engineer-desk/agent-activity/status';
import type { AgentConnection, AgentEvent } from '../../shell/agent-bus';

type Activity = { exports?: unknown[]; artifacts: { removedAt?: unknown; source?: string }[] };
export function agentLine(
  a: Activity,
  hat: 'pm' | 'engineer',
  connection: AgentConnection,
  events: readonly AgentEvent[],
): string {
  // Read the same recorded feed as the compact stream, including its initial history.
  // Do not count calls as products: retries and reads are not additional hand-backs.
  if (hat === 'engineer') {
    const labels: Record<string, [string, string]> = {
      'engineer.reproduce': ['已交回复现结果', 'Reproduction returned'],
      'engineer.trial': ['已交回试跑结果', 'Trial returned'],
      'engineer.code.run': ['已交回代码运行结果', 'Code run returned'],
      'engineer.submissions.draft': ['已起草签字单', 'Drafted a sign-off'],
    };
    const latest = [...events]
      .reverse()
      .find((event) => event.status === 'ok' && labels[event.tool]);
    if (latest) return T(...labels[latest.tool]);
    return agentStatus(connection).text;
  }
  const exp = (a.exports || []).length;
  const back = a.artifacts.filter((x) => !x.removedAt && x.source !== 'user').length;
  if (!exp && !back) return T('还没交出任务', 'Nothing handed over yet');
  return T(`交出 ${exp} 次，带回 ${back} 份`, `${exp} handed over, ${back} returned`);
}
