"""249: replay the two original 245 public runs through the ticket projection."""

import copy
import json
from pathlib import Path

from career_lab.engineer.session import DETAIL_BUDGET, EngineerService, size

FIXTURES = Path(__file__).resolve().parents[2] / "apps/web/src/features/engineer-desk/fixtures"


def originals():
    return [
        json.loads((FIXTURES / f"trial-245-{name}.en.json").read_text())
        for name in ("fallback", "realtime")
    ]


def test_original_candidates_keep_public_rows_and_effective_limits():
    first, second = [EngineerService.trial_summary(row) for row in originals()]
    assert first["rows"][0]["actual_status"] == "fallback"
    assert second["rows"][0]["actual_status"] == "answered"
    assert second["rows"][0]["citations"][0]["version"] == 1
    assert second["effective_differences"] == {"update_strategy": "realtime_sync_not_provisioned"}
    assert all(
        [row["id"] for row in run["rows"]] == ["F01", "F04", "F05", "F12"]
        for run in [first, second]
    )
    ticket = json.loads((FIXTURES / "ticket-245.en.json").read_text())
    ticket["trials"] = [ticket["trials"][0], first, second]
    fitted = EngineerService.fit(ticket)
    assert size(fitted) <= DETAIL_BUDGET
    assert all(len(run["rows"]) == 4 for run in fitted["trials"][1:])
    # Agent reads retain their established summary visibility, even for another executor's runs.
    assert all(
        "rows" not in EngineerService.trial_summary(row, include_rows=False) for row in originals()
    )


def test_read_budget_omits_older_details_explicitly_before_run_identities():
    first, second = [EngineerService.trial_summary(row) for row in originals()]
    large = copy.deepcopy(first)
    large["rows"][0]["answer_summary"] = "x" * DETAIL_BUDGET
    fitted = EngineerService.fit({"trials": [large, second], "drafts": []})
    assert size(fitted) <= DETAIL_BUDGET
    assert len(fitted["trials"]) == 2
    assert fitted["trials"][0]["rows_omitted"] is True
    assert "rows" not in fitted["trials"][0]
    assert len(fitted["trials"][1]["rows"]) == 4
