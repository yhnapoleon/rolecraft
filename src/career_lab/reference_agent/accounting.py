"""Conservative total usage from provider receipts and typed tool results."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from career_lab.contracts.v2.core import ActualConsumption, Budget, ModelAttemptUsage, ProtocolError
from career_lab.contracts.v2.world import TestResultV2
from career_lab.reference_agent.runner import Checkpoint


@dataclass(frozen=True)
class UsageLedger:
    consumption: ActualConsumption
    attempts: tuple[ModelAttemptUsage, ...]
    unknown_sources: tuple[str, ...]


def measure(execution: Checkpoint, own: Sequence[ModelAttemptUsage]) -> UsageLedger:
    attempts = list(own)
    unknown = []
    for result in execution.results:
        if result.status != "completed":
            unknown.append(result.request_id + ":pending")
            continue
        if result.jobs:
            unknown.append(result.request_id + ":jobs")
        if result.operation != "tests.create":
            continue
        try:
            test = TestResultV2.model_validate(result.response.result["test"])
        except (KeyError, TypeError, ValidationError):
            unknown.append(result.request_id + ":test_receipt")
            continue
        attempts.extend(test.execution.attempts)
        if not test.execution.cost_complete:
            unknown.append(result.request_id + ":test_cost")
    usage_known = not unknown and all(attempt.usage_known for attempt in attempts)
    cost_known = not unknown and all(attempt.cost is not None for attempt in attempts)
    consumption = ActualConsumption(
        model_attempt_count=len(attempts),
        actions=execution.dispatch_count,
        input_tokens=sum(attempt.input_tokens or 0 for attempt in attempts)
        if usage_known
        else None,
        output_tokens=sum(attempt.output_tokens or 0 for attempt in attempts)
        if usage_known
        else None,
        cost=sum(attempt.cost or 0 for attempt in attempts) if cost_known else None,
        wall_seconds=(datetime.now(UTC) - execution.started_at).total_seconds(),
        usage_complete=usage_known,
        cost_complete=cost_known,
    )
    return UsageLedger(consumption, tuple(attempts), tuple(unknown))


def require_budget(ledger: UsageLedger, budget: Budget) -> None:
    usage = ledger.consumption
    if ledger.unknown_sources:
        raise ProtocolError("nested_usage_unknown")
    if usage.model_attempt_count >= budget.model_calls or usage.actions >= budget.actions:
        raise ProtocolError("run_budget_exhausted")
    require_spending(usage, budget, next_call=True)


def require_spending(usage: ActualConsumption, budget: Budget, *, next_call: bool = False) -> None:
    if budget.tokens is not None:
        if usage.input_tokens is None or usage.output_tokens is None:
            raise ProtocolError("run_usage_unknown")
        if (
            usage.input_tokens + usage.output_tokens > budget.tokens
            or next_call
            and usage.input_tokens + usage.output_tokens == budget.tokens
        ):
            raise ProtocolError("run_budget_exhausted")
    if budget.currency_limit is not None:
        if usage.cost is None:
            raise ProtocolError("run_usage_unknown")
        if usage.cost > budget.currency_limit or next_call and usage.cost == budget.currency_limit:
            raise ProtocolError("run_budget_exhausted")


def require_nested_budget(ledger: UsageLedger, budget: Budget, operation: str) -> None:
    """Do not start potentially model-backed tools once any allowance is exhausted."""
    if operation in {"tests.create", "reviews.create", "submissions.create"}:
        require_budget(ledger, budget)
