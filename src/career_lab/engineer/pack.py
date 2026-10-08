"""Authorized, immutable handoffs. Full scenario sources stay on the trusted host."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_jsonable_python

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ref_for
from career_lab.scenarios.v2.probes import export_public_probes
from career_lab.storage.v2_lifecycle import point


class PackSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindings: C.SessionBindings
    as_of: C.VersionPoint


class PackIndex(BaseModel):
    """On-disk member index, not a new public business contract."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    kind: Literal["engineer_baseline_pack"]
    source: PackSource
    work_language: Literal["zh", "en"]
    pack: C.FileRef
    config: C.FileRef
    tests: tuple[C.FileRef, ...] = Field(min_length=1, max_length=100)
    materials: C.FileRef
    public_probes: C.FileRef
    guide: C.FileRef


def encode(value):
    return (C.canonical(to_jsonable_python(value)) + "\n").encode("utf-8")


def file_ref(name, raw):
    return C.FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest())


def handoff_guide(language):
    if language == "zh":
        text = """# 工程师基线任务包

config.json 是导出时的配置；test 文件保留各次测试自己的历史配置和原始结果。
materials.json 是获准的案例材料；public-probes.json 只含公开问题，不含标准答案。
所选测试是待调查记录，成功复现不代表回答正确或问题已修复。
复现须在可信本机使用原始运行库、当前有效凭据和匹配的已安装场景；这些不随包外发。
请由环境操作者替换下面的路径。凭据沿用 W06 私有 JSON（权限 0600），不能写到命令参数中。
"""
    else:
        text = """# Engineering baseline package

config.json is the configuration at export time; each test retains its own historical configuration and recorded result.
materials.json contains authorized cases; public-probes.json contains public questions without expected answers.
Selected tests are investigation inputs. Reproducing behavior does not prove correctness or a repair.
Run on the trusted local host with the original database, current credentials and matching installed scenario. These are not included in the package.
Ask the environment operator to supply the paths below. Credentials use the private W06 JSON format (mode 0600); keep tokens out of command arguments.
"""
    return (text + "\n```sh\ncareer-lab engineer reproduce --pack <package-directory> --database <original.db> --credentials <private.json> --scenario <installed-scenario-directory> --output <new-report-directory>\n```\n").encode("utf-8")


def capture(store, module, auth, test_ids, *, as_of=None):
    """One authorized database view; never exports a private snapshot or truth file."""
    test_ids = sorted(set(test_ids))
    if not test_ids or len(test_ids) > 100:
        raise C.ProtocolError("engineer_test_selection_required")
    if auth.actor_id != "learner":
        raise C.ProtocolError("engineer_learner_required", status=403)
    if auth.allowed_actions is not None and not {"tests.list", "objects.read", "materials.list"} <= set(auth.allowed_actions):
        raise C.ProtocolError("action_forbidden", status=403)

    def read(view):
        snapshot = module.snapshot(view)
        tests = {row["id"]: C.TestResultV2.model_validate(row) for row in
                 module.list_tests(view, C.ResourcePage(), auth).result["tests"]}
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
        materials = []
        for mid in ("failures", "trial_details"):
            version = snapshot.source_versions.get(mid)
            if version is None or (auth.allowed_objects is not None and mid not in auth.allowed_objects):
                continue
            fragments = module.package.project(mid, version, auth.actor_id, view.state.business_seq, auth.session_id)
            if fragments:
                materials.append({"id": mid, "version": version, "fragments": [
                    {"text": f.text, "ref": f.ref.model_dump(mode="json")} for f in fragments]})
        probes = [{"id": p["id"], "query": p["query"]} for p in export_public_probes(module.package)]
        files = {"config.json": encode(snapshot.config), "materials.json": encode(materials),
                 "public-probes.json": encode(probes), "README.md": handoff_guide(module.work_language)}
        test_files = []
        for i, test in enumerate(selected, 1):
            name = f"test-{i:03d}.json"
            files[name] = encode(test)
            test_files.append(file_ref(name, files[name]))
        source = {"bindings": view.bindings.model_dump(mode="json"), "as_of": point(view.state).model_dump(mode="json")}
        identity = C.digest({"source": source, "files": {name: file_ref(name, raw).sha256 for name, raw in files.items()}})
        pack = C.EngineerPack(id="engineer-" + identity, scenario=view.bindings.scenario,
            config=config_ref, failures=tuple(ref_for("test", t) for t in selected),
            public_probes=(file_ref("public-probes.json", files["public-probes.json"]),),
            requirements=("Configuration-only handoff; no code execution.",
                          "Reproduce recorded behavior before changing configuration.",
                          "Recorded behavior is not a correctness grade."))
        files["pack.json"] = encode(pack)
        files["index.json"] = encode({"schema_version": 1, "kind": "engineer_baseline_pack", "source": source,
            "work_language": module.work_language, "pack": file_ref("pack.json", files["pack.json"]),
            "config": file_ref("config.json", files["config.json"]), "tests": test_files,
            "materials": file_ref("materials.json", files["materials.json"]),
            "public_probes": file_ref("public-probes.json", files["public-probes.json"]),
            "guide": file_ref("README.md", files["README.md"])})
        return files

    return store.query(auth, read, operation="tests.list") if as_of is None else store.query_at(auth, as_of, read, operation="tests.list")


