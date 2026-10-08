"""Mandatory zh/en reporting; no claim that synthetic coverage proves quality."""

from collections import Counter
import hashlib
from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from .metrics import summarize, paired_cluster_delta

REQUIRED = ("zh", "en")


def validate_translation_index(value, entries):
    if value.get("protocol") != "w07-translation-metadata-v1" or not isinstance(
        value.get("pairs"), list
    ):
        raise ProtocolError("translation_metadata_protocol_invalid")
    by_id = {e.record_id: e for e in entries}
    seen = set()
    try:
        for pair in value["pairs"]:
            if not pair["id"] or pair["id"] in seen:
                raise ProtocolError("translation_pair_identity_invalid")
            seen.add(pair["id"])
            a, b = pair["original"], pair["translated"]
            if a["record_id"] == b["record_id"] or {a["language"], b["language"]} != set(REQUIRED):
                raise ProtocolError("translation_language_pair_invalid")
            x, y = by_id[a["record_id"]], by_id[b["record_id"]]
            if x.split != y.split or x.split != pair["split"]:
                raise ProtocolError("translation_cross_split")
            if (
                x.structure_id != y.structure_id
                or x.structure_id != pair["structure_id"]
                or x.component_id != y.component_id
            ):
                raise ProtocolError("translation_causal_group_mismatch")
            if (
                pair["quality_verified"] is not False
                or pair["semantic_translation_review"] != "pending"
            ):
                raise ProtocolError("unapproved_translation_quality_claim")
    except (KeyError, TypeError) as exc:
        raise ProtocolError("translation_metadata_invalid") from exc
    return value


def validate_translation_member(record, pairs):
    for pair in pairs:
        for side in ["original", "translated"]:
            member = pair[side]
            if member["record_id"] != record.record_id:
                continue
            expected = {
                "record_id": record.record_id,
                "language": record.language,
                "input_hash": record.input_hash,
                "lineage_hash": digest(record.lineage),
            }
            if member != expected:
                raise ProtocolError("translation_record_binding_mismatch")
            line = record.lineage
            if (
                line.structure_id != pair["structure_id"]
                or line.component_id != pair["component_id"]
                or set(line.fact_root_ids) != set(pair["fact_root_ids"])
                or pair["id"] not in line.derivation_ids
            ):
                raise ProtocolError("translation_lineage_binding_mismatch")
            if side == "translated" and pair["original"]["record_id"] not in line.source_record_ids:
                raise ProtocolError("translation_derivation_link_required")
            anchor = pair[side + "_anchor"]
            file = FileRef.model_validate(anchor["file"])
            if file not in record.provenance.actual_sources:
                raise ProtocolError("translation_source_not_in_provenance")
            path = tuple(anchor["text_path"])
            allowed = (
                len(path) == 4
                and path[:2] == ("evidence", "candidate_evidence")
                and type(path[2]) is int
                and path[3] == "text"
            ) or path == ("evidence", "claim")
            allowed = allowed or (
                len(path) == 4
                and path[0] in {"steps", "observed_steps"}
                and type(path[1]) is int
                and path[2] == "observations"
                and type(path[3]) is int
            )
            if not allowed:
                raise ProtocolError("translation_anchor_path_not_allowed")
            text = record.model_input.model_dump(mode="json")
            try:
                for key in path:
                    if isinstance(key, int) and key < 0:
                        raise ValueError("negative index")
                    text = text[key]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProtocolError("translation_anchor_path_invalid") from exc
            if (
                not isinstance(text, str)
                or hashlib.sha256(text.encode()).hexdigest() != anchor["quote_sha256"]
            ):
                raise ProtocolError("translation_quote_hash_mismatch")
            start, end = anchor["span_start"], anchor["span_end"]
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end - start != len(text)
            ):
                raise ProtocolError("translation_span_invalid")


