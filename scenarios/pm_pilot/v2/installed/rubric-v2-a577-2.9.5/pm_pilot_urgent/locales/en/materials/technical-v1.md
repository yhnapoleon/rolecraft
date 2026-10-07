# Technical handover: capabilities and configuration

This company and its business information are fictional training material.

Maintained by: the technical lead. The current assistant retrieves passages and keeps the document and version used in each answer. Configurable options include knowledge domains, retrieval count, chunk length, matching threshold, freshness handling and human fallback.

The default index is updated daily. A source document can be ahead of the index by up to 24 hours.

Work-item budgets: scope filtering takes 1 developer-day; a human-fallback entry point takes 1 developer-day; real-time synchronization takes 5 developer-days, including synchronization and knowledge-domain configuration. Human fallback is a separate item.

Costs add across selected work items. Scope filtering, human fallback and real-time synchronization only become effective when their work items and approved budget are sufficient. Configuration records retain the requested settings, effective settings and reasons for anything that did not take effect.

Refresh index reads the sources published at that moment. Real-time synchronization retrieves the current source version. Manual policy verification sends dynamic-policy questions to a person. Each choice can be saved in a configuration version.

Retrieval ranks the coverage of query terms in each passage. The matching threshold is 0.3; passages below it are excluded. This setting has limited development-query evidence, not universal calibration. Freshness handling can leave the answer unchanged, warn, or fall back to a person.

The technical lead says: "I need the original wording and configuration snapshot to reproduce a problem. Keep the actual answer, citation and status code. Bring the record when we discuss retrieval issues."

Execution boundary: the assistant cannot reset an account, file an expense claim or approve a resource request. A handoff suggestion does not automatically create a human-service ticket.
