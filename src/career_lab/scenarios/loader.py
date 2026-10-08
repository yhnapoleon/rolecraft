import hashlib
import json
from pathlib import Path, PureWindowsPath

import yaml
from pydantic import ValidationError

from career_lab.contracts.scenario import RubricSpec, ScenarioSpec, ValidationIssue


class ScenarioLoadError(ValueError):
    """Invalid or modified scenario bundle; safe for CLI error reporting."""


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ScenarioLoadError(f"non-string or duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if PureWindowsPath(relative).drive or not path.is_relative_to(root) or path == root:
        raise ScenarioLoadError(f"path escapes scenario bundle: {relative}")
    return path


def _yaml(path: Path) -> dict:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ScenarioLoadError(f"expected YAML mapping: {path.name}")
    return data


def validate_scenario(spec: ScenarioSpec) -> list[ValidationIssue]:
    """Validate cross-references; filesystem and hash checks belong to load_scenario."""
    issues: list[ValidationIssue] = []

    def issue(code: str, location: str, message: str):
        issues.append(ValidationIssue(code=code, location=location, message=message))

    for name in ("roles", "facts", "event_rules", "domains", "work_items"):
        ids = [x.id for x in getattr(spec, name)]
        if len(ids) != len(set(ids)):
            issue("duplicate_id", name, "IDs must be unique within a collection")
    roles = {r.id for r in spec.roles} | {"learner"}
    materials = {(m.id, m.version): m for m in spec.materials}
    if len(materials) != len(spec.materials):
        issue("duplicate_material", "materials", "material id/version must be unique")
    events = {e.id: e for e in spec.event_rules}
    brief = materials.get((spec.brief_material_id, 1))
    if not brief or "learner" not in brief.visible_to or brief.available_after_event:
        issue("missing_brief", "brief_material_id", "learner must see the initial brief")

    for collection in (spec.materials, spec.facts, spec.event_rules):
        for item in collection:
            if set(item.visible_to) - roles:
                issue("unknown_role", item.id, "visibility references unknown roles")
    for fact in spec.facts:
        source = materials.get((fact.material_id, fact.material_version))
        if source is None:
            issue("missing_fact_source", fact.id, "fact source does not exist")
        elif source.available_after_event:
            issue("future_fact", fact.id, "initial facts cannot cite future materials")
        elif not set(fact.visible_to).issubset(source.visible_to):
            issue(
                "inaccessible_fact_source",
                fact.id,
                "fact recipients must be able to read its source",
            )
    initial_ids = [m.id for m in spec.materials if m.available_after_event is None]
    if len(initial_ids) != len(set(initial_ids)):
        issue("ambiguous_initial_version", "materials", "one initial version per material required")
    for material in spec.materials:
        if material.available_after_event:
            event = events.get(material.available_after_event)
            if not event or not any(
                v.material_id == material.id and v.version == material.version
                for v in event.effects.material_versions
            ):
                issue(
                    "missing_activation", material.id, "future material needs matching event effect"
                )
    for event in spec.event_rules:
        if event.trigger.kind == "approved_request" and event.trigger.authorized_role not in {
            r.id for r in spec.roles
        }:
            issue("unknown_approver", event.id, "approval role does not exist")
        material_ids = [ref.material_id for ref in event.effects.material_versions]
        if len(material_ids) != len(set(material_ids)):
            issue(
                "ambiguous_material_effect",
                event.id,
                "one event can activate only one version per material",
            )
        for ref in event.effects.material_versions:
            material = materials.get((ref.material_id, ref.version))
            if material is None or material.available_after_event != event.id:
                issue(
                    "invalid_material_effect",
                    event.id,
                    "event must activate its declared material version",
                )
    dimensions = {d.id for d in spec.rubric.dimensions}
    if (
        len(dimensions) != len(spec.rubric.dimensions)
        or sum(d.weight for d in spec.rubric.dimensions) != 100
    ):
        issue("invalid_dimensions", "rubric", "unique dimensions must have total weight 100")
    criteria = [c.id for c in spec.rubric.criteria]
    if len(criteria) != len(set(criteria)):
        issue("duplicate_criterion", "rubric", "criterion IDs must be unique")
    for criterion in spec.rubric.criteria:
        if criterion.dimension not in dimensions:
            issue("unknown_dimension", criterion.id, "criterion dimension does not exist")
    if dimensions - {c.dimension for c in spec.rubric.criteria}:
        issue("empty_dimension", "rubric", "every dimension requires criteria")
    realtime = next((w for w in spec.work_items if w.id == "realtime_sync"), None)
    if not realtime or realtime.dev_days != spec.constraints.realtime_sync_days:
        issue("inconsistent_cost", "work_items", "realtime work cost must match constraints")
    facts = {f.id: f for f in spec.facts}
    for name in ("capacity", "dev_days", "realtime_sync_days", "index_delay_hours", "deadline_day"):
        fact = facts.get(name)
        if (
            fact is None
            or type(fact.value) is not int
            or fact.value != getattr(spec.constraints, name)
        ):
            issue(
                "inconsistent_fact",
                name,
                "required numeric fact must match enforced initial constraint",
            )
    if spec.constraints.minimum_participants > spec.constraints.capacity:
        issue(
            "impossible_participant_bounds",
            "constraints",
            "minimum participants exceeds initial capacity",
        )
    return issues


def load_scenario(path: Path) -> ScenarioSpec:
    """Load and verify a frozen scenario.yaml/rubric/materials/manifest bundle.

    Full ScenarioSpec is world-private. Never expose it directly to an actor or API.
    Task 2 supplies role/time projections before it is used in a live session.
    """
    path = Path(path).resolve()
    root = path.parent
    try:
        data = _yaml(path)
        rubric_path = _inside(root, data.pop("rubric_path"))
        rubric = RubricSpec.model_validate(_yaml(rubric_path))
        spec = ScenarioSpec.model_validate({**data, "rubric": rubric})
        loaded = []
        files = {
            path.relative_to(root).as_posix(): path.read_bytes(),
            rubric_path.relative_to(root).as_posix(): rubric_path.read_bytes(),
        }
        for material in spec.materials:
            source = _inside(root, material.path)
            raw = source.read_bytes()
            text = raw.decode("utf-8")
            if not text.strip():
                raise ScenarioLoadError(f"empty material: {material.path}")
            relative = source.relative_to(root).as_posix()
            if relative in files:
                raise ScenarioLoadError(f"duplicate bundle file: {relative}")
            files[relative] = raw
            loaded.append(
                material.model_copy(
                    update={"content": text, "content_hash": hashlib.sha256(raw).hexdigest()}
                )
            )
        hashes = {key: hashlib.sha256(raw).hexdigest() for key, raw in sorted(files.items())}
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest != {"scenario_id": spec.id, "version": spec.version, "files": hashes}:
            raise ScenarioLoadError(
                "bundle hash/identity mismatch; publish changes as a new version"
            )
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        spec = spec.model_copy(update={"materials": tuple(loaded), "content_hash": digest})
        issues = validate_scenario(spec)
        if issues:
            raise ScenarioLoadError(
                "; ".join(f"{i.code}: {i.location}: {i.message}" for i in issues)
            )
        return spec
    except ScenarioLoadError:
        raise
    except (
        OSError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise ScenarioLoadError(f"cannot load {path.name}: {exc}") from exc
