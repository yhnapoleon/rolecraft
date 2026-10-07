"""English-only display messages, excluded from the Chinese runtime dependency set."""
MESSAGES_EN = {'synthetic': 'This company and its business information are fictional training material.',
 'missing_cases': 'These trial records have not been released as learner material.',
 'cases_title': 'Preparation-stage assistant trial records',
 'case_details_title': 'Trial settings and complete answers',
 'policy_notice': 'Expense Management has published a hotel-policy notice. The new document is in the workspace.',
 'demo_notice': 'The manager has moved the internal demonstration to day 4. See the updated demonstration '
                'arrangements.',
 'scope_notice': 'Chen Min has forwarded a request from Sales Support. See the new scope-discussion record.',
 'stale_warning': 'The index is behind the source version. Verify the current policy before relying on the '
                  'following passage.\n',
 'prohibited_topic': 'This topic cannot be answered automatically. Check with an authorized owner.',
 'outside_scope': 'This question is outside the currently enabled knowledge scope. Ask an authorized person to '
                  'review it.',
 'no_retrieval_hit': 'No sufficiently supported passage was retrieved. Please ask a person to check.',
 'manual_verification_required': 'This knowledge domain requires human verification; no automatic answer was '
                                 'given.',
 'stale_source_guard': 'The source and index versions differ. The freshness guard prevented an automatic answer.',
 'no_fallback': 'An automatic answer is not sufficiently supported, and human fallback is not provisioned.',
 'tech_summary': 'A preparation-stage diagnostic compared this question: I signed up for company training; does '
                 'that mean I can go to the class? It used thresholds 0.35 and 0.2 against the same FAQ and an '
                 'unrelated control. The actual paired results are retained in the diagnostic record. This is a '
                 'local comparison, not a universally correct setting.',
 'tech_register_summary': 'The technical diagnostic retains the original training question, two thresholds and an '
                          'unrelated control. Its internal register ID is not for disclosure.',
 'path_question': 'What is the hotel reimbursement limit per night?',
 'path_reason': 'Request based on the candidate material and the proposed work items.'}
