"""Owned bundle-language assembly; no replacement for the shared Session schema."""

import json
from pathlib import Path
from career_lab.contracts.v2 import ProtocolError, digest, Lineage
from .content import materials as canonical_materials

LOCALES = ("zh", "en")
ACCEPTED_CHINESE_COMMIT = "b821b0e67c9e5d20f386f44efb1f4a6be297e7a4"
STRUCTURE_ID = "index_scope_resource_dependency"
COMPONENT_ID = "pm_pilot_v2_family"


def require_locale(locale):
    if locale not in LOCALES:
        raise ProtocolError("unsupported_work_language")
    return locale


def locale_root(root, locale=None):
    root = Path(root)
    data = (
        json.loads((root / "locale.json").read_bytes())
        if (root / "locale.json").is_file()
        else {"locale": "zh"}
    )
    actual = require_locale(data["locale"])
    if locale is None or require_locale(locale) == actual:
        return root
    candidate = root / "locales" / locale
    if not (candidate / "locale.json").is_file():
        raise ProtocolError("locale_bundle_unavailable", status=503)
    if json.loads((candidate / "locale.json").read_bytes())["locale"] != locale:
        raise ProtocolError("locale_bundle_mismatch", status=409)
    return candidate


def canonical_facts(scenario_id="pm_pilot"):
    from .variants import material_definitions

    result = {}
    for mid, _, _, version, _, rows in material_definitions("zh", 0.35, scenario_id):
        for index, row in enumerate(rows):
            if isinstance(row, tuple):
                for fid, value, unit in row[1]:
                    result[f"{fid}@{version}"] = {
                        "id": fid,
                        "version": version,
                        "value": value,
                        "unit": unit,
                        "material_id": mid,
                        "paragraph_index": index,
                    }
    return result


def metadata(locale, materials, facts, material_files, files, min_score, *, scenario_id="pm_pilot"):
    require_locale(locale)
    canonical = canonical_facts(scenario_id)
    root_id = "pm-pilot-facts-" + digest(canonical)
    by_fact = {f"{f.id}@{f.version}": f for f in facts}
    if set(by_fact) != set(canonical):
        raise ProtocolError("locale_fact_set_mismatch")
    lineage = Lineage(
        structure_id=STRUCTURE_ID,
        fact_root_ids=(root_id,),
        component_id=COMPONENT_ID,
        derivation_ids=(ACCEPTED_CHINESE_COMMIT,),
    )
    return {
        "schema_version": 1,
        "locale": locale,
        "source_language": locale,
        "original_language": "zh",
        "translation_basis_commit": ACCEPTED_CHINESE_COMMIT,
        "canonical_scenario_id": scenario_id,
        "canonical_fact_root_id": root_id,
        "lineage": lineage.model_dump(mode="json"),
        "split": "train",
        "independent_structure_count": 1,
        "translation_adds_independent_structures": 0,
        "calibration_usage": "development work on an already-seen training fact root; not held-out evaluation",
        "retrieval_default": min_score,
        "facts": {
            key: {**value, "display_value": by_fact[key].value, "display_unit": by_fact[key].unit}
            for key, value in canonical.items()
        },
        "materials": [
            {
                "id": m.id,
                "version": m.version,
                "locale": locale,
                "canonical_record_id": f"{scenario_id}:{m.id}@{m.version}",
                "translation_group_id": f"{root_id}:{m.id}@{m.version}",
                "path": material_files[m.id][str(m.version)],
                "sha256": __import__("hashlib")
                .sha256(files[material_files[m.id][str(m.version)]])
                .hexdigest(),
            }
            for m in materials
        ],
        "reference_contract": "Offsets and source hashes belong to this locale bundle. Static fact source seq0 is an authoring placeholder; use authoritative material_activation and runtime projection.",
        "public_session_language_field": "owned assembly only; shared work_language wiring pending the coordinator input",
    }


