# Engineer review contract

The additive `engineer-review-v1` file protocol releases the submission/review interface for W13 M1. It does not install submit/review execution or a new HTTP endpoint. The existing three legacy objects and `expansion-v3` freeze remain unchanged. New producers import `career_lab.contracts.v2.engineer`; the legacy `career_lab.contracts.v2` namespace retains its original models and defaults.

Generate the immutable schema, examples, OpenAPI components and TypeScript with:

```sh
python -m career_lab.contracts.v2.engineer_export --output <new-directory>
```

The checked-in candidate is [engineer-review-v1/manifest.json](engineer-review-v1/manifest.json). Repeating export to the same directory succeeds only if every byte matches. The manifest binds schemas, examples, TypeScript, OpenAPI, protocol implementation files and the previous frozen manifest. All examples are synthetic interface fixtures.

## New and old records

`decode_engineer_document(kind, raw)` accepts `EngineerPack`, `EngineerSubmission`, or `RegressionReport`. Without `contract_version`, it uses the unchanged legacy class. With `contract_version="engineer-review-v1"`, submissions use `EngineerSubmissionRecord` and reports use `EngineerRegressionReport`. Unknown/null versions fail closed; the pack remains in its original format. The enclosing engineer pack index's format 1/2 remains the responsibility of the existing pack reader.

| Need | Frozen field or consumer rule |
|---|---|
| Pack identity | `submission.pack` is the exact pack.json file reference. Existing `EngineerPack.id` identifies the captured data (`engineer-<digest>`); it is not pack.json's byte hash. Preserve both without renaming either. |
| Baseline configuration | `base_config_hash` is the SHA256 of the exact config file referenced by the trusted pack index. `validate_submission_files` compares it to the caller's trusted `baseline` reference, parses `AssistantConfig`, and checks the original pack's config object identity. |
| Candidate | `config` is a portable, hash-checked file reference. Candidate parses as `AssistantConfig` and belongs to the original config/session. The W02 policy/effective_config consumer must additionally validate scenario domain, resource and allowed configuration changes. |
| Declared results | Required `regression_report` is either an exact file reference to `EngineerClaimedReport`, or explicit null meaning no self-reported results. Claims contain unique probe IDs and pass/fail/error. The claim file must bind the same pack and candidate. |
| Unresolved items and time | Required `unresolved` contains typed items; empty means none declared. `created_at` requires a timezone. Restoring the same submission retains the original timestamp. Missing fields and null lists are rejected. |
| Review identity | `EngineerReviewInput` binds submission, pack, baseline/candidate, scenario, full probe-suite, reviewer implementation/version, resource snapshot, source version point, resolved requested/effective config, language and explicit model reference/null. Its canonical `digest()` is `input_hash`; typed defaults are materialized before hashing. |
| Coverage | `probe_ids` is the complete ordered suite membership selected by the trusted reviewer. Every probe must have exactly one result, including errors. Submitters cannot choose the authoritative suite or expectations. |
| Per-probe result | `EngineerProbeResult` preserves query, typed expectation, actual `TestResultV2` (including sources, indexed/used versions, requested/effective config, executor and usage), effective config digest, pass/fail/error, elapsed seconds and execution error code. Actual as_of must equal the fixed source/resource point; executed_at remains the distinct real execution timestamp. |
| Report verification | `verified` means reproduction and claim comparison completed, including legitimate business probe failures. `report_mismatch` means the completed actual run disagrees with the declaration; `incomplete` means probe execution errored or claim checking remains unverified. It is not a pass grade. |
| Rule feedback | Typed findings distinguish target repair, new regression, claim consistency and unresolved issues. Findings identify probes and visibility. No capability total score is introduced. |
| Semantic advice | Explicit model/version reference, original text and status; without a model use `waiting_model` with null text. Advice is always `affects_score=false`. Work language is fixed in the review input, never inferred by translating historical text. |
| Public report | `public_engineer_report()` returns only public probes/findings/unresolved items and explicitly public advice. Hidden probes contribute pass/fail/error counts only. A typed applicability summary preserves the scenario/candidate references, baseline/suite/reviewer/effective-config hashes and source point even for an entirely hidden suite. Full input/resource snapshots and hidden probe identities, queries, expectations and actuals stay in the trusted report. |

The public projection is a trusted reviewer output. The producer must classify authored findings/advice correctly and sanitize their text against authorized sources before publication. The projection cannot infer the confidentiality of arbitrary prose. A learner-supplied visibility flag is never publication authorization.

## W13 execution obligations

The shared decoder and byte checks do not authenticate a caller, authorize a file, execute a candidate, or prove a result truthful. W13 must obtain the trusted pack references from an authorized original capture; recheck the session/executor on every attempt; apply existing W02 policies; execute the full frozen suite against the candidate's actual effective configuration and source/resource point; and preserve both the submitted claim file and the actual report. Hash-correct attacker files alone establish no authority.

Persist submission ID and canonical payload together atomically. Same ID/same payload reads the original result and timestamp; different payload returns a stable conflict. Bind the review ID to the complete normalized `EngineerReviewInput`; replay reads the existing report without probe/model calls. An interrupted run stays incomplete until a separately authorized attempt. W13 M1 owns this persistence and execution, including process/model faults, permission checks, and bilingual CLI acceptance. M2 owns AIPM reference/adoption, never automatic configuration application or approval.

## Shared installation points

| Consumer | Existing formal seam | Runtime contract |
|---|---|---|
| Scenario/extensions | `ExtensionRegistry.register(Operation)` | Static public operation whitelist; request model is a V2 contract; mutations return `Mutation` through `Gateway` and `V2Store.execute`. A ready operation requires a callable handler. |
| Object/reference extensions | `register_object_model`, `register_reference_resolver` | Registered before Gateway creation; versioned object and current scope checks remain in the transaction core. |
| Standard review | `install_lifecycle(..., feedback_handler=...)`, `register_job("v2.feedback", StoreJobHandler(..., retry_on_error=False))` | `/reviews` → fixed job → `/feedback/{review_id}` and `/requests/{request_id}` recovery. Missing feedback handler leaves feedback.create unavailable. |
| Model consumer | Existing `build_registry(..., feedback_handler=...)` injection | W08 adapter must compose with the evidence/feedback owner; preserve rules, fixed input and durable single-attempt receipts. This slice does not inject a trained model or change evaluation semantics. |
| Module readiness | `ExtensionRegistry.availability(name)` and `/workbench` `available`/`semantic` | Readiness reflects installed registration; absence is 503 `module_unavailable`. `waiting_model` remains explicit. |
| Product interaction | Existing `Command`, `RequestResult`, `ReviewInput`, `FeedbackV2`; standard v4 host | Normal HTTP review tested in both languages; host/region completion is still gated by the frontend quality work. |
| W13 M1 / AIPM report consumer | New Python contracts and generated `types.ts` | Consume the manifest's exact revision. Engineer runtime and public report mounting remain follow-on work. |

No new frontend host, command registry, catalog pointer, scenario package, credential derivation, or protected backend file is changed by this contract slice. Existing transaction, private-draft, closed-cycle, feedback immutability and content/evaluation/code identity regressions remain the acceptance gates.
