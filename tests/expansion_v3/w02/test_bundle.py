import hashlib, json, shutil
from pathlib import Path
import pytest
from career_lab.contracts.v2.core import ProtocolError
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.seed import build_seed
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.runtime.model_adapter import LocalModel
from .conftest import auth, command


def test_bundle_manifest_content_and_reproducibility(package, tmp_path):
    records = json.loads((package.root / "research/public-case-records.json").read_text())
    replica = load_package(build_seed(tmp_path / "replica", records))
    from career_lab.scenarios.v2.release import business_metadata, content_files

    assert content_files(replica) == content_files(package)
    assert business_metadata(replica.bundle.model_dump(mode="json")) == business_metadata(
        package.bundle.model_dump(mode="json")
    )
    assert len(package.facts) == 50
    assert len(package.material("faq", 1).fragments) == 9
    assert len(records["records"]) == 12
    assert (
        len(package.material("policy", 1).fragments)
        == len(package.material("policy", 2).fragments)
        == 3
    )
    assert package.material("meal", 1).version == 1 and package.material("leave", 1).version == 1
    assert set(f.path for f in package.bundle.files) == set(package.bundle.public_files) | set(
        package.bundle.private_files
    )
    assert "probes.json" in package.bundle.private_files
    assert "materials/policy-v2.md" in package.bundle.private_files
    with pytest.raises(ValueError, match="overwrite"):
        build_seed(tmp_path / "replica")


def test_hash_and_path_tampering_rejected(package, tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(package.root, root)
    (root / "materials/faq-v1.md").write_text("tampered")
    with pytest.raises(ProtocolError, match="file hash mismatch"):
        load_package(root)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"][0]["path"] = "../escape"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ProtocolError, match="scenario bundle invalid"):
        load_package(root)


def reseal(root, path, transform):
    target = root / path
    data = json.loads(target.read_text())
    transform(data)
    target.write_text(json.dumps(data, ensure_ascii=False))
    manifest = json.loads((root / "manifest.json").read_text())
    for ref in manifest["files"]:
        if ref["path"] == path:
            ref["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_fact_contradiction_detected_even_after_hash_reseal(package, tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(package.root, root)
    reseal(root, "facts.json", lambda data: data[0].update(value=999))
    with pytest.raises(ProtocolError, match="fact source value mismatch"):
        load_package(root)


def test_roles_get_only_authorized_paraphrase_and_no_never(package, engine):
    snapshot = engine.initial("session")
    tech = package.project("tech_private", 1, "tech_lead", 0, "session")
    assert tech and all("局部对照" in f.text for f in tech)
    assert all(f.ref.quote is None and f.ref.span_start is None for f in tech)
    for actor in ("learner", "supervisor", "business_lead"):
        assert "tech_private" not in {
            m.id
            for m, _ in package.visible_materials(snapshot.source_versions, actor, 0, "session")
        }
    for actor in ("learner", "supervisor", "tech_lead", "business_lead"):
        projection = str(package.visible_materials(snapshot.source_versions, actor, 0, "session"))
        assert "NEVER_W02_7C9E" not in projection
        assert "legacy_connector_unstable" not in projection
    with pytest.raises(ProtocolError):
        engine.plan(
            snapshot,
            command(
                snapshot,
                "read_material",
                "private",
                material={
                    "session_id": "session",
                    "kind": "material",
                    "object_id": "world_private",
                    "version": 1,
                },
            ),
            auth(),
        )


def test_material_before_activation_is_not_readable(engine):
    s = engine.initial("session")
    with pytest.raises(ProtocolError, match="material unavailable"):
        engine.plan(
            s,
            command(
                s,
                "read_material",
                "future",
                material={
                    "session_id": "session",
                    "kind": "material",
                    "object_id": "policy",
                    "version": 2,
                },
            ),
            auth(),
        )
