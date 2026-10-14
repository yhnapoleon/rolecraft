/** "Recorded business decisions" of a feedback record, one recorded line per line. The evaluator
 * chose which decisions to state and wrote them in the request panel's words; the browser shows
 * the record as written, without re-selecting or rewording decisions. */
import type { Report } from './index';
import './business-decisions.css';

export function renderDecisions(doc: Document, report: Report): HTMLElement {
  const section = doc.createElement('div');
  section.className = 'business-decisions';
  for (const line of report.business_response.split('\n')) {
    if (!line.trim()) continue;
    const item = doc.createElement('p');
    item.textContent = line;
    section.append(item);
  }
  return section;
}
