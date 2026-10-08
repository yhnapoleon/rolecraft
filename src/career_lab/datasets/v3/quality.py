"""Lineage, partition, provenance and input-isolation checks for W07."""

from collections import Counter, defaultdict
import re
import unicodedata

from career_lab.contracts.v2.core import ProtocolError, canonical
from career_lab.contracts.v2.data import DatasetRecordV2, AnnotationV2
from .common import check_payload


class QualityError(ProtocolError):
    def __init__(self, report):
        self.report = report
        super().__init__("dataset_quality_failed")


def fixture_record(record):
    return (
        record.bucket == "fixture"
        or "fixture:not-business-run" in record.provenance.transformations
    )


def input_signature(record):
    """Fingerprint semantic input, excluding JSON boilerplate and source identifiers."""
    value = record.model_input.model_dump(mode="json")

    def normalize(text):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text))).casefold()

    if record.family in {"relation", "criterion"}:
        p = value["evidence"]
        parts = [p["claim"], p["purpose"], p.get("criterion") or "", canonical(p["rule_context"])]
        parts.extend(sorted(c["text"] for c in p["candidate_evidence"]))
    elif record.family == "trajectory":
        parts = [value["task"], value["question"]]
        parts.extend(
            canonical(
                {"action": x["action"], "observations": x["observations"], "outcome": x["outcome"]}
            )
            for x in value["steps"]
        )
    else:
        parts = [value["task"], value["question"]]
        parts.extend(
            canonical({"action": x["action"], "observations": x["observations"]})
            for x in value["observed_steps"]
        )
        parts.extend(
            sorted(
                canonical({"tool": x["tool"], "arguments": x["arguments"], "purpose": x["purpose"]})
                for x in value["candidates"]
            )
        )
    return "\x1e".join(normalize(x) for x in parts)


def duplicate_pairs(rows, signatures, threshold):
    """Exact char-5-shingle Jaccard, using bitsets instead of O(L²) matching.

    Still checks every same-family cross-split pair; no approximate LSH misses.
    This screens lexical copies only. Causal/translation grouping is separate.
    """
    vocabulary = {}
    masks = {}
    sizes = {}
    for rid, text in signatures.items():
        shingles = {text[i : i + 5] for i in range(max(1, len(text) - 4))}
        mask = 0
        for token in shingles:
            if token not in vocabulary:
                vocabulary[token] = len(vocabulary)
            mask |= 1 << vocabulary[token]
        masks[rid] = mask
        sizes[rid] = len(shingles)
    for index, a in enumerate(rows):
        for b in rows[index + 1 :]:
            if a.split == b.split or a.family != b.family:
                continue
            left, right = signatures[a.record_id], signatures[b.record_id]
            if left == right:
                yield {
                    "code": "duplicate_input_cross_split",
                    "record_ids": [a.record_id, b.record_id],
                }
                continue
            n, m = sizes[a.record_id], sizes[b.record_id]
            if min(n, m) / max(n, m) < threshold:
                continue
            intersection = (masks[a.record_id] & masks[b.record_id]).bit_count()
            score = intersection / (n + m - intersection)
            if score >= threshold:
                yield {
                    "code": "near_duplicate_cross_split",
                    "record_ids": [a.record_id, b.record_id],
                    "similarity": score,
                }


