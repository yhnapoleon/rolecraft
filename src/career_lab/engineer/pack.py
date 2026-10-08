"""Authorized task packages and isolated execution of their original tests."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule, ref_for
from career_lab.storage.v2_store import TransactionView, V2Store

from .capture import capture
from .files import check_directory, encode, publish, retained_documentation


def export_pack(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    test_ids: Sequence[str],
    output: Path,
) -> dict[str, Any]:
    files = capture(
        store,
        module,
        auth,
        test_ids,
        retained=retained_documentation(Path(output)) if Path(output).exists() else None,
    )
    publish(output, files)
    return {
        "pack_id": json.loads(files["pack.json"])["id"],
        "status": "exported",
        "tests": len(set(test_ids)),
    }


def observed_behavior(result: C.TestResultV2) -> dict[str, Any]:
    """Compare behavior, retaining versions while excluding new execution identities."""
    value = result.model_dump(
        mode="json", include={"query", "status", "answer", "error_code", "citations", "config"}
    )
    value["versions"] = result.execution.model_dump(
        mode="json", include={"source_versions", "indexed_versions", "used_versions"}
    )
    return value


def reproduce_test(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    test: C.TestResultV2,
) -> dict[str, Any]:
    def run(view: TransactionView) -> dict[str, Any]:
        snapshot = module.snapshot(view)
        request = C.TestRequestV2(query=test.query, config_version=test.config_ref.config_version)
        actual = module.assistant.run(
            snapshot, request, auth, "engineer-" + test.id, operation_name="tests.create"
        ).result
        for ref in actual.citations:
            module.check_evidence(view, auth, ref)
        recorded, reproduced = observed_behavior(test), observed_behavior(actual)
        return {
            "source_test": ref_for("test", test),
            "matches_record": recorded == reproduced,
            "recorded": recorded,
            "reproduced": reproduced,
            "execution": actual.execution.model_dump(
                mode="json", include={"attempts", "cost_complete"}
            ),
        }

    return store.query_at(auth, test.as_of, run, operation="tests.create")


def execution_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    usage_complete = all(row["execution"]["cost_complete"] for row in results)
    model_calls = (
        sum(len(row["execution"]["attempts"]) for row in results) if usage_complete else None
    )
    mode = (
        "isolated_reexecution_usage_unknown"
        if model_calls is None
        else (
            "isolated_reexecution_with_model_calls"
            if model_calls
            else "isolated_reexecution_without_model_calls"
        )
    )
    return {"mode": mode, "model_calls": model_calls, "usage_complete": usage_complete}


def reproduce_pack(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    root = Path(root)
    retained = retained_documentation(root)
    index, pack, _ = retained
    module.check_bindings(index.source.bindings)
    if pack.config.session_id != auth.session_id:
        raise C.ProtocolError("engineer_session_mismatch", status=403)
    tests = [C.TestResultV2.model_validate_json(C.read_file(root, ref)) for ref in index.tests]
    # Hashes supplied by a caller cannot establish authenticity. Compare with
    # the original authorized records, including the exact exported file set.
    files = capture(
        store,
        module,
        auth,
        [test.id for test in tests],
        as_of=index.source.as_of,
        retained=retained,
    )
    check_directory(root, files)
    store.authorize(auth, "act", "tests.create")
    results = [reproduce_test(store, module, auth, test) for test in tests]
    matched = all(row["matches_record"] for row in results)
    report = {
        "schema_version": 1,
        "pack_id": pack.id,
        "executor": auth.executor,
        "source": index.source,
        **execution_summary(results),
        "work_language": index.work_language,
        "status": "reproduced" if matched else "behavior_changed",
        "correctness_assessed": False,
        "results": results,
    }
    publish(output, {"report.json": encode(report)})
    return {"pack_id": pack.id, "status": report["status"], "tests": len(results)}
