"""Source-grounded English relevance; these queries are development, not held out."""

from dataclasses import replace
from pathlib import Path
import pytest
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.public_cases import run_pre_event_trial
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.assistant.v2.calibration_en import QUERIES

ROOT = Path(__file__).resolve().parents[3] / "scenarios/pm_pilot/v2"


@pytest.mark.parametrize(
    "query",
    [
        "How much can I claim for food on a business trip?",
        "What is the daily lunch reimbursement limit?",
        "What is the daily dinner reimbursement limit?",
        "How much is the meal reimbursement limit per day?",
    ],
)
def test_food_expenses_do_not_return_taxi_amount(query):
    package = load_package(ROOT / "locales/en")
    result = run_pre_event_trial(package, "meal-relevance", query, {})["result"]
    assert result["status"] == "answered" and "100" in result["answer"]
    assert {r["object_id"] for r in result["citations"]} == {"meal"}


@pytest.mark.parametrize(
    "query",
    [
        "What should I do if my expense form is returned?",
        "What should I do if my hotel expense form is rejected?",
        "How do I appeal a denied meal claim?",
    ],
)
def test_unwritten_rejection_process_is_not_invented_from_form_mentions(query):
    package = load_package(ROOT / "locales/en")
    result = run_pre_event_trial(package, "unsupported-process", query, {})["result"]
    assert result["status"] == "fallback" and result["error_code"] == "no_retrieval_hit"
    assert result["citations"] == []


@pytest.mark.parametrize("ident,query,material,error,changes", QUERIES)
def test_existing_development_queries_at_frozen_default(ident, query, material, error, changes):
    package = load_package(ROOT / "locales/en")
    result = run_pre_event_trial(package, ident, query, changes)["result"]
    if material:
        allowed = {material} if isinstance(material, str) else set(material)
        assert result["status"].startswith("answered") and allowed & {
            r["object_id"] for r in result["citations"]
        }
    else:
        assert result["error_code"] == error