def audit_records(records, *, annotations=None, near_duplicate_threshold=0.94):
    """Reject connected leakage, including indirect roots/derivations and all families."""
    if not 0 < near_duplicate_threshold <= 1:
        raise ValueError("near duplicate threshold must be in (0, 1]")
    rows = [
        DatasetRecordV2.model_validate(r.model_dump(mode="json") if hasattr(r, "model_dump") else r)
        for r in records
    ]
    errors, warnings = [], []
    ids = [r.record_id for r in rows]
    if len(ids) != len(set(ids)):
        errors.append({"code": "duplicate_record_id"})
    by_id = {r.record_id: r for r in rows}
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    grouping = {}
    edges = {}
    signatures = {}
    for r in rows:
        check_payload(r.model_input.model_dump(mode="json"))
        if fixture_record(r) and r.bucket != "fixture":
            errors.append({"code": "fixture_bucket_identity_mismatch", "record_id": r.record_id})
        line = r.lineage
        groups = [("structure", line.structure_id), ("component", line.component_id)]
        groups += [("fact_root", x) for x in line.fact_root_ids]
        groups += [("derivation", x) for x in line.derivation_ids]
        groups += [
            (k, getattr(line, k))
            for k in ("session_id", "run_id", "branch_id", "decision_id", "candidate_id")
            if getattr(line, k)
        ]
        for key in groups:
            if key in grouping:
                union(r.record_id, grouping[key])
            else:
                grouping[key] = r.record_id
        edges[r.record_id] = line.source_record_ids
        for ancestor in line.source_record_ids:
            if ancestor not in by_id:
                errors.append(
                    {"code": "unknown_ancestor", "record_id": r.record_id, "ancestor": ancestor}
                )
            else:
                union(r.record_id, ancestor)
        signatures[r.record_id] = input_signature(r)
        if (
            r.family in {"relation", "criterion"}
            and r.model_input.evidence.completeness != "complete"
        ):
            warnings.append({"record_id": r.record_id, "code": r.model_input.evidence.completeness})
        if r.family == "trajectory" and not r.model_input.logs_complete:
            warnings.append({"record_id": r.record_id, "code": "incomplete_logs"})
    visited, active = set(), set()

    def visit(i):
        if i in active:
            errors.append({"code": "lineage_cycle", "record_id": i})
            return
        if i in visited:
            return
        active.add(i)
        for ancestor in edges.get(i, ()):
            if ancestor in by_id:
                visit(ancestor)
        active.remove(i)
        visited.add(i)

    for i in ids:
        visit(i)
    components = defaultdict(list)
    for r in rows:
        components[find(r.record_id)].append(r)
    for component in components.values():
        if len({r.split for r in component}) > 1:
            errors.append(
                {
                    "code": "connected_lineage_cross_split",
                    "record_ids": sorted(r.record_id for r in component),
                }
            )
    errors.extend(duplicate_pairs(rows, signatures, near_duplicate_threshold))
    label_counts, statuses, accepted_tiers = Counter(), Counter(), Counter()
    evidence_rows = []
    label_only = []
    if annotations is not None:
        raw_labels = list(annotations)
        labels = {
            a.record_id: AnnotationV2.model_validate(a.model_dump(mode="json")) for a in raw_labels
        }
        if len(labels) != len(raw_labels) or labels.keys() != by_id.keys():
            errors.append({"code": "annotation_identity_set_mismatch"})
        for r in rows:
            a = labels.get(r.record_id)
            if a is None:
                continue
            if a.input_hash != r.input_hash or a.label_tier != r.label_tier:
                errors.append(
                    {"code": "annotation_input_or_tier_mismatch", "record_id": r.record_id}
                )
            statuses[a.status] += 1
            if a.status == "accepted":
                accepted_tiers[a.label_tier] += 1
            elif a.label_tier != "G2":
                errors.append({"code": "pending_tier_impersonation", "record_id": r.record_id})
            if a.final:
                if a.final.task_type != r.model_input.task_type:
                    errors.append({"code": "annotation_task_mismatch", "record_id": r.record_id})
                label_counts[f"{r.family}:{a.final.label}"] += 1
                target = evidence_rows if a.final.evidence_evaluable else label_only
                target.append(
                    {
                        "record_id": r.record_id,
                        "bucket": r.bucket,
                        "label_tier": a.label_tier,
                        "source_files": [
                            ref.model_dump(mode="json") for ref in r.provenance.actual_sources
                        ],
                        "session_id": r.lineage.session_id,
                        "source_digest": r.provenance.source.source_digest,
                        "evidence_training": a.final.evidence_evaluable,
                        "isolation_reason": None
                        if a.final.evidence_evaluable
                        else "localization_not_evaluable; excluded from evidence training and evidence/joint denominators",
                        "semantic_authority": "fixture only; no semantic truth claim"
                        if fixture_record(r)
                        else "numeric verifier rechecked at publication"
                        if a.label_tier == "G0"
                        else "requires independent semantic authority; model self-report is insufficient",
                    }
                )
    report = {
        "valid": not errors,
        "records": len(rows),
        "families": dict(Counter(r.family for r in rows)),
        "splits": dict(Counter(r.split for r in rows)),
        "languages": dict(Counter(r.language for r in rows)),
        "buckets": dict(Counter(r.bucket for r in rows)),
        "label_tiers": dict(accepted_tiers),
        "record_declared_tiers": dict(Counter(r.label_tier for r in rows)),
        "evidence_supervision": {
            "evaluable_count": len(evidence_rows),
            "evaluable_records": evidence_rows,
            "label_only_count": len(label_only),
            "label_only_records": label_only,
        },
        "labels": dict(label_counts),
        "annotation_status": dict(statuses),
        "structures": len({r.lineage.structure_id for r in rows}),
        "lineage_components": len(components),
        "sessions": len({r.lineage.session_id for r in rows if r.lineage.session_id}),
        "fixture_records": sum(fixture_record(r) for r in rows),
        "errors": errors,
        "warnings": warnings,
        "near_duplicate_threshold": near_duplicate_threshold,
        "near_duplicate_algorithm": "semantic-char5-jaccard-bitset-v1",
        "near_duplicate_limit": "lexical screening only; no claim of semantic independence",
        "component_members": [sorted(r.record_id for r in v) for v in components.values()],
    }
    if errors:
        raise QualityError(report)
    return report


