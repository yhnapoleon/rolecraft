"""The E1-E5 rule evaluation of one stored review, read from the private review store.

Every input is the server's own private record: the frozen review input, the private report,
the submission record, the original and candidate configurations and the self-report. Files
are checked against the hashes the frozen input records. Only the evaluator's output, which
holds public probe IDs and hidden counts, leaves this module.
"""

from pathlib import Path

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import (
    EngineerClaimedReport,
    EngineerReviewInput,
    EngineerSubmissionRecord,
)
from career_lab.contracts.v2.engineer_evaluation import EngineerRuleEvaluation

from .evaluation import evaluate_review
from .review_store import load_report


def stored_evaluation(private_root: Path, review_id: str) -> EngineerRuleEvaluation:
    """Raises ``engineer_review_changed`` when the private records are missing or altered."""
    inputs_root = private_root / "inputs" / review_id
    try:
        inputs = EngineerReviewInput.model_validate_json((inputs_root / "input.json").read_bytes())
        if "review-" + C.digest(inputs) != review_id:
            raise ValueError("review identity mismatch")
        report = load_report(private_root / "reports" / review_id, inputs)
        submission = EngineerSubmissionRecord.model_validate_json(
            C.read_file(inputs_root, inputs.submission)
        )
        claimed = (
            EngineerClaimedReport.model_validate_json(
                C.read_file(inputs_root, submission.regression_report)
            )
            if submission.regression_report is not None
            else None
        )
        return evaluate_review(
            report,
            submission,
            C.AssistantConfig.model_validate_json(C.read_file(inputs_root, inputs.baseline_config)),
            C.AssistantConfig.model_validate_json(C.read_file(inputs_root, inputs.config)),
            claimed=claimed,
        )
    except (OSError, ValueError, C.ProtocolError):
        raise C.ProtocolError("engineer_review_changed", status=409) from None