def bilingual_report(train, dev, evaluations, training_reports, data_scope, task):
    train = list(train)
    dev = list(dev)
    pairs = data_scope.get("translation_pairs", [])
    lookup = {r.record_id: r for r in train + dev}
    result = {
        "required_languages": list(REQUIRED),
        "training_language_combination": dict(Counter(r.language for r in train)),
        "evaluation_split": "dev",
        "quality_validated": False,
        "formal_bilingual_evaluation_complete": False,
        "scope": "synthetic_mechanical_only"
        if data_scope["fixture"]
        else "development_unconfirmed",
        "languages": {},
        "unknown_language_record_ids": [
            r.record_id for r in train + dev if r.language not in REQUIRED
        ],
        "translation_provenance_status": data_scope.get("translation_provenance_status", "missing"),
        "remaining": [
            "real per-language labels/model evaluation",
            "registered held-out bilingual structures",
            "normal Chinese and English product QA",
        ],
    }
    for lang in REQUIRED:
        tr = [r for r in train if r.language == lang]
        dv = [r for r in dev if r.language == lang]
        out = {
            "data_status": "present" if dv else "blocked_missing_language_data",
            "quality_status": "not_validated",
            "train_records": len(tr),
            "dev_records": len(dv),
            "sources": dict(Counter(r.bucket for r in dv)),
            "label_tiers": dict(Counter(r.annotation.label_tier for r in dv)),
            "structures": len({r.structure_id for r in dv}),
            "records": [
                {
                    "record_id": r.record_id,
                    "input_hash": r.annotation.input_hash,
                    "structure_id": r.structure_id,
                    "component_id": r.component_id,
                }
                for r in dv
            ],
            "models": {},
        }
        for name, evaluation in evaluations.items():
            rows = [r for r in evaluation["rows"] if r["language"] == lang]
            fit = training_reports.get(name, {})
            ids = fit.get("train_ids")
            out["models"][name] = {
                "metrics": summarize(rows, task) if rows else None,
                "evaluation_status": "computed_fixture_only"
                if rows and data_scope["fixture"]
                else "computed_dev_only"
                if rows
                else "not_run_no_language_rows",
                "actual_fit_records": sum(
                    lookup[rid].language == lang for rid in ids if rid in lookup
                )
                if ids is not None
                else None,
                "inference_seconds": sum(r.get("latency_seconds", 0.0) for r in rows)
                if rows
                else None,
                "provider_cost": None,
                "training_cost_allocation": "not attributed across languages",
                "capacity_exclusions": [
                    e
                    for e in fit.get("excluded_records", [])
                    if e.get("record_id") in lookup and lookup[e["record_id"]].language == lang
                ],
            }
        result["languages"][lang] = out
    result["paired_model_comparisons"] = {}
    if "linear" in evaluations:
        for lang in REQUIRED:
            base = [r for r in evaluations["linear"]["rows"] if r["language"] == lang]
            result["paired_model_comparisons"][lang] = {
                name: {
                    "joint": paired_cluster_delta(
                        base,
                        [r for r in value["rows"] if r["language"] == lang],
                        metric="joint_correct",
                    ),
                    "label": paired_cluster_delta(
                        base,
                        [r for r in value["rows"] if r["language"] == lang],
                        metric="label_correct",
                    ),
                }
                for name, value in evaluations.items()
                if name != "linear"
            }
    dev_ids = {r.record_id for r in dev}
    aligned = [
        p
        for p in pairs
        if p["original"]["record_id"] in dev_ids and p["translated"]["record_id"] in dev_ids
    ]
    result["cross_language_pairs"] = {
        "count": len(aligned),
        "independent_components": len({p["component_id"] for p in aligned}),
        "unpaired_dev_record_ids": sorted(
            dev_ids - {m["record_id"] for p in aligned for m in [p["original"], p["translated"]]}
        ),
        "models": {},
    }
    for name, evaluation in evaluations.items():
        pred = {r["record_id"]: r["prediction"] for r in evaluation["predictions"]}
        comparisons = []
        for pair in aligned:
            a, b = pair["original"], pair["translated"]
            pa, pb = pred.get(a["record_id"]), pred.get(b["record_id"])
            ok = pa and pb and pa.get("status") == "ok" and pb.get("status") == "ok"
            comparisons.append(
                {
                    "pair_id": pair["id"],
                    "original": a,
                    "translated": b,
                    "label_agreement": pa["label"] == pb["label"] if ok else None,
                    "evidence_agreement": None,
                    "evidence_alignment_status": "blocked_candidate_level_translation_alignment_not_frozen",
                    "semantic_translation_review": pair["semantic_translation_review"],
                    "agreement_is_not_correctness": True,
                }
            )
        result["cross_language_pairs"]["models"][name] = comparisons
    return result
