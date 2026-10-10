"""Run a fixed suite through the real assistant with one candidate configuration."""

import json
from dataclasses import dataclass, replace
from time import perf_counter

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import EngineerProbeExpectation, EngineerProbeResult
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.policy import effective_config


@dataclass(frozen=True)
class Probe:
    id: str
    query: str
    public: bool
    expected: EngineerProbeExpectation


def suite_probes(raw: bytes) -> tuple[Probe, ...]:
    rows = json.loads(raw)
    probes = tuple(
        Probe(
            row["id"],
            C.TestRequestV2(query=row["query"], config_version=0).query,
            row["public"],
            EngineerProbeExpectation.model_validate(row["expected"]),
        )
        for row in rows
    )
    if not probes or len({p.id for p in probes}) != len(probes):
        raise C.ProtocolError("engineer_suite_invalid")
    return probes


def matches(actual: C.TestResultV2, expected: EngineerProbeExpectation) -> bool:
    return (
        actual.status == expected.status
        and actual.error_code == expected.error_code
        and all(text in actual.answer for text in expected.contains)
        and all(
            any(ref.object_id == mid and ref.version == version for ref in actual.citations)
            for mid, version in expected.citation_versions.items()
        )
        and (
            expected.effective_update_strategy is None
            or actual.config.effective.update_strategy == expected.effective_update_strategy
        )
    )


def execute_suite(
    module: ScenarioModule,
    snapshot: ScenarioSnapshot,
    auth: C.AuthContext,
    candidate: C.AssistantConfig,
    probes: tuple[Probe, ...],
    identity: str,
) -> tuple[EngineerProbeResult, ...]:
    state = replace(snapshot, config=candidate)
    resolved = effective_config(module.package, candidate, snapshot.world.resources)
    results: list[EngineerProbeResult] = []
    for probe in probes:
        start = perf_counter()
        actual = None
        error_code = None
        outcome = "error"
        try:
            actual = module.assistant.run(
                state,
                C.TestRequestV2(query=probe.query, config_version=candidate.config_version),
                auth,
                identity + "-" + probe.id,
                operation_name="tests.create",
            ).result
            outcome = "pass" if matches(actual, probe.expected) else "fail"
        except Exception:
            # Execution faults do not become a business fail or leak private text.
            error_code = "engineer_probe_execution_failed"
        results.append(
            EngineerProbeResult(
                probe_id=probe.id,
                visibility="public" if probe.public else "hidden",
                query=probe.query,
                expected=probe.expected,
                actual=actual,
                result=outcome,
                config_hash=C.digest(resolved.effective),
                elapsed_seconds=perf_counter() - start,
                error_code=error_code,
            )
        )
    return tuple(results)


def interrupted_results(
    probes: tuple[Probe, ...], config_hash: str
) -> tuple[EngineerProbeResult, ...]:
    return tuple(
        EngineerProbeResult(
            probe_id=p.id,
            visibility="public" if p.public else "hidden",
            query=p.query,
            expected=p.expected,
            actual=None,
            result="error",
            config_hash=config_hash,
            elapsed_seconds=0,
            error_code="engineer_review_interrupted",
        )
        for p in probes
    )


def account_for_baseline_errors(
    baseline: tuple[EngineerProbeResult, ...],
    candidate: tuple[EngineerProbeResult, ...],
) -> tuple[EngineerProbeResult, ...]:
    errors = {row.probe_id for row in baseline if row.result == "error"}
    # Preserve the candidate's actual execution even when comparative
    # verification cannot finish because its baseline execution failed.
    return tuple(
        row.model_copy(
            update={
                "result": "error",
                "error_code": "engineer_baseline_execution_failed",
            }
        )
        if row.probe_id in errors and row.result != "error"
        else row
        for row in candidate
    )
