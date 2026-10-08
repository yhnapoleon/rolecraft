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
 'tech_summary': "A preparation-stage test reproduced this question: I've already signed up for company training. "
                 'Does that mean I can simply turn up to attend the class? At thresholds 0.35 and the current '
                 'default 0.3 it retrieved no supported passage. At 0.2 it returned Device repair, which does '
                 'not answer the training question. Lowering the threshold did not solve this case. An unrelated '
                 'control still retrieved nothing. This is an observed English diagnostic, not a recommended threshold.',
 'tech_register_summary': 'The technical diagnostic retains the original training question, three thresholds and an '
                          'unrelated control. Its internal register ID is not for disclosure.',
 'path_question': 'What is the hotel reimbursement limit per night?',
 'path_reason': 'Request based on the candidate material and the proposed work items.'}
