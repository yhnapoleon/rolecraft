"""Verified, versioned scenario content and disclosure projections."""

from dataclasses import dataclass, field
import json
import hashlib
import re
from pathlib import Path
from typing import Mapping

import yaml

from career_lab.contracts.v2.core import EvidenceRefV2, ProtocolError, digest, read_file
from career_lab.contracts.v2.world import (
    ScenarioBundle,
    MaterialV2,
    FactV2,
    AssistantConfig,
    RoleSpecV2,
)
from career_lab.contracts.v2.projection import project_fragments


@dataclass(frozen=True)
class MaterialMetadata:
    id: str
    version: int
    title: str
    domain: str


@dataclass(frozen=True)
class ScenarioPackage:
    root: Path
    bundle: ScenarioBundle
    content_hash: str
    materials: tuple[MaterialV2, ...]
    facts: tuple[FactV2, ...]
    rules: dict
    locale: str = "zh"
    locale_metadata: dict = field(default_factory=dict)

    def baseline(self, session_id):
        return self.bundle.baseline_config.model_copy(update={"session_id": session_id})

    def material(self, material_id, version):
        found = next(
            (m for m in self.materials if (m.id, m.version) == (material_id, version)), None
        )
        if found is None:
            raise ProtocolError("material_unavailable", status=404)
        return found

    def project(self, material_id, version, actor, as_of_seq, session_id):
        # Membership in known_materials is an additional ceiling on role projection.
        roles = {r.id: r for r in self.bundle.role_specs}
        if actor != "learner" and actor not in roles:
            raise ProtocolError("unknown_role", status=403)
        if actor in roles and material_id not in roles[actor].known_materials:
            raise ProtocolError("material_unavailable", status=404)
        material = self.material(material_id, version)
        fragments = []
        for fragment in material.fragments:
            policy, ref = fragment.disclosure, fragment.ref
            # Draft projection doesn't enforce paraphrase actors or valid_until.
            # Apply those input ceilings before invoking the shared projector.
            if policy.actors and actor not in policy.actors:
                continue
            if ref.valid_until_seq is not None and as_of_seq >= ref.valid_until_seq:
                continue
            if actor in roles:
                for fid in fragment.fact_ids:
                    override = roles[actor].disclosure_policy.get(fid)
                    if override is None:
                        continue
                    if override.mode == "never":
                        policy = override
                        break
                    if override.actors and actor not in override.actors:
                        policy = override
                        break
                    if override.mode == "paraphrase_only":
                        if (
                            policy.mode == "paraphrase_only"
                            and override.paraphrase != policy.paraphrase
                        ):
                            raise ProtocolError("disclosure_override_invalid")
                        policy = override
                    elif override.mode == "role_only" and policy.mode == "public":
                        policy = override
            if policy.mode == "never" or (policy.actors and actor not in policy.actors):
                continue
            rebound = ref.model_copy(update={"session_id": session_id})
            fragments.append(fragment.model_copy(update={"ref": rebound, "disclosure": policy}))
        return project_fragments(fragments, actor, as_of_seq)

    def visible_materials(self, versions: Mapping[str, int], actor, seq, sid, *, kb_only=False):
        kb_ids = {mid for ids in self.bundle.domains.values() for mid in ids}
        result = []
        for mid, version in sorted(versions.items()):
            if kb_only and mid not in kb_ids:
                continue
            try:
                fragments = self.project(mid, version, actor, seq, sid)
            except ProtocolError as exc:
                if exc.code != "material_unavailable":
                    raise
                continue
            if fragments:
                material = self.material(mid, version)
                result.append(
                    (
                        MaterialMetadata(
                            material.id, material.version, material.title, material.domain
                        ),
                        fragments,
                    )
                )
        return tuple(result)


