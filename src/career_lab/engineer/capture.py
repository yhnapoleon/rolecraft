"""Capture one authorized database view and construct its verifiable data identity."""

from collections.abc import Sequence
from typing import Any

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.scenarios.v2.module import ScenarioModule, ref_for
from career_lab.scenarios.v2.probes import export_public_probes
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import TransactionView, V2Store

from .files import RetainedDocumentation, encode, file_ref
from .guide import handoff_guide
from .identity import source_version

LEGACY_REQUIREMENTS = (
    "Configuration-only handoff; no code execution.",
    "Reproduce recorded behavior before changing configuration.",
    "Recorded behavior is not a correctness grade.",
)


def capture(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    test_ids: Sequence[str],
    *,
    as_of: C.VersionPoint | None = None,
    retained: RetainedDocumentation | None = None,
) -> dict[str, bytes]:
    """One authorized database view; never exports a private snapshot or truth file."""
    test_ids = sorted(set(test_ids))
    if not test_ids or len(test_ids) > 100:
        raise C.ProtocolError("engineer_test_selection_required")
    if auth.actor_id != "learner":
        raise C.ProtocolError("engineer_learner_required", status=403)
    if auth.allowed_actions is not None and not {
        "tests.list",
        "objects.read",
        "materials.list",
    } <= set(auth.allowed_actions):
        raise C.ProtocolError("action_forbidden", status=403)

    def read(view: TransactionView) -> dict[str, bytes]:
        return capture_view(view, module, auth, test_ids, retained)

    return (
        store.query(auth, read, operation="tests.list")
        if as_of is None
        else store.query_at(auth, as_of, read, operation="tests.list")
    )


def capture_view(
    view: TransactionView,
    module: ScenarioModule,
    auth: C.AuthContext,
    test_ids: list[str],
    retained: RetainedDocumentation | None,
) -> dict[str, bytes]:
    snapshot = module.snapshot(view)
    tests = {
        row["id"]: C.TestResultV2.model_validate(row)
        for row in module.list_tests(view, C.ResourcePage(), auth).result["tests"]
    }
    if any(key not in tests for key in test_ids):
        raise C.ProtocolError("engineer_test_unavailable", status=404)
    selected = [tests[key] for key in test_ids]
    # The normal test list already checks its config and citation scope.
    for test in selected:
        for ref in (test.config_ref, *test.citations):
            if not view.reference_allowed(ref):
                raise C.ProtocolError("engineer_source_unavailable", status=404)
    config_ref = ref_for("config", snapshot.config)
    if not view.reference_allowed(config_ref):
        raise C.ProtocolError("engineer_config_unavailable", status=404)
    return package_files(view, module, auth, snapshot, selected, config_ref, retained)


def case_materials(
    view: TransactionView,
    module: ScenarioModule,
    auth: C.AuthContext,
    snapshot: ScenarioSnapshot,
) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    # The scenario loader identifies this pair as authored public failure cases.
    # Other investigation-domain material is outside the engineering handoff.
    material_ids = ("failures", "trial_details")
    for mid in material_ids:
        version = snapshot.source_versions.get(mid)
        if version is None or (
            auth.allowed_objects is not None and mid not in auth.allowed_objects
        ):
            continue
        fragments = module.package.project(
            mid, version, auth.actor_id, view.state.business_seq, auth.session_id
        )
        if fragments:
            materials.append(
                {
                    "id": mid,
                    "version": version,
                    "fragments": [
                        {"text": f.text, "ref": f.ref.model_dump(mode="json")} for f in fragments
                    ],
                }
            )
    return materials


def package_files(
    view: TransactionView,
    module: ScenarioModule,
    auth: C.AuthContext,
    snapshot: ScenarioSnapshot,
    selected: list[C.TestResultV2],
    config_ref: C.ObjectRef,
    retained: RetainedDocumentation | None,
) -> dict[str, bytes]:
    schema_version = retained[0].schema_version if retained else 2
    probes = [{"id": p["id"], "query": p["query"]} for p in export_public_probes(module.package)]
    files: dict[str, bytes] = {
        "config.json": encode(snapshot.config),
        "materials.json": encode(case_materials(view, module, auth, snapshot)),
        "public-probes.json": encode(probes),
        "README.md": retained[2] if retained else handoff_guide(module.work_language),
    }
    test_files: list[C.FileRef] = []
    for i, test in enumerate(selected, 1):
        name = f"test-{i:03d}.json"
        files[name] = encode(test)
        test_files.append(file_ref(name, files[name]))
    source = {
        "bindings": view.bindings.model_dump(mode="json"),
        "as_of": point(view.state).model_dump(mode="json"),
    }
    identity = C.digest(
        {
            "source": source,
            "files": {
                name: file_ref(name, raw).sha256
                for name, raw in files.items()
                if schema_version == 1 or name != "README.md"
            },
        }
    )
    pack = C.EngineerPack(
        id="engineer-" + identity,
        scenario=view.bindings.scenario,
        config=config_ref,
        failures=tuple(ref_for("test", t) for t in selected),
        public_probes=(file_ref("public-probes.json", files["public-probes.json"]),),
        requirements=LEGACY_REQUIREMENTS
        if schema_version == 1
        else retained[1].requirements
        if retained
        else (
            "Configuration-only handoff; no code execution.",
            "Re-run recorded behavior before evaluating a configuration change.",
            "Recorded behavior is not a correctness grade.",
        ),
    )
    files["pack.json"] = encode(pack)
    add_index(files, source, module.work_language, test_files, retained)
    return files


def add_index(
    files: dict[str, bytes],
    source: dict[str, Any],
    language: str,
    test_files: list[C.FileRef],
    retained: RetainedDocumentation | None,
) -> None:
    index = {
        "schema_version": retained[0].schema_version if retained else 2,
        "kind": "engineer_baseline_pack",
        "source": source,
        "work_language": language,
        "pack": file_ref("pack.json", files["pack.json"]),
        "config": file_ref("config.json", files["config.json"]),
        "tests": test_files,
        "materials": file_ref("materials.json", files["materials.json"]),
        "public_probes": file_ref("public-probes.json", files["public-probes.json"]),
        "guide": file_ref("README.md", files["README.md"]),
    }
    if not retained or retained[0].schema_version == 2:
        index.update(
            tool_versions=retained[0].tool_versions
            if retained
            else {"career-lab-engineer": source_version()},
            template_version=retained[0].template_version if retained else "2",
        )
    files["index.json"] = encode(index)
