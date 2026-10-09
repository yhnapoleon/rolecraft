"""Append-only publication history for the expansion contract.

Append a record to MANIFEST_HISTORY; never edit existing historical events.
Records apply in tuple order: mappings merge in insertion order, while scalars
and lists replace prior values. integration_changes describes integration work;
review_fixes records corrections. Use new keys and accurate text. A new event
may explicitly supersede an old value without erasing the original record.
previous_contract_revision names the published input revision; input_contract_revision
names the actual input label. Repeated previous revisions retain the original chain.

Only manually maintained publication fields belong here. source_files, documents,
errors, schemas/examples, OpenAPI and registry mappings are calculated by export.py.
Source fingerprints use the selected root's current implementation files; document
fingerprints use root/docs/contracts/expansion-v3, even for an empty output directory.
Public error codes come from the original source scan, committed error history and
required runtime codes; export.py explicitly excludes internal export invariants.
Do not add a parallel static error catalog to this history.

Export keeps the existing without_provenance policy active for schemas and OpenAPI.
Publishing provenance later requires an explicit compatibility-policy change and a
new freeze; adding its fields alone does not publish them in this contract.

Generate into an empty temporary directory on the task branch, compare deterministic
output and complete manual history, and run all export callers plus frozen-byte tests.
Only update the committed freeze when authorized. The coordinator appends integrated
records, links the preceding published revision and regenerates after combining all
branches. Current source changes may produce a new revision; never hand-edit generated
JSON or historical hashes. Full code identity is also recorded in delivery receipts.
"""

from pydantic import JsonValue

