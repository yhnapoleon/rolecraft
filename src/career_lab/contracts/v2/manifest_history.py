"""Append-only publication metadata for the expansion contract.

Each record is applied in tuple order. Mapping fields merge in insertion order;
scalar/list fields replace the prior value. Never edit an old record: append a
record with integration_changes/review_fixes and the previous published revision.
The repeated previous_contract_revision values preserve the original export chain.

source_files and documents are the original publication's historical fingerprints,
not hashes of today's checkout. Current code identity belongs in delivery receipts.
Schemas, examples and OpenAPI are always generated from production models/routes.
The public error codes are an explicit contract, not every internal ProtocolError.
Append new codes to ERROR_CODES; output is sorted, so historical order is retained.

Generate on the task branch first; the coordinator generates again after merging
all new records. See module-interfaces.md for the integration procedure.
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
        "documents": {
            "compatibility.md": {
                "path": "compatibility.md",
                "sha256": "a1115dfc12f6c9482a542249b9395b0d091a042ada9e49ef188d337e5c93a971",
            },
            "consumer-request-resolution.json": {
                "path": "consumer-request-resolution.json",
                "sha256": "fe388a221162a6b213225b8579db4b43368d97412d3e18dd8cd3a16f2ba31d54",
            },
            "module-interfaces.md": {
                "path": "module-interfaces.md",
                "sha256": "759f10925dcd68908c027f86eaff10d8424fe38dac011a09fe02eb6b5a97c2cd",
            },
        },
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
        "source_files": {
            "src/career_lab/api/app.py": (
                "9f073708c893c2ed5fac7a06b69d5c173af67e9d4fda94f868b06bebdf46be68"
            ),
            "src/career_lab/api/evaluation_runtime.py": (
                "365731dd38b21e28b7e2653434a7afd089e5e01b22ac3734636963ce3628d9a4"
            ),
            "src/career_lab/api/feedback_integration.py": (
                "ab0adab1472101b5bfb4bfade4b237f5a918ccdbb47ef1452d887d2c449b66c4"
            ),
            "src/career_lab/api/lifecycle_integration.py": (
                "099f37bdb5b1678f5e3c86ae42c8f6788a2c1ad20f89f7fcaa26a932c5a75066"
            ),
            "src/career_lab/api/modules.py": (
                "db74178fab5ddfe27a7b949aaa195dbbb9abcfe15859bf8f3428c5d830cb0542"
            ),
            "src/career_lab/api/private_roles.py": (
                "e12889119d1c78109cc2d503ee70c143fe0d58008f4e59670f55540a6e684759"
            ),
            "src/career_lab/api/public_materials.py": (
                "dfdd1b42af9501541d75cfa7875297edb91887bc46db79595107cc31efaa2faf"
            ),
            "src/career_lab/api/role_snapshot.py": (
                "19ea854aff520928b219f314bfa63608b90d62825603a3e36063a278ab563551"
            ),
            "src/career_lab/api/v2_routes.py": (
                "91c8d42225aa52d460734e6460456b896c6a737f3ec131a406b0d1c9b791e96d"
            ),
            "src/career_lab/api/v4_config.py": (
                "248ba9d11bd9cf5f16513f9407713a87c870b0df6bf98848c267e90de434d46f"
            ),
            "src/career_lab/api/v4_extensions.py": (
                "f050c0e6d4382c5c43b648c5d8a1ea9d1225e998835617c12875796a520b9673"
            ),
            "src/career_lab/api/vertical_reads.py": (
                "95a8843b5e8b569a264ce28da9b4f3613e179ef29d41c171a6544e53a65acce8"
            ),
            "src/career_lab/api/vertical_runtime.py": (
                "4a5ff5e051e46de8d350d9b2c3cf47ba65ce3a80d5cbf07430b972b13282380c"
            ),
            "src/career_lab/api/workspace_integration.py": (
                "0b731ea27219d49767b72e07b65293edc810eae79872842f8a2459ef863e2604"
            ),
            "src/career_lab/cli.py": (
                "4085c8ce4b0f242734bccb4e4f8a8ac713d7c78ba42a724eea767b115b4469ce"
            ),
            "src/career_lab/contracts/__init__.py": (
                "10140c7ad16ce4744487b7e5f3418b726caa52979d662feda985b44986e2d7ac"
            ),
            "src/career_lab/contracts/actions.py": (
                "835fbb62979891cbf97d0580e0843c2a8f97b8a8bcc08c8a01afecec36f919ac"
            ),
            "src/career_lab/contracts/base.py": (
                "e62af2f4c8d827a994ae7f69d2022d50b5a42581d885348aab070fa407de2a77"
            ),
            "src/career_lab/contracts/deliverables.py": (
                "0455a250f84c4008a823c0e54af7dc69cde277cca594d177e59b91cd7333a6f9"
            ),
            "src/career_lab/contracts/evaluation.py": (
                "6dc4969cf02222543fa96ddffbd4d9fd19f4813ee1f9b85ea3d193797ac4ea23"
            ),
            "src/career_lab/contracts/scenario.py": (
                "b191244dd1356503b153abf3a31921ce7911ec19b66534378b369b35d135e3b0"
            ),
            "src/career_lab/contracts/v2/__init__.py": (
                "a785e74095d14713af0d98565017df553f06cab46c515a8805af46a3a1c24a47"
            ),
            "src/career_lab/contracts/v2/core.py": (
                "6dc7ce6ab00d781f8c14f505a7c8f9ef482e8715dee7fb78a2e7ee3da1318fb5"
            ),
            "src/career_lab/contracts/v2/data.py": (
                "bd0888c2937400bf00ceeac53b9e49260040c3782c7cbfaca62d10097841065b"
            ),
            "src/career_lab/contracts/v2/discovery.py": (
                "93cc327208f8e269c57baf3016c09b820a1076d556e60ab40cb04ecc4dbd5db5"
            ),
            "src/career_lab/contracts/v2/evaluation.py": (
                "0697b8f77246da064a43b31596acb12e7943405e6d5ea3b084c376e22dc37307"
            ),
            "src/career_lab/contracts/v2/examples.py": (
                "a7ccad36f83ede154220f28689eb9f81f6d5f41569c6ed3319cdf916eb7fec4a"
            ),
            "src/career_lab/contracts/v2/export.py": (
                "b311582586734defdd313428b02f90b582b28f38ec53639f6d6e2db3ada01d1c"
            ),
            "src/career_lab/contracts/v2/extensions.py": (
                "6e66df02813583f8f7bd4d707a3815960558c93d7b45cadfa119eb6b70cf1be1"
            ),
            "src/career_lab/contracts/v2/files.py": (
                "c521605a5e630e5a3010cfcec217ae37ac67507c98169ff3ac4a04758866dc30"
            ),
            "src/career_lab/contracts/v2/legacy.py": (
                "9c09304cfe65e663839719f00d9237e44a7dfc924c13e6ad6dc799f8c25defd3"
            ),
            "src/career_lab/contracts/v2/projection.py": (
                "24dd56480f1de6f8489241e9bd4d65cd7bf533427b2dbc91768318f1d733f896"
            ),
            "src/career_lab/contracts/v2/provider.py": (
                "8ef69da0f37b0e91ec235ab6ac039b2c81d1be14c7affb1eb8e71dda3c815306"
            ),
            "src/career_lab/contracts/v2/requests.py": (
                "0bf9ee25aeaba3a21f7d218588a8262ae383524161d0cb6af955e28ac0c3658f"
            ),
            "src/career_lab/contracts/v2/research.py": (
                "6319d233b5c1ad6833236bd9c51daf2b7d140d5aaade6853a672b4ad76561629"
            ),
            "src/career_lab/contracts/v2/workspace.py": (
                "32662a94bb7e728f1def9fdfe11c4570f8f0651afff4fbab8b16f78bfdc6e878"
            ),
            "src/career_lab/contracts/v2/world.py": (
                "afa8e26e1e27200260d61ade7eb987a5ea70a38e99af4cb89e658ad8de6ad03a"
            ),
            "src/career_lab/contracts/versioning.py": (
                "da1fc0d7a3bb7b1110cc33d1b7a7f68dcc6dbb8c061f81f3778a113a7ae809fb"
            ),
            "src/career_lab/jobs/repository.py": (
                "dbf999faadb779f386fa3661acf51f335fdbb7426d024a70416102e8d2f04283"
            ),
            "src/career_lab/jobs/worker.py": (
                "a91bffb17fdd295db6ce259cc84f9fa3c0e7deb8debfa915954b1eb380aad437"
            ),
            "src/career_lab/rubrics/registry.py": (
                "204f90efa1b93bc010d638f7310ef396148caf2aed3af132c7a5e064442700de"
            ),
            "src/career_lab/storage/v2_jobs.py": (
                "397b36937d61acbd3283bce7b2ef8f4e5c6f9fabe691288ddf43f1a490383890"
            ),
            "src/career_lab/storage/v2_lifecycle.py": (
                "820df180088bd3c09a550912aab838f4586042955b3220553ae294167a97c857"
            ),
            "src/career_lab/storage/v2_remap.py": (
                "05ded384d8682e2cef5a14828c7418eeb427ad9ee1e9b5614846c74b786debee"
            ),
            "src/career_lab/storage/v2_snapshot.py": (
                "e4d295e54c3ffe9813bb93ebd90d57a9b65368d91f1e83d4dda502e902108f0f"
            ),
            "src/career_lab/storage/v2_store.py": (
                "54ae8a6353e3e09e72ac41dcbafe4604984a1963bef161f1199afdf40fdde014"
            ),
            "src/career_lab/storage/v2_tables.py": (
                "db85ef5684efbee9dd0788d41377801eecd8acd1c7802c591f54e0688e02fcac"
            ),
        },
    },
)

ERROR_CODES: tuple[str, ...] = (
    "action_forbidden",
    "action_remap_schema_required",
    "active_share_on_removed_product",
    "annotation_evidence_not_applicable_at_reference_time",
    "annotation_no_legal_joint_target",
    "annotation_not_accepted",
    "annotation_record_mismatch",
    "annotation_task_mismatch",
    "approval_policy_required",
    "async_cycle_write_forbidden",
    "async_state_change_forbidden",
    "campaign_not_authorized",
    "capability_forbidden",
    "capture_precedes_reference",
    "config_reference_mismatch",
    "config_write_required",
    "context_stale",
    "credential_expired",
    "credential_revoked_or_invalid",
    "cycle_scope_invalid",
    "decision_not_persisted",
    "delegation_escalation",
    "delegation_executor_invalid",
    "delegation_id_reused",
    "delegation_job_backend_unavailable",
    "delegation_job_limit_invalid",
    "delegation_job_limit_reached",
    "delegation_job_policy_invalid",
    "delegation_scope_invalid",
    "derived_feedback_only",
    "derived_feedback_subject_mismatch",
    "derived_feedback_subject_missing",
    "derived_subject_invalid",
    "disclosure_quote_missing",
    "disclosure_session_mismatch",
    "disclosure_time_mismatch",
    "environment_adapter_unavailable",
    "evaluation_binding_mismatch",
    "evaluation_runtime_unavailable",
    "evaluation_source_mismatch",
    "event_projection_ambiguous",
    "event_projection_identity_mismatch",
    "event_reference_invalid",
    "event_reference_requires_projection",
    "event_view_invalid",
    "evidence_validity_undetermined",
    "executor_spoofed",
    "external_reference_drift",
    "external_reference_mismatch",
    "feedback_boundary_requires_server_trace",
    "feedback_completeness_scope_unknown",
    "feedback_criterion_unknown",
    "feedback_evidence_status_required",
    "feedback_evidence_unavailable",
    "feedback_not_ready",
    "feedback_projection_not_persistable",
    "feedback_record_immutable",
    "feedback_response_basis_missing",
    "feedback_response_identity_mismatch",
    "feedback_response_input_mismatch",
    "feedback_response_only",
    "feedback_response_operation_required",
    "feedback_subject_invalid",
    "feedback_trace_invalid",
    "feedback_trace_path_invalid",
    "file_hash_mismatch",
    "file_missing",
    "file_outside_root",
    "foreign_session_reference",
    "future_evidence",
    "history_cursor_invalid",
    "history_identity_mismatch",
    "human_required",
    "import_mode_mismatch",
    "import_receipt_immutable",
    "installed_scenario_identity_mismatch",
    "invalid_settings",
    "job_context_invalid",
    "job_cycle_changed",
    "job_cycle_closed",
    "job_effect_already_committed",
    "job_execution_failed",
    "job_identity_mismatch",
    "job_kind_invalid",
    "job_not_found",
    "job_output_cycle_closed",
    "job_refresh_not_available",
    "job_refresh_only",
    "job_result_identity_conflict",
    "job_session_inactive",
    "job_share_unavailable",
    "job_snapshot_mismatch",
    "job_snapshot_missing",
    "legacy_endpoint_forbidden",
    "legacy_kind_unsupported",
    "legacy_type_unavailable",
    "module_object_invalid",
    "module_response_contract_missing",
    "module_response_invalid",
    "module_unavailable",
    "not_action_boundary",
    "object_dependency_cycle",
    "object_identity_conflict",
    "object_identity_mismatch",
    "object_kind_unavailable",
    "object_not_found",
    "object_reference_duplicate",
    "object_reference_missing",
    "object_scope_forbidden",
    "object_session_mismatch",
    "object_version_conflict",
    "observation_history_unavailable",
    "observation_window_unsupported",
    "operation_route_mismatch",
    "practice_feedback_scope_mismatch",
    "practice_language_mismatch",
    "practice_language_unavailable",
    "practice_request_reused",
    "practice_target_binding_changed",
    "preview_has_writes",
    "private_object_channel_required",
    "product_required",
    "product_requires_share",
    "protocol_version_unsupported",
    "public_material_projection_invalid",
    "read_capability_cannot_write",
    "reference_context_required",
    "reference_provider_unavailable",
    "reference_quote_mismatch",
    "reference_span_forbidden",
    "reference_time_mismatch",
    "reference_view_expired",
    "reference_view_required",
    "reference_window_unavailable",
    "request_basis_immutable",
    "request_basis_reference_mismatch",
    "request_id_reused",
    "request_not_found",
    "request_record_invalid",
    "research_read_only",
    "restore_context_missing",
    "restore_id_reused",
    "restore_parent_auth_missing",
    "restore_request_id_required",
    "restore_requires_new_session",
    "restore_target_exists",
    "restore_target_mismatch",
    "restore_token_conflict",
    "review_followup_invalid",
    "reviewed_practice_option_required",
    "revision_cycle_required",
    "revision_not_available",
    "revision_parent_not_current",
    "role_attempt_guard_unavailable",
    "role_attempt_identity_conflict",
    "role_attempt_identity_invalid",
    "role_attempt_invalid",
    "role_attempt_status_invalid",
    "role_authority_invalid",
    "role_context_identity_immutable",
    "role_context_private",
    "role_disclosure_invalid",
    "role_executor_spoofed",
    "role_generation_identity_conflict",
    "role_generation_only",
    "role_history_identity_invalid",
    "role_history_incomplete",
    "role_history_requires_migration",
    "role_history_source_invalid",
    "role_integration_not_accepted",
    "role_job_snapshot_required",
    "role_job_snapshot_unrecorded",
    "role_not_available",
    "role_private_audience_invalid",
    "role_private_authority_required",
    "role_private_context_mismatch",
    "role_private_identity_invalid",
    "role_private_plan_changed",
    "role_private_record_invalid",
    "role_private_scope_mismatch",
    "role_private_source_missing",
    "role_private_source_unapproved",
    "role_public_cycle_invalid",
    "role_public_private_dependency",
    "role_reader_reserved",
    "role_reply_private_fields_forbidden",
    "role_request_forbidden",
    "role_share_receipt_invalid",
    "role_snapshot_identity_invalid",
    "role_snapshot_state_missing",
    "role_subject_invalid",
    "role_turn_identity_invalid",
    "role_worker_required",
    "route_object_mismatch",
    "rules_engine_unavailable",
    "scenario_binding_mismatch",
    "scenario_module_unavailable",
    "scenario_read_only",
    "scenario_state_private",
    "session_not_found",
    "session_paused",
    "session_submitted",
    "share_identity_immutable",
    "share_record_invalid",
    "snapshot_boundary_invalid",
    "snapshot_event_reference_missing",
    "snapshot_event_scope",
    "snapshot_log_gap",
    "snapshot_namespace_collision",
    "snapshot_object_scope",
    "snapshot_point_mismatch",
    "snapshot_revision_mismatch",
    "snapshot_revision_unavailable",
    "snapshot_session_mismatch",
    "snapshot_source_mismatch",
    "snapshot_window_unavailable",
    "state_field_forbidden",
    "step_observation_mismatch",
    "step_request_mismatch",
    "submission_required",
    "temporal_reference_mismatch",
    "temporal_scope_undetermined",
    "token_invalid",
    "token_required",
    "training_split_forbidden",
    "undeclared_object_reference",
    "unsupported_empty_gold_evidence",
    "use_job_refresh",
    "use_scoped_observation",
    "v1_envelope_required",
    "v2_envelope_required",
    "v2_session_required",
    "version_conflict",
    "work_language_unavailable",
    "worker_claim_required",
    "worker_lease_lost",
    "workspace_actor_forbidden",
)

ERROR_HTTP_POLICY: dict[str, str] = {
    "401": "missing/invalid authentication",
    "403": "capability/scope denied",
    "404": "not found or unauthorized object",
    "409": "version/hash/identity conflict",
    "422": "invalid request/business precondition",
    "503": "uninstalled/unavailable module or invalid server result",
}
