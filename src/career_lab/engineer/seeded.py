"""Scenario-supplied engineering tickets, indexed by scenario ID and work language.

The published scenario packages are byte-protected, so the ticket text lives here. The
target question itself is read from the scenario's engineer regression suite (a public row)
by its canonical probe ID, in the session's own work language.
"""

import json
from typing import Any

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import TransactionView

from .suite import require_suite

SEED_EXECUTOR = C.Executor(id="engineer-ticket-seed", kind="system")

SEEDED_TICKETS: dict[str, dict[str, Any]] = {
    "pm_pilot": {
        "canonical_probe_id": "F01",
        "title": {
            "zh": "委托：住宿报销上限的回答需要排查",
            "en": "Ticket: the hotel reimbursement limit answer needs investigation",
        },
    }
}

ORIGIN_LABELS = {
    "ticket_seed": {
        "zh": "委托附带的复现记录",
        "en": "Reproduction record attached to the ticket",
    },
    "learner_test": {"zh": "产品经理的测试记录", "en": "Product manager's test record"},
}


def tests_title(language: str, count: int) -> str:
    if language == "en":
        return f"Tests handed over from product ({count})"
    return f"产品经理交来的测试（{count} 条）"


def seeded_ticket(module: ScenarioModule) -> tuple[dict[str, Any], str]:
    """The ticket text and its target question for this installed package."""
    entry = SEEDED_TICKETS.get(module.package.bundle.id)
    if entry is None:
        raise C.ProtocolError("engineer_seeded_ticket_unavailable", status=404)
    rows = json.loads(require_suite(module.package))
    wanted = entry["canonical_probe_id"]
    query = next(
        (row["query"] for row in rows if row["public"] and row["canonical_probe_id"] == wanted),
        None,
    )
    if query is None:
        raise C.ProtocolError("engineer_seeded_ticket_unavailable", status=404)
    return entry, query


def seed_record(
    view: TransactionView,
    module: ScenarioModule,
    auth: C.AuthContext,
    query: str,
    request_id: str,
    operation: str,
) -> C.TestResultV2:
    """Run the target question once, for real, on the session's current configuration.

    The record names the system as its executor and is kept in the engineer store only:
    it never enters the PM test list, timeline or evaluation evidence.
    """
    snapshot = module.snapshot(view)
    seed_auth = auth.model_copy(update={"executor": SEED_EXECUTOR})
    record = module.assistant.run(
        snapshot,
        C.TestRequestV2(query=query, config_version=snapshot.config.config_version),
        seed_auth,
        request_id,
        operation_name=operation,
        # Rule-based like reproduction, trials and reviews, so it can be re-run exactly.
        recognize=False,
    ).result
    for ref in record.citations:
        module.check_evidence(view, auth, ref)
    return record