def check_directory(root, files):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != set(files):
        raise C.ProtocolError("engineer_pack_changed", status=409)
    if any((root / name).is_symlink() or not (root / name).is_file() or (root / name).read_bytes() != raw for name, raw in files.items()):
        raise C.ProtocolError("engineer_pack_changed", status=409)


def publish(root, files):
    """Build off to the side and rename once; an existing package is never overwritten."""
    root = Path(root).absolute()
    if root.exists() or root.is_symlink():
        check_directory(root, files)
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".engineer-", dir=root.parent) as temporary:
        stage = Path(temporary) / "pack"
        stage.mkdir(mode=0o700)
        for name, raw in files.items():
            path = stage / name
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            stage.rename(root)
        except OSError:
            if not root.exists():
                raise
            check_directory(root, files)


def export_pack(store, module, auth, test_ids, output):
    files = capture(store, module, auth, test_ids)
    publish(output, files)
    return {"pack_id": json.loads(files["pack.json"])["id"], "status": "exported", "tests": len(set(test_ids))}


def observed_behavior(result):
    """Compare behavior, retaining versions while excluding new execution identities."""
    value = result.model_dump(mode="json", include={"query", "status", "answer", "error_code", "citations", "config"})
    value["versions"] = result.execution.model_dump(mode="json", include={"source_versions", "indexed_versions", "used_versions"})
    return value


def reproduce_pack(store, module, auth, root, output):
    root = Path(root)
    index = PackIndex.model_validate_json((root / "index.json").read_bytes())
    module.check_bindings(index.source.bindings)
    pack = C.EngineerPack.model_validate_json(C.read_file(root, index.pack))
    if pack.config.session_id != auth.session_id:
        raise C.ProtocolError("engineer_session_mismatch", status=403)
    tests = [C.TestResultV2.model_validate_json(C.read_file(root, ref)) for ref in index.tests]
    # Hashes supplied by a caller cannot establish authenticity. Compare with
    # the original authorized records, including the exact exported file set.
    files = capture(store, module, auth, [test.id for test in tests], as_of=index.source.as_of)
    check_directory(root, files)
    store.authorize(auth, "act", "tests.create")
    results = []
    for test in tests:
        def run(view):
            snapshot = module.snapshot(view)
            request = C.TestRequestV2(query=test.query, config_version=test.config_ref.config_version)
            actual = module.assistant.run(snapshot, request, auth, "engineer-" + test.id, operation_name="tests.create").result
            for ref in actual.citations:
                module.check_evidence(view, auth, ref)
            recorded, reproduced = observed_behavior(test), observed_behavior(actual)
            return {"source_test": ref_for("test", test), "matches_record": recorded == reproduced,
                    "recorded": recorded, "reproduced": reproduced}
        results.append(store.query_at(auth, test.as_of, run, operation="tests.create"))
    matched = all(row["matches_record"] for row in results)
    report = {"pack_id": pack.id, "mode": "isolated_deterministic_reexecution", "work_language": index.work_language,
              "status": "reproduced" if matched else "behavior_changed", "correctness_assessed": False,
              "model_calls": 0, "results": results}
    publish(output, {"report.json": encode(report)})
    return {"pack_id": pack.id, "status": report["status"], "tests": len(results)}
