/** Read-only regression report for the engineer role (EngineerPublicReport, engineer-review-v1).
 * engineerReportView is pure; renderEngineerReport draws it; mountEngineerReport does both. */
import { engineerReportView, type EngineerReportOptions } from './view';
import { renderEngineerReport, type EngineerReportRenderOptions } from './render';
import type { EngineerPublicReport } from './types';

export * from './types';
export {
  engineerReportView,
  ruleFindingText,
  type EngineerBasisRow,
  type EngineerCheckView,
  type EngineerCountView,
  type EngineerEvaluationRowView,
  type EngineerProbeRowView,
  type EngineerReportOptions,
  type EngineerReportView,
  type EngineerTagView,
  type EngineerTone,
} from './view';
export { renderEngineerReport, type EngineerReportRenderOptions } from './render';
export { ENGINEER_REPORT_COPY, MATERIAL_NAMES, type EngineerReportKey } from './copy';

/** Replace root's content with the report; returns the drawn sheet. */
export function mountEngineerReport(
  root: HTMLElement,
  report: EngineerPublicReport,
  options: EngineerReportOptions & EngineerReportRenderOptions,
): HTMLElement {
  const sheet = renderEngineerReport(
    root.ownerDocument,
    engineerReportView(report, options),
    options,
  );
  root.replaceChildren(sheet);
  return sheet;
}
