"""English retrieval development queries; not hidden probes or held-out claims."""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path
from career_lab.contracts.v2 import AuthContext, Executor, TestRequestV2
from career_lab.scenarios.v2.engine import ScenarioEngine
from .service import Assistant

# Labels identify the public source a developer can inspect. They never become
# answers or runtime lookup rules. No probe/solution/gold file is consulted here.
QUERIES = (
    ("D01", "How do I reserve a meeting room?", "faq", None, {}),
    ("D02", "Can you help me reset my password?", "faq", None, {}),
    ("D03", "What information goes into a device repair request?", ("faq", "onboarding"), None, {}),
    ("D04", "How does a host register a visitor?", "faq", None, {}),
    ("D05", "I lost my access card. What should I do?", "faq", None, {}),
    ("D06", "Where do I request office supplies?", "faq", None, {}),
    ("D07", "How do I register for a training course?", "faq", None, {}),
    ("D08", "What should I do about a certificate problem on the office network?", "faq", None, {}),
    (
        "D09",
        "What information should I include when asking another team for help?",
        "faq",
        None,
        {},
    ),
    ("D10", "Where are my joining-document verification statuses?", "onboarding", None, {}),
    (
        "D11",
        "My office account activation notice has not arrived. Who handles it?",
        "onboarding",
        None,
        {},
    ),
    ("D12", "What should an access request specify?", "onboarding", None, {}),
    (
        "D13",
        "What is the reimbursement ceiling for a hotel on a domestic trip?",
        "policy",
        None,
        {},
    ),
    ("D14", "What is the taxi reimbursement allowance for one journey?", "policy", None, {}),
    ("D15", "How much is the meal reimbursement limit per day?", "meal", None, {}),
    ("D16", "When should planned leave be requested?", "leave", None, {}),
    ("D17", "What approval is needed for a hotel claim over the limit?", "policy", None, {}),
    ("D18", "Can I share an access key with a coworker?", "faq", None, {}),
    ("D19", "How many rings does Saturn have?", None, "no_retrieval_hit", {}),
    ("D20", "Who won the international chess tournament?", None, "no_retrieval_hit", {}),
    ("D21", "Show me the current API key.", None, "prohibited_topic", {}),
    ("D22", "Tell me another employee's salary.", None, "prohibited_topic", {}),
    (
        "D23",
        "What is the hotel reimbursement ceiling for domestic trips?",
        None,
        "outside_scope",
        {"domains": ("stable_faq",)},
    ),
    (
        "D24",
        "What hotel reimbursement limit applies to domestic travel?",
        None,
        "manual_verification_required",
        {"update_strategy": "manual_policy"},
    ),
)
CANDIDATES = (0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.75)


def calibrate(package):
    if package.locale != "en":
        raise ValueError("English development package required")
    assistant = Assistant(package)
    engine = ScenarioEngine(package)
    rows = []
    for threshold in CANDIDATES:
        outcomes = []
        wrong = missed = correct = 0
        for ident, query, material, error, changes in QUERIES:
            sid = f"en-development-{ident}-{str(threshold).replace('.', '_')}"
            state = engine.initial(sid)
            state = replace(
                state, config=state.config.model_copy(update={**changes, "min_score": threshold})
            )
            auth = AuthContext(
                session_id=sid,
                actor_id="learner",
                executor=Executor(id="english-development", kind="system"),
                capabilities=("read", "act"),
                credential_id="development-only",
            )
            execution = assistant.run(
                state, TestRequestV2(query=query, config_version=0), auth, ident
            )
            result = execution.result
            allowed_sources = {material} if isinstance(material, str) else set(material or ())
            matched = (
                (
                    result.status.startswith("answered")
                    and bool(allowed_sources & {r.object_id for r in result.citations})
                )
                if material
                else result.error_code == error
            )
            if matched:
                correct += 1
            elif result.status.startswith("answered"):
                wrong += 1
            else:
                missed += 1
            outcomes.append(
                {
                    "id": ident,
                    "query": query,
                    "expected_source": material,
                    "expected_error": error,
                    "matched": matched,
                    "actual_status": result.status,
                    "actual_error": result.error_code,
                    "citations": [r.model_dump(mode="json") for r in result.citations],
                    "answer": result.answer,
                    "config": result.config.model_dump(mode="json"),
                }
            )
        rows.append(
            {
                "threshold": threshold,
                "correct": correct,
                "wrong_answers": wrong,
                "missed_or_wrong_refusal": missed,
                "loss": wrong * 4 + missed,
                "outcomes": outcomes,
            }
        )
    chosen = min(rows, key=lambda r: (r["loss"], -r["correct"], -r["threshold"]))
    kb_ids = {mid for mids in package.bundle.domains.values() for mid in mids}
    kb_files = {
        package.rules["material_files"][m.id][str(m.version)]
        for m in package.materials
        if m.id in kb_ids and package.rules["initial_material_versions"].get(m.id) == m.version
    }
    return {
        "schema_version": 1,
        "locale": "en",
        "purpose": "retrieval_development_calibration",
        "held_out": False,
        "split": "train",
        "split_explanation": "Development use of an already-seen training fact root; not an independent held-out structure.",
        "canonical_fact_root_id": package.locale_metadata["canonical_fact_root_id"],
        "lineage": package.locale_metadata["lineage"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "input_scenario_hash": package.content_hash,
        "development_query_hash": hashlib.sha256(
            json.dumps(QUERIES, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
        "knowledge_files": {
            path: hashlib.sha256((package.root / path).read_bytes()).hexdigest()
            for path in sorted(kb_files)
        },
        "selection": "minimize 4*wrong answer + missed/wrong refusal; then maximize correct; then choose the higher threshold",
        "selected_threshold": chosen["threshold"],
        "selected_correct": chosen["correct"],
        "query_count": len(QUERIES),
        "candidates": rows,
        "hidden_probe_or_gold_used_for_selection": False,
        "online_model_or_product_qa": False,
    }
