"""MCP HTTP limits: one place for the numbers, per-authorization rate, bounded admission."""

from career_lab.mcp.streamable_http import DEFAULT_LIMITS, Admission, HttpLimits, TokenBuckets


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_mcp_http_limits_are_defined_in_one_place() -> None:
    assert DEFAULT_LIMITS == HttpLimits(
        in_flight=16, concurrent=4, burst=30, per_second=10.0, max_body=1_048_576
    )


def test_mcp_http_token_bucket_allows_a_burst_then_refills_at_its_rate() -> None:
    clock = Clock()
    buckets = TokenBuckets(burst=3, per_second=2.0, clock=clock)
    assert [buckets.take("grant") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert buckets.take("grant") == 0.5
    assert buckets.take("other grant") == 0.0
    clock.now += 0.5
    assert buckets.take("grant") == 0.0
    assert buckets.take("grant") == 0.5


def test_mcp_http_admission_is_bounded_and_released() -> None:
    admission = Admission(2)
    assert admission.enter() and admission.enter()
    assert not admission.enter()
    admission.leave()
    assert admission.enter()