def load_package(root: Path) -> ScenarioPackage:
    root = Path(root).resolve()
    try:
        raw = (root / "manifest.json").read_bytes()
        bundle = ScenarioBundle.model_validate_json(raw)
        contents = {ref.path: read_file(root, ref) for ref in bundle.files}
        needed = {
            "scenario.yaml",
            "materials.json",
            "facts.json",
            "roles.json",
            "baseline.json",
            "probes.json",
            "paths.json",
            "rubric-reference.json",
        }
        if not needed <= contents.keys():
            raise ProtocolError("incomplete_scenario_bundle")
        rules = yaml.safe_load(contents["scenario.yaml"])
        locale_data = json.loads(contents["locale.json"]) if "locale.json" in contents else {}
        locale = locale_data.get("locale", "zh")
        if rules["scenario_id"] != bundle.id or rules["revision"] != bundle.revision:
            raise ProtocolError("scenario_identity_mismatch")
        if (
            tuple(RoleSpecV2.model_validate(r) for r in json.loads(contents["roles.json"]))
            != bundle.role_specs
        ):
            raise ProtocolError("role_manifest_mismatch")
        if AssistantConfig.model_validate_json(contents["baseline.json"]) != bundle.baseline_config:
            raise ProtocolError("baseline_manifest_mismatch")
        materials = tuple(
            MaterialV2.model_validate(x) for x in json.loads(contents["materials.json"])
        )
        facts = tuple(FactV2.model_validate(x) for x in json.loads(contents["facts.json"]))
        if len({(m.id, m.version) for m in materials}) != len(materials):
            raise ProtocolError("duplicate_material")
        if len({(f.id, f.version) for f in facts}) != len(facts):
            raise ProtocolError("duplicate_fact")
        by_material = {(m.id, m.version): m for m in materials}
        by_fact = {(f.id, f.version): f for f in facts}
        for m in materials:
            path = rules["material_files"][m.id][str(m.version)]
            if path not in contents:
                raise ProtocolError("material_file_not_manifested")
            text = contents[path].decode()
            for fragment in m.fragments:
                ref = fragment.ref
                if (ref.object_id, ref.version) != (m.id, m.version) or ref.kind != "material":
                    raise ProtocolError("fragment_identity_mismatch")
                if (
                    ref.span_start is None
                    or text[ref.span_start : ref.span_end] != ref.quote
                    or fragment.text != ref.quote
                ):
                    raise ProtocolError("fragment_span_mismatch")
                if any(not any(fid == f.id for f in facts) for fid in fragment.fact_ids):
                    raise ProtocolError("unknown_fragment_fact")
        for fact in facts:
            source = fact.source
            material = by_material.get((source.object_id, source.version))
            if material is None or not any(f.ref == source for f in material.fragments):
                raise ProtocolError("fact_source_missing")
            # Every numerical/categorical fact carries its literal value in its source.
            # Semantic contradiction review remains separate from this exact check.
            if str(fact.value) not in (source.quote or ""):
                raise ProtocolError("fact_source_value_mismatch")
        initial = rules["initial_material_versions"]
        for mid, version in initial.items():
            if (mid, version) not in by_material:
                raise ProtocolError("initial_material_missing")
        for domain, mids in bundle.domains.items():
            if not mids or any(
                not any(m.id == mid and m.domain == domain for m in materials) for mid in mids
            ):
                raise ProtocolError("domain_mapping_invalid")
        for role in bundle.role_specs:
            if set(role.known_materials) - {m.id for m in materials} or set(role.known_facts) - {
                f.id for f in facts
            }:
                raise ProtocolError("role_source_missing")
        for key, value in bundle.initial_resources.items():
            fact = by_fact.get((key, 1))
            if fact is None or fact.value != value:
                raise ProtocolError("initial_resource_fact_mismatch")
        for key, value in rules["approval_limits"].items():
            if by_fact[(key + "_limit", 1)].value != value:
                raise ProtocolError("approval_fact_mismatch")
        if set(rules["work_costs"]) != {
            f.id.removeprefix("cost_") for f in facts if f.id.startswith("cost_")
        }:
            raise ProtocolError("work_fact_missing")
        for key, value in rules["work_costs"].items():
            if by_fact[("cost_" + key, 1)].value != value:
                raise ProtocolError("cost_fact_mismatch")
        if by_fact[("demand_total", 1)].value != sum(
            by_fact[(key, 1)].value for key in ("demand_faq", "demand_policy", "demand_sensitive")
        ):
            raise ProtocolError("demand_total_mismatch")
        if by_fact[("candidate_total", 1)].value != sum(
            by_fact[(key, 1)].value for key in ("new_staff", "operations_staff", "admin_staff")
        ):
            raise ProtocolError("candidate_total_mismatch")
        role_ids = {role.id for role in bundle.role_specs} | {"learner"}
        for role in bundle.role_specs:
            if set(role.disclosure_policy) - {f.id for f in facts}:
                raise ProtocolError("role_disclosure_fact_missing")
            if any(set(policy.actors) - role_ids for policy in role.disclosure_policy.values()):
                raise ProtocolError("role_disclosure_actor_unknown")
        for rule in rules.get("business_events", []):
            if any(
                (mid, version) not in by_material
                for mid, version in rule["material_updates"].items()
            ):
                raise ProtocolError("business_event_material_missing")
        probes = json.loads(contents["probes.json"])
        if any(type(probe.get("public")) is not bool for probe in probes):
            raise ProtocolError("probe_visibility_missing")
        normalized = lambda text: re.sub(r"\W", "", text).casefold()
        public_text = normalized("\n".join(contents[path].decode() for path in bundle.public_files))
        if any(
            normalized(probe["query"]) in public_text for probe in probes if not probe["public"]
        ):
            raise ProtocolError("hidden_probe_in_public_material")
        material_by_path = {rules["material_files"][m.id][str(m.version)]: m for m in materials}
        for path in bundle.public_files:
            material = material_by_path.get(path)
            if material is None or any(
                f.disclosure.mode != "public" or f.disclosure.actors for f in material.fragments
            ):
                raise ProtocolError("private_raw_file_published")
            if rules["initial_material_versions"].get(material.id) != material.version:
                raise ProtocolError("future_raw_file_published")
        if locale_data:
            from .localization import validate_metadata

            locale = validate_metadata(locale_data, bundle, facts, materials, contents)
            if rules.get("locale") != locale:
                raise ProtocolError("locale_rule_mismatch")
        if "research/public-case-records.json" in contents:
            from .case_records import (
                validate_public_cases,
                render_public_cases,
                render_case_details,
            )

            records = json.loads(contents["research/public-case-records.json"])
            validate_public_cases(
                records,
                initial,
                materials,
                {mid for mids in bundle.domains.values() for mid in mids},
                locale=locale,
            )
            actual = next((m for m in materials if m.id == "failures" and m.version == 1), None)
            if actual is None or [f.text for f in actual.fragments] != render_public_cases(
                records, locale=locale
            ):
                raise ProtocolError("public_case_render_mismatch")
            details = next(
                (m for m in materials if m.id == "trial_details" and m.version == 1), None
            )
            if details is None or [f.text for f in details.fragments] != render_case_details(
                records, locale=locale
            ):
                raise ProtocolError("public_case_details_mismatch")
        return ScenarioPackage(
            root,
            bundle,
            hashlib.sha256(raw).hexdigest(),
            materials,
            facts,
            rules,
            locale,
            locale_data,
        )
    except ProtocolError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ProtocolError("scenario_bundle_invalid") from exc
