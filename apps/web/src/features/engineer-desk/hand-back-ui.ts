/** Opens the engineering review on the product manager's side (S9): reads the review, the change
 * the engineer signed and the pilot as it is now, and draws HandBackSheet in its own island. On
 * "update", a delivered practice opens a revision first, then configuration.apply sends only the
 * settings that differ; the workspace is read again so the board shows the new configuration at
 * once. A pilot changed meanwhile (409) is read again before confirming. Loaded on first use. */
import { T } from '../../app/i18n';
import type { GatewayTransport } from '../../gateway-transport';
import { mountIsland } from '../../islands/mount';
import { runAction, signalsChanged, toast } from '../../shell';
import { engineerApi, failureText } from './api';
import {
  applyFailure,
  handBackChanges,
  handBackCommand,
  outcomeCaution,
  outcomeClean,
  outcomeSentence,
  reviewResult,
  reviewDetails,
  revisionReason,
} from './hand-back';
import { type ColleagueRun, colleagueRun, HandBackSheet, type HandBackView } from './hand-back-sheet';
import { fieldName, valueText } from './copy';

import { engineerLocal, recordHandBack } from './local-state';
import { clock, settingsDiff, type Change } from './model';

/** The configuration change, for the board and anyone else listening on the page. */
export interface PilotConfigApplied {
  readonly sessionId: string;
  readonly fromVersion: number | null;
  readonly toVersion: number;
  readonly reviewId: string;
  readonly changes: Record<string, unknown>;
  readonly origin: 'engineer-review';
}

let island: { update(v: HandBackView): void; destroy(): void } | null = null;
let host: HTMLElement | null = null;