def source_policy_error(record, policies):
    """The adapter supplies explicit source review records; absent permission fails closed."""
    if not record.provenance.actual_sources:
        return "missing_source_files"
    if not isinstance(policies, dict):
        return "source_reviews_required"
    for ref in record.provenance.actual_sources:
        review = policies.get(ref.path)
        if not isinstance(review, dict) or review.get("sha256") != ref.sha256:
            return "unreviewed_source"
        if review.get("review_status") != "approved":
            return "source_review_not_approved"
        if review.get("revoked") is True:
            return "source_authorization_revoked"
        if record.bucket == "public_aux":
            if (
                not all(review.get(k) for k in ("url", "accessed_at", "license", "original_hash"))
                or review.get("review_status") != "approved"
            ):
                return "public_source_license_or_review_missing"
            if review["license"] != record.provenance.license:
                return "public_source_license_mismatch"
        if record.bucket == "business_synth" and not review.get("authorization_ref"):
            return "department_authorization_missing"
        if record.bucket == "human_session" and not review.get("consent_ref"):
            return "human_consent_missing"
    return None


def policy_approval(record, policies):
    """Freeze only this record's actual source reviews, without the source body.

    Lineage decision_id/candidate_id are treated as global causal identities.
    Producers with local identifiers must namespace them before export; a fork
    retains its parent's causal identity instead of assigning a new namespace.
    """
    reason = source_policy_error(record, policies)
    if reason:
        raise ProtocolError(reason, status=403)
    return {
        "record_id": record.record_id,
        "input_hash": record.input_hash,
        "bucket": record.bucket,
        "sources": [
            {"ref": ref.model_dump(mode="json"), "review": policies[ref.path]}
            for ref in record.provenance.actual_sources
        ],
    }


def verify_policy_approval(record, approval):
    if not isinstance(approval, dict):
        raise ProtocolError("source_policy_receipt_missing")
    try:
        reviews = {entry["ref"]["path"]: entry["review"] for entry in approval["sources"]}
        expected = policy_approval(record, reviews)
    except (KeyError, TypeError) as exc:
        raise ProtocolError("source_policy_receipt_invalid") from exc
    if expected != approval:
        raise ProtocolError("source_policy_receipt_mismatch")
    return expected
