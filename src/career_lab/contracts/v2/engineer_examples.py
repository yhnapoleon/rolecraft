"""Synthetic examples for engineer file contracts; never measured product results."""

from pydantic import BaseModel

from . import engineer as E
from .core import V2, Executor, FileRef, digest
from .examples import STAMP, sample_model
from .world import EffectiveConfig, TestResultV2


def engineer_examples() -> dict[str, V2]:
    ref = FileRef(path="files/example.json", sha256="0" * 64)
    executor = Executor(id="example-reviewer", kind="system")
    unresolved = E.EngineerUnresolvedItem(id="open-1", description="Synthetic open item")
    submission = E.EngineerSubmissionRecord(
        contract_version="engineer-review-v1",
        id="submission-1",
        pack=ref,
        config=ref,
        base_config_hash=ref.sha256,
        regression_report=None,
        unresolved=(unresolved,),
        explanation="Synthetic configuration-only example",
        executor=executor,
        created_at=STAMP,
        work_language="en",
    )
    fixed = E.EngineerReviewInput(
        contract_version="engineer-review-v1",
        pack=ref,
        baseline_config=ref,
        config=ref,
        scenario=ref,
        probe_suite=ref,
        reviewer_version=ref,
        resource_snapshot=ref,
        submission=ref,
        probe_ids=("probe-1",),
        source_as_of=sample_model(E.VersionPoint),
        resolved_config=sample_model(EffectiveConfig),
        work_language="en",
        model=None,
    )
    actual = sample_model(TestResultV2).model_copy(update={"config": fixed.resolved_config})
    result = E.EngineerProbeResult(
        probe_id="probe-1",
        visibility="public",
        query=actual.query,
        expected=E.EngineerProbeExpectation(status=actual.status),
        actual=actual,
        result="pass",
        config_hash=digest(fixed.resolved_config.effective),
        elapsed_seconds=0,
    )
    finding = E.EngineerFinding(
        kind="target_fix",
        status="pass",
        visibility="public",
        description="Synthetic rule comparison",
        probe_ids=(result.probe_id,),
    )
    report = E.EngineerRegressionReport(
        contract_version="engineer-review-v1",
        id="review-1",
        submission=ref,
        input=fixed,
        input_hash=digest(fixed),
        reviewer=executor,
        created_at=STAMP,
        status="verified",
        claim_check="not_provided",
        results=(result,),
        findings=(finding,),
        unresolved=(unresolved,),
        advice=E.EngineerAdvice(status="waiting_model", text=None, model=None),
    )
    claimed = E.EngineerClaimedReport(
        contract_version="engineer-review-v1",
        id="claimed-1",
        pack=ref,
        config=ref,
        created_at=STAMP,
        results=(E.EngineerProbeClaim(probe_id="probe-1", result="pass"),),
    )
    examples: dict[str, V2] = {}

    def visit(value: object) -> None:
        if isinstance(value, BaseModel):
            if type(value).__module__ == E.__name__:
                examples[type(value).__name__] = value
            for name in type(value).model_fields:
                visit(getattr(value, name))
        elif isinstance(value, tuple):
            for child in value:
                visit(child)

    for value in (
        submission,
        report,
        claimed,
        E.public_engineer_report(report),
        E.EngineerPublicAdvice(status="waiting_model", model=None),
    ):
        visit(value)
    return examples