MANIFEST_HISTORY: tuple[dict[str, JsonValue], ...] = (
    {
        "schema_version": 1,
        "status": "frozen_candidate_pending_independent_review",
        "owner": "rolecraft-032-foundation",
        "base_commit": "80cf1f6189cd25610d609f44283ff9668582d759",
        "input_contract_revision": "preflight",
        "v1_dirty_included": False,
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
        ],
        "previous_draft": "draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e",
        "changes_since_draft": [
            "Command.schema_version and CreateSessionV2.schema_version are now "
            "required for explicit envelopes.",
            "Added ModelPrediction; ModelBundle validates ordered task label vocabulary.",
            "G2v compares evidence sets independent of ordering, requires "
            "reordered evidence only when more than one item exists.",
            "API/storage/atomic job queue/isolated restore implementations and "
            "their public models are now included.",
            "AssistantConfig adds finite min_score (initial 0.35, uncalibrated), "
            "freshness_guard none/warn/fallback and manual_domains; TestResultV2 "
            "requires execution metadata and exact config_ref.",
            "BusinessRequest requires immutable proposed/applied BusinessBasis. "
            "ScenarioStateV2 is private transaction state, not an observation.",
            "Observation.visible_sources now requires ObservedFragment with "
            "explicit learner acquisition/audience; catalog is separate. "
            "StepResult/ObservedStep bind actual request identities, points and "
            "executor.",
            "AnnotationPass successful passes require actual invocation "
            "identity; G2v also requires separate context IDs, independence "
            "method/reason and truthful evidence order policy.",
            "AuthContext/DelegationGrant adds explicit create_under_tasks; "
            "derived results remain tied to the actual executor, unrelated "
            "existing artifacts are not inherited.",
            "SnapshotExport now includes immutable external source references; "
            "restore supports exact target/idempotency and structured action "
            "remapping. Regenerate draft snapshots under the new revision.",
            "WorkProduct/import DTOs retain intent/refs, test_compare, "
            "review_focus distinct from direction, source return identity, "
            "adoption and version conflicts.",
            "PublicTransactionResult is the HTTP/worker wire result; "
            "TransactionResult remains the internal authoritative record.",
        ],
    },
    {
        "previous_contract_revision": (
            "expansion-v3-5a117a51493f5bb5d8f96f711d78466f82550935d803c312d277cfac045ff6a4"
        )
    },
    {
        "review_fixes": {
            "R01": "Actual WorkerClaim is passed and fenced at entry/commit; no lease borrowing.",
            "R02": "Fixed-subject derived FeedbackV2 may persist on submitted; ordinary "
            "writes stay forbidden.",
            "R03": "Model-directed remapping leaves arbitrary text and legacy "
            "provenance unchanged.",
            "R04": "Kind/namespace ID keys distinguish local and external objects; "
            "mapped graph is validated.",
            "R05": "PublicDisclosureRecord strips/rejects raw source quote/span and "
            "checks scope/time.",
            "R06": "Restore replay token must match a real usable saved owner credential.",
            "R07": "Built-in authenticated read-only request_id query returns real "
            "request/job/effect links.",
            "R08": "Received provider body/usage preserved independently of "
            "invalid/missing actual identity.",
            "R09": "Accepted single-pass G2 final equals that actual successful decision.",
        }
    },
    {
        "review_fixes": {
            "C-W01-01": "Snapshot-bound asynchronous inputs; declared head/state "
            "freshness, actual claim and current authorization checked "
            "atomically. needs_context parks once; explicit idempotent "
            "refresh preserves original subject/command and immutable "
            "context history.",
            "C-W01-02": "RoleContext reads reject non-research learner and historical "
            "reserved role IDs; only a trusted matching role reader or "
            "internal research capability can read. Reserved role "
            "credentials cannot be minted. New writes remain private.",
            "C-W01-03": "Withdrawn route-deleting candidate is not included. Public "
            "integration must use Gateway slots; W03 adapter remains "
            "separate integration work.",
            "P2-related": "Stable worker error codes; scoped v2 jobs GET; reverse-order "
            "object/resolver collision rejected.",
        }
    },
    {
        "review_fixes": {
            "C-W01-04": "Ordinary jobs require an active open current cycle before "
            "handler and at commit. Explicit refresh preserves "
            "question/command while moving context to the current cycle; "
            "fixed-subject feedback remains allowed. Deterministic failures "
            "stop; parked reason/history is queryable; research writes "
            "denied."
        }
    },
    {"publication_package": "W14"},
    {"input_contract_revision": "draft-core-wiring-r6-20261007"},
    {
        "previous_contract_revision": (
            "expansion-v3-2e4b5f05138ae995320db1ae21ca6f5d7a8d63bf5ec3e19346a088510cb0515c"
        )
    },
    {
        "integration_changes": {
            "W02-S06": "Opt-in contextual resolver gets authoritative "
            "persisted-window ScenarioState; legacy four-argument "
            "behavior retained.",
            "W02-S07": "Verified command/result references are atomically "
            "anchored for read-request recovery.",
            "W03-GR02-partial": "Validated LegacyProvenance.raw remains inert "
            "during reference/time traversal; receipt and "
            "preview interfaces remain pending.",
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 runtime is still pinned to r3; controlled source-port regressions do not "
            "close actual ScenarioModule HTTP acceptance. Consumers must migrate through "
            "coordinator-fixed inputs.",
        ]
    },
    {
        "review_fixes": {
            "031-W01-REPLAY-SCOPE-01": "execute, replay and request/job GET share "
            "current scope and visibility checks, including "
            "historical result-only/unanchored references; "
            "no handler/resolver rerun."
        }
    },
    {
        "review_fixes": {
            "W02-S09": "Recovery and idempotent replay select event projector only by "
            "persisted action and trusted installed registration; preserve "
            "safe fields without handler/resolver rerun."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-d5aa8ca0d6532afe1165511e1403455cde39026f7d555decdd1840038849e0bb"
        )
    },
    {
        "integration_changes": {
            "W07-W08-data-slice": "Explicit fixture bucket; separate metadata "
            "projection with "
            "language/provenance/lineage/snapshot "
            "identities; paired pending/accepted tier "
            "checks and historical-evidence-time-v1 "
            "validation."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-722c39cc0906f1b1a8e741ad234321491ee85198e6714b5a52d99e1e9262dd37"
        )
    },
    {
        "integration_changes": {
            "W07-W08-empty-joint-target": "Accepted evaluable conclusions "
            "require every acceptable evidence set "
            "nonempty unless label is INSUFFICIENT "
            "or NOT_APPLICABLE; non-evaluable "
            "cases remain valid without "
            "evidence."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-81f4855d5cdf8c601c6b09d7b350b11dcda5ed156e2d801d8e542fa197718c85"
        )
    },
    {
        "integration_changes": {
            "W07-W08-semantic-consensus": "Only independent-pass consensus uses "
            "semantic_decision_key; G2/G2v final "
            "remains bound by the full normalized "
            "decision_key to the actual selected "
            "pass."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-deb8023ca664946f45c52692c65e3524703d77194c5100e0ee42939ae26cff4b"
        )
    },
    {
        "integration_changes": {
            "W04-S02-P0": "Legacy role_reply audit fields are denied to "
            "learner/Agent on common reads and replay; new public "
            "spoken evidence remains readable; research audit "
            "preserves history. No role generation activation is "
            "implied."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-3f2ca36e4275f2ff8d8e074e91231509116c054df8750d157682e8486354a9de"
        )
    },
    {
        "integration_changes": {
            "W03-common-import-sharing": "Read-only import preview and atomic "
            "receipt; operation-local reference "
            "checks; exact-version share pages; "
            "trusted removal cascade without scope "
            "expansion; queued share reads "
            "rechecked."
        }
    },
    {
        "integration_changes": {
            "W02-projector-registration": "Conflicting declared public "
            "action/projector registrations are "
            "rejected before installation."
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
        ]
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 owned b821 remains exact c2; coordinator rebind required for cumulative "
            "business runtime. W03 owner must adopt removal_cascade port for restricted "
            "removals; role private generation and native UI remain pending.",
        ]
    },
    {
        "previous_contract_revision": (
            "expansion-v3-0aa98d5ebec838fd0e2b56a9eed2f32a51c6ec94dff526712083a589d858e510"
        )
    },
    {
        "integration_changes": {
            "W05-factual-persistence": "Optional typed factual/history/rule "
            "sections persist in FeedbackV2; legacy "
            "absent means not recorded. Exact "
            "feedback follow-ups append immutable "
            "objects without changing "
            "submitted/paused business state; new "
            "reviews link prior responses and "
            "explicit decisions."
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 owned b821 remains exact c2; coordinator rebind required for cumulative "
            "business runtime. W03 owner must adopt removal_cascade port for restricted "
            "removals; role private generation and native UI remain pending.",
            "W05 evaluator-to-trusted-source adapter and native feedback UI remain "
            "pending. Controlled persistence tests do not prove actual production history "
            "or model quality.",
        ]
    },
    {
        "previous_contract_revision": (
            "expansion-v3-d6277a2b850369a86d4f1c169464ea521587066071d899fd2d43326d178bd076"
        )
    },
    {
        "integration_changes": {
            "W04-fixed-role-read": "Private audit DTOs and exact recorded "
            "job-window role projection; receipt/source "
            "history checked; ordinary view has no "
            "authority; private generation "
            "sink/activation still unavailable."
        }
    },
    {
        "integration_changes": {
            "W05-W03-remapping": "FeedbackResponseCreate.feedback_id and "
            "ResourcePage feedback/response/import "
            "identities remap by declared kind, leaving "
            "text and historical opaque provenance "
            "unchanged."
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 owned b821 remains exact c2; coordinator rebind required for cumulative "
            "business runtime. W03 owner must adopt removal_cascade port for restricted "
            "removals; role private generation and native UI remain pending.",
            "W05 evaluator-to-trusted-source adapter and native feedback UI remain "
            "pending. Controlled persistence tests do not prove actual production history "
            "or model quality.",
            "Role snapshot tests use controlled catalogs/audits. No production private "
            "writer, failure-attempt sink, event-reference persistence or full role "
            "generation is claimed.",
        ]
    },
    {
        "previous_contract_revision": (
            "expansion-v3-d6277a2b850369a86d4f1c169464ea521587066071d899fd2d43326d178bd076"
        )
    },
    {
        "integration_changes": {
            "031-C8-01": "Store read/query/view/job-view and cached "
            "request/replay share feedback subject authorization "
            "and transient support projection; hidden "
            "quote/title/ID/derived prose removed; original records "
            "unchanged."
        }
    },
    {
        "integration_changes": {
            "original-source-protection": "test_freeze enumerates only BASE "
            "existing scenarios; no v2 baseline "
            "rewrite and no test exclusion "
            "needed."
        }
    },
    {
        "integration_changes": {
            "W03-product-cycle-replay": "Only an exact saved authorized product "
            "DTO cycle field is structural metadata. "
            "Explicit cycle sources, direct cycle "
            "objects and unproven DTOs retain scope "
            "checks; no scope grant is widened."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-5edc886f3e862b53b11c19dbcf9955042d02c7ff18dd4ecf51fee8bb3d7c108c"
        )
    },
    {
        "previous_contract_revision": (
            "expansion-v3-3d096f2715f31fc99d48862be10e9f78e414199d241f12f6dbf84d8443038d49"
        )
    },
    {
        "integration_changes": {
            "W04-private-writer": "Actual worker-bound private port, atomic "
            "public reply/private audit, fenced internal "
            "attempt journal, original Agent attribution "
            "without scope expansion; factory stays closed "
            "by default pending repaired W04 input."
        }
    },
    {
        "integration_changes": {
            "W04-private-reply-whitelist": "Public/historical RoleReply fields "
            "are restricted to the pinned public "
            "DTO regardless of permissive "
            "registrations; private carrier and "
            "unknown fields remain unreadable to "
            "learner/Agent."
        }
    },
    {
        "integration_changes": {
            "role-event-references": "Actual event provenance is "
            "scope/audience/window validated and "
            "remapped in the event namespace; no "
            "parallel event store."
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 owned b821 remains exact c2; coordinator rebind required for cumulative "
            "business runtime. W03 owner must adopt removal_cascade port for restricted "
            "removals; role private generation and native UI remain pending.",
            "W05 evaluator-to-trusted-source adapter and native feedback UI remain "
            "pending. Controlled persistence tests do not prove actual production history "
            "or model quality.",
            "Role snapshot tests use controlled catalogs/audits. No production private "
            "writer, failure-attempt sink, event-reference persistence or full role "
            "generation is claimed.",
            "Successful generation checks use controlled non-network models and catalog. "
            "W04 new private-ID fix and real business cumulative acceptance are still "
            "required; no production activation implied.",
        ]
    },
    {
        "previous_contract_revision": (
            "expansion-v3-ffa9cb25c4a9d74c670c8cd03aac284cb6a23c6bea04192dc0c6d3da6391532a"
        )
    },
    {
        "integration_changes": {
            "feedback-segment-scope": "Server-only complete input traces bind "
            "exact content hashes and dependencies per "
            "segment; fully authorized finite-scope "
            "readers retain proved text, missing or "
            "hidden dependencies degrade only affected "
            "parts."
        }
    },
    {
        "integration_changes": {
            "submitted-evidence-status": "New response evidence is explicitly "
            "user_submitted_unverified (or "
            "none_submitted); legacy absence stays "
            "unknown. Linking never claims quote or "
            "semantic verification."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-41a21baa9f86c9e7ee7d17b07aa0c55eb5b0dd24b6f04c8a402ec65f72ddf05c"
        )
    },
    {
        "integration_changes": {
            "W06-public-queue-capacity": "Persisted per-credential 1–2 job "
            "policy; existing jobs counted in "
            "locked transactions for public "
            "enqueue/refresh, not process memory. "
            "Native repository enqueue/failed retry "
            "still requires coordinator scope "
            "release."
        }
    },
    {
        "integration_changes": {
            "operation-readiness": "Installed and ready are distinct; closed "
            "registered operations return stable "
            "unavailable before public dispatch. "
            "Auth/delegation capabilities remain "
            "independent."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-a9f27fe80aead0f69080b23ece63773ab3e50131e77e41532581958b0a4fa3f4"
        )
    },
    {
        "integration_changes": {
            "recursive-public-reply-validation": "Fixed RoleReply DTO validates "
            "the entire JSON tree "
            "independently of permissive "
            "registrations; nested private "
            "metadata is rejected on write "
            "and historical public reads."
        }
    },
    {
        "integration_changes": {
            "authoritative-segment-traces": "A declared trace always constrains "
            "text hash and complete "
            "dependencies, including cited "
            "explanations and history; visible "
            "citations do not bypass it. The "
            "most-specific complete trace is "
            "authoritative for a field."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-d04601c2f279d3940e6b6e1cb452664585faa0b289f2a0c985b06aa28b9e3d24"
        )
    },
    {
        "integration_changes": {
            "W06-native-queue-capacity": "Native session-v2 enqueue/failed retry "
            "and V2Store share the same credential "
            "lock, SQL active-job count and "
            "persisted policy; idempotent replay "
            "does not reserve again; legacy v1 "
            "unchanged."
        }
    },
    {
        "previous_contract_revision": (
            "expansion-v3-e17e102c1dc0c7755dbaf6828d18ca17ad7a3c4485dc2fa25e90c4dd8f9211aa"
        )
    },
    {
        "integration_changes": {
            "native-runtime-slice": "One standard API/worker assembly; native "
            "investigation, assistant trials, resource "
            "decisions and colleague slots. Explicit "
            "failed-job refresh, no automatic model "
            "retry including expired leases, exact "
            "historical public event/source reads, real "
            "material activation in recovered role "
            "provenance. W05 r9 production evidence, "
            "atomic feedback and native callbacks are "
            "assembled with frozen advisory policies; "
            "W03 native composition remains pending."
        }
    },
    {
        "boundaries": [
            "This is W01 common foundation, not implemented W02-W15 business modules.",
            "v4 semantic engine, paid provider/model quality, full product QA and "
            "research results are not claimed.",
            "Existing v1 remains separate; internal snapshot/restore never appears in "
            "learner routes.",
            "W02 owned b821 remains exact c2; coordinator rebind required for cumulative "
            "business runtime. W03 owner must adopt removal_cascade port for restricted "
            "removals; role private generation and native UI remain pending.",
            "W05 evaluator-to-trusted-source adapter and native feedback UI remain "
            "pending. Controlled persistence tests do not prove actual production history "
            "or model quality.",
            "Role snapshot tests use controlled catalogs/audits. No production private "
            "writer, failure-attempt sink, event-reference persistence or full role "
            "generation is claimed.",
            "Successful generation checks use controlled non-network models and catalog. "
            "W04 new private-ID fix and real business cumulative acceptance are still "
            "required; no production activation implied.",
            "056: preceding stage boundaries are historical. Private non-local plumbing "
            "now has controlled no-network regression evidence, not real provider "
            "quality, PostgreSQL or final package acceptance. W02 must rebind to this new "
            "contract before standard installed runtime acceptance.",
        ],
        "integration_changes": {
            "056-default-installed-runtime": "Default API/worker loads the "
            "current installed package and "
            "verifies its actual manifest "
            "identity; explicit roots remain "
            "authoritative. Author roots remain "
            "reproducible uninstalled inputs.",
            "056-role-call-guard": "Durable phase reservation keyed by original "
            "request and explicit refresh generation; "
            "worker/HTTP recovery and provider changes "
            "cannot reissue calls. Mechanical "
            "language/binding verifier only, semantic "
            "quality unverified; local replies unchanged. "
            "Controlled fixture workers inherit "
            "production no-retry policy.",
            "056-v4-extension-contract": "Typed human-only delegation list and "
            "practice request/response schemas; "
            "exact OpenAPI mounted routes; durable "
            "source/target lifecycle and recovery "
            "documented. Authored content review "
            "lineage is verified against original "
            "manifest bytes and non-runtime files "
            "after rebinding.",
        },
        "previous_contract_revision": (
            "expansion-v3-805c1a7c37fd3ed124305e276b00f18717836eaed502a2213f4d436828f04fa9"
        ),
        "review_fixes": {
            "056-role-call-guard": "Durable phase reservation keyed by original request "
            "and explicit refresh generation; worker/HTTP "
            "recovery and provider changes cannot reissue calls. "
            "Mechanical language/binding verifier only, semantic "
            "quality unverified; local replies unchanged. "
            "Controlled fixture workers inherit production "
            "no-retry policy.",
            "QA055-13": "Formal schemas/OpenAPI/source inclusion and documented "
            "identity, authorization, recovery and error semantics. "
            "Multi-process/PostgreSQL and cross-directory migration remain "
            "unverified conditional checks.",
        },
    },
)