MESSAGES = {
    "zh": {
        "synthetic": "本案例的公司与业务资料为虚构训练设定。",
        "missing_cases": "此记录尚未作为学员资料发布。",
        "cases_title": "筹备期试用问答记录",
        "case_details_title": "试用配置与完整回答",
        "policy_notice": "费用管理发布了差旅住宿政策通知，最新资料已放入工作区。",
        "demo_notice": "经理发来日程变更：内部演示改到第4天，详见新的演示安排。",
        "scope_notice": "陈敏转来销售支持组追加意向，请查看业务范围讨论的新记录。",
        "stale_warning": "来源索引版本落后，以下内容须核验当前政策。\n",
        "prohibited_topic": "该主题禁止自动回答，请向授权负责人核验。",
        "outside_scope": "该问题超出当前开放知识范围，请转人工核验。",
        "no_retrieval_hit": "未检索到可靠依据，请转人工核验。",
        "manual_verification_required": "该知识域需要人工核验，当前未作自动回答。",
        "stale_source_guard": "索引与源版本不一致，新鲜度守卫已阻止自动回答。",
        "no_fallback": "当前无法可靠自动回答，且人工兜底尚未生效。",
        "assistant_model_unavailable": "未配置模型。等待模型接入；问题与配置已保留。",
        "assistant_generation_failed": "生成失败，问题与配置已保留。",
        "tech_summary": "筹备期复现过一个培训报名问法：公司培训我已提交报名是不是就能去听课。匹配阈值0.35时未命中，0.2时返回FAQ中的培训报名段；无关问题仍未命中。这只是一次局部对照，未完成统一校准。",
        "tech_register_summary": "技术诊断保存了培训报名原问法、两档阈值和无关问题对照；内部登记号不对外转述。",
        "path_question": "住宿报销上限是多少？",
        "path_reason": "根据候选用户材料和方案工作项申请",
    }
}


def text(package_or_locale, key):
    locale = (
        package_or_locale
        if isinstance(package_or_locale, str)
        else getattr(package_or_locale, "locale", "zh")
    )
    require_locale(locale)
    if locale == "en":
        from .localization_en import MESSAGES_EN

        return MESSAGES_EN[key]
    return MESSAGES["zh"][key]


def validate_metadata(data, bundle, facts, materials, contents):
    from hashlib import sha256

    locale = require_locale(data["locale"])
    canonical = canonical_facts(bundle.id)
    if (
        data["canonical_scenario_id"] != bundle.id
        or data["split"] != bundle.split
        or data["canonical_fact_root_id"] != "pm-pilot-facts-" + digest(canonical)
    ):
        raise ProtocolError("locale_canonical_identity_mismatch")
    lineage = Lineage.model_validate(data["lineage"])
    if (
        lineage.structure_id != bundle.structure_id
        or lineage.component_id != COMPONENT_ID
        or lineage.fact_root_ids != (data["canonical_fact_root_id"],)
    ):
        raise ProtocolError("locale_lineage_mismatch")
    mapping = data["facts"]
    actual = {f"{f.id}@{f.version}": f for f in facts}
    if set(mapping) != set(canonical) or set(actual) != set(canonical):
        raise ProtocolError("locale_fact_set_mismatch")
    for key, expected in canonical.items():
        entry = mapping[key]
        fact = actual[key]
        if any(entry.get(k) != v for k, v in expected.items()):
            raise ProtocolError("locale_fact_identity_mismatch")
        if fact.value != entry["display_value"] or fact.unit != entry["display_unit"]:
            raise ProtocolError("locale_fact_display_mismatch")
        if isinstance(expected["value"], (int, float)) and fact.value != expected["value"]:
            raise ProtocolError("locale_numeric_fact_mismatch")
        if locale == "zh" and (fact.value, fact.unit) != (expected["value"], expected["unit"]):
            raise ProtocolError("locale_chinese_baseline_mismatch")
    listed = {(r["id"], r["version"]): r for r in data["materials"]}
    if set(listed) != {(m.id, m.version) for m in materials}:
        raise ProtocolError("locale_material_set_mismatch")
    for (mid, version), row in listed.items():
        if row["locale"] != locale or row["sha256"] != sha256(contents[row["path"]]).hexdigest():
            raise ProtocolError("locale_material_hash_mismatch")
        if row["translation_group_id"] != f"{data['canonical_fact_root_id']}:{mid}@{version}":
            raise ProtocolError("locale_translation_group_mismatch")
    if data["retrieval_default"] != bundle.baseline_config.min_score:
        raise ProtocolError("locale_retrieval_default_mismatch")
    return locale


def runtime_source_files(repo, locale):
    """Hash all shared/locale-consumed owned Python; isolate English-only work.

    A shared caller change is still pinned. English-only modules are loaded only
    through the en branch, never by a zh request or a zh renderer.
    """
    from hashlib import sha256

    require_locale(locale)
    result = {}
    for folder in (repo / "src/career_lab/assistant/v2", repo / "src/career_lab/scenarios/v2"):
        for path in folder.glob("*.py"):
            english_only = path.name.endswith("_en.py") or path.name == "english.py"
            if locale == "zh" and english_only:
                continue
            result[path.relative_to(repo).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return result