export function openHandBackSheet(options: {
  transport: GatewayTransport;
  sessionId: string;
  reviewId: string;
  /** Read the practice's workspace again (the board's configuration version follows). */
  reread?: () => Promise<unknown>;
}) {
  const api = engineerApi(options.transport, options.sessionId);
  let view: HandBackView;
  // biome-ignore lint/suspicious/noExplicitAny: the pilot configuration as the server sends it
  let pilot: any = null;
  let changes: Record<string, Change> = {};
  // Daniel's ticket (a product manager's practice): decisions are recorded on it.
  let colleagueTicket: string | null = null;
  const set = (patch: Partial<HandBackView>) => {
    view = { ...view, ...patch };
    island?.update(view);
  };
  const close = () => {
    set({ open: false, confirm: false });
    setTimeout(() => {
      island?.destroy();
      island = null;
      host?.remove();
      host = null;
    }, 320);
  };
  async function load() {
    set({ loading: true, error: '' });
    try {
      const record = await api.review(options.reviewId);
      const ticket = await api.ticket(record.ticket_id);
      const draft = ticket.latest_draft?.id === record.draft_id ? ticket.latest_draft : null;
      changes = (draft?.changes ?? {}) as Record<string, Change>;
      pilot = await api.pilotConfig();
      const status = await api.status();
      colleagueTicket = ticket.assignee === 'colleague' ? ticket.id : null;
      const h = ticket.handover;
      const said = (c: Record<string, { before: unknown; after: unknown }>) =>
        Object.entries(c)
          .map(([k, v]) => `${fieldName(k)} ${valueText(k, v.before)} → ${valueText(k, v.after)}`)
          .join('；');
      const colleague: ColleagueRun | null =
        colleagueTicket && h ? colleagueRun(h, ticket.review_budget, said) : null;
      const last = [...(h?.decisions ?? [])].reverse().find((d) => typeof d.decision === 'string');
      const results = record.report.public_results;
      const hidden = record.report.hidden;
      const comparison = record.report.hidden_comparison;
      // The same reading as the report's headline and the board's signal.
      const result = reviewResult(record, T('zh', 'en') as 'zh' | 'en');
      const agent = record.draft_executor?.kind;
      set({
        loading: false,
        signedAt: clock(record.signed_at),
        fromAgent: agent === 'external_agent' || agent === 'reference_agent',
        clean: outcomeClean(result),
        title: outcomeSentence(result),
        caution: outcomeCaution(result),
        details: reviewDetails(record, T('zh', 'en') as 'zh' | 'en'),
        newFailures: result.newFailures,
        fixed: comparison?.fixed ?? 0,
        publicPassed: results.filter((r) => r.result === 'pass').length,
        publicTotal: results.length,
        hidden: hidden.passed + hidden.failed + hidden.errors,
        diff: settingsDiff(ticket.baseline_config, changes, ticket.editable_fields),
        rows: pilot ? handBackChanges(changes, pilot) : [],
        fromVersion: pilot?.config_version ?? null,
        submitted: status === 'submitted',
        appliedVersion:
          engineerLocal(options.sessionId).handedBack?.[options.reviewId]?.appliedVersion ?? null,
        colleague,
        decided: String(last?.decision ?? ''),
      });
    } catch (error) {
      set({ loading: false, error: failureText(error) });
    }
  }
  /** A pilot changed meanwhile: read it again and list what still differs, then confirm again. */
  async function reread() {
    set({ reloading: true, applyError: '' });
    try {
      pilot = await api.pilotConfig();
      set({
        reloading: false,
        conflict: false,
        rows: pilot ? handBackChanges(changes, pilot) : [],
        fromVersion: pilot?.config_version ?? null,
        submitted: (await api.status()) === 'submitted',
      });
    } catch (error) {
      set({ reloading: false, applyError: failureText(error) });
    }
  }
  async function apply() {
    if (!pilot || !view.rows?.length) return;
    set({ applying: true, applyError: '', conflict: false });
    try {
      if ((await api.status()) === 'submitted') {
        const parent = await api.latestSubmission();
        if (parent) {
          const reason = revisionReason();
          await api.beginRevision(parent, reason);
          // The board's revision guide, as after "Start a revision" on the result page.
          document.dispatchEvent(
            new CustomEvent('rolecraft:revision-started', {
              bubbles: true,
              detail: { delivery: null, unmet: [], products: [], reason },
            }),
          );
        }
      }
      const fromVersion = view.fromVersion;
      const sent = handBackCommand(pilot, view.rows);
      const result = await api.applyConfig(sent);
      const version = result.config.config_version ?? (fromVersion ?? 1) + 1;
      // Daniel's report: the person's own apply is recorded on his ticket, checked on the server
      // against the report's change (a configuration that does not carry it is refused).
      if (colleagueTicket) {
        const recorded = await api.decide(colleagueTicket, 'apply', { config_version: version });
        if (recorded.decision.result === 'applied_with_changes')
          toast(
            T(
              '已记下：按报告应用，另外还改了其他设置。',
              'Recorded: applied from the report, with other settings changed too.',
            ),
          );
      }
      const back = engineerLocal(options.sessionId).handedBack?.[options.reviewId];
      if (back)
        recordHandBack(options.sessionId, options.reviewId, { ...back, appliedVersion: version });
      signalsChanged();
      set({ applying: false, confirm: false, appliedVersion: version, submitted: false });
      toast(T(`试点已更新为配置 v${version}`, `The pilot is now on configuration v${version}`));
      const detail: PilotConfigApplied = {
        sessionId: options.sessionId,
        fromVersion,
        toVersion: version,
        reviewId: options.reviewId,
        changes: { ...sent.settings },
        origin: 'engineer-review',
      };
      document.dispatchEvent(new CustomEvent('rolecraft:pilot-config-applied', { detail }));
      // configuration.apply and begin_revision went around the board's store: read it again so
      // the board's "Config" reads the new version without a reload.
      void options.reread?.().catch(() => {});
    } catch (error) {
      const failure = applyFailure(error);
      set({ applying: false, applyError: failure.text, conflict: failure.conflict });
    }
  }
  view = {
    open: true,
    loading: true,
    error: '',
    signedAt: '',
    fromAgent: false,
    clean: true,
    title: '',
    caution: '',
    details: [],
    newFailures: 0,
    fixed: 0,
    publicPassed: 0,
    publicTotal: 0,
    hidden: 0,
    diff: [],
    rows: null,
    fromVersion: null,
    submitted: false,
    confirm: false,
    applying: false,
    applyError: '',
    conflict: false,
    reloading: false,
    appliedVersion: null,
    colleague: null,
    decided: '',
    onAsk: () => {
      close();
      // The rail's conversation with Daniel, as the people list opens it.
      void runAction('chat', undefined, { role: 'technical' });
    },
    onReturn: () => {
      if (!colleagueTicket) return;
      void api
        .decide(colleagueTicket, 'return', {
          note: T('先不采用这份改动', 'Not taking this change for now'),
        })
        .then(() => {
          set({ decided: 'return' });
          toast(T('已退回给 Daniel', 'Returned to Daniel'));
        })
        .catch((error) => set({ applyError: failureText(error) }));
    },
    onRerun: () => {
      close();
      void runAction('open-bench');
    },
    onOpenChange: (open) => (open ? set({ open }) : close()),
    onConfirmChange: (confirm) => set({ confirm, applyError: '' }),
    onApply: () => void apply(),
    onReload: () => void reread(),
    onRetry: () => void load(),
  };
  island?.destroy();
  host?.remove();
  host = document.createElement('div');
  host.className = 'ed-handback-host';
  document.body.appendChild(host);
  island = mountIsland(host, HandBackSheet, view);
  void load();
}
