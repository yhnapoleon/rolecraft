"""Historical responsibility findings, separate from the current work's grade."""

from career_lab.contracts.v2.core import ProtocolError, canonical
from math import isfinite
from .localization import message, validate_language
from .availability import SAFE_REASON


def before(a, b):
    if a is None or b is None:
        return False
    return all(
        getattr(a, k) <= getattr(b, k)
        for k in ["business_seq", "workspace_revision", "storage_revision"]
    )


def unique_sources(sources):
    """Deduplicate exact canonical references only, preserving first-use order.

    Different versions, time windows and quote spans remain distinct. This is
    local to each finding; it never deduplicates responsibilities or activities.
    """
    seen = set()
    result = []
    for source in sources:
        key = canonical(source)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def assess_responsibilities(
    records, policy, subjects, at, resolve, resolve_at, *, work_language="zh"
):
    from dataclasses import replace

    if policy.mechanism.startswith("v2."):
        mechanism = policy.mechanism[3:]
        policy = replace(
            policy,
            mechanism="tests"
            if mechanism in {"functional_tests", "staleness_test", "adjustment"}
            else mechanism,
        )
    output = []
    for record in records:
        if record.kind not in {
            "actual_action",
            "commitment",
            "completion_claim",
            "unknown",
        } or record.state not in {"active", "withdrawn", "unknown"}:
            raise ProtocolError("invalid_responsibility_record")
        if record.criterion != policy.id or not any(a == b for a in subjects for b in record.scope):
            continue
        # Newer responsibilities are outside the historical judgment. No future
        # source text is loaded merely to explain why it was excluded.
        if not before(record.occurred_at, at) or not before(record.valid_from, at):
            continue
        entry = {
            "criterion": record.criterion,
            "kind": record.kind,
            "state": record.state,
            "occurred_at": record.occurred_at.model_dump(mode="json"),
            "evaluated_at": at.model_dump(mode="json"),
            "scope": [
                r.model_dump(mode="json") for r in record.scope if any(r == s for s in subjects)
            ],
            "finding": "unknown",
            "explanation": message(work_language, SAFE_REASON),
            "sources": [],
        }
        proofs = [resolve(ref) for ref in record.sources]
        if not proofs or not all(proofs):
            # Missing and forbidden have the same safe shape. Coalesce these
            # placeholders so private source cardinality is not disclosed.
            pending = {
                "criterion": policy.id,
                "kind": "unknown",
                "state": "unknown",
                "occurred_at": None,
                "evaluated_at": at.model_dump(mode="json"),
                "scope": [r.model_dump(mode="json") for r in subjects],
                "finding": "unknown",
                "explanation": message(work_language, SAFE_REASON),
                "sources": [],
            }
            if pending not in output:
                output.append(pending)
            continue
        entry["sources"] = unique_sources([r.model_dump(mode="json") for r in proofs])
        entry["actor_id"] = record.actor_id
        entry["executor"] = record.executor.model_dump(mode="json") if record.executor else None
        valid = (record.valid_until is None or not before(record.valid_until, at)) and all(
            r.valid_until_seq is None or at.business_seq < r.valid_until_seq for r in proofs
        )
        entry["sources_valid_at_subject"] = valid
        if not valid:
            entry["explanation"] = message(
                work_language,
                "已核对历史来源，但其在本次参照点已失效；保留历史用途，本项当前有效性待核验。",
            )
            output.append(entry)
            continue
        if record.kind == "unknown" or record.state == "unknown":
            output.append(entry)
            continue
        if record.kind == "commitment":
            entry.update(
                finding="recorded_commitment",
                explanation=(
                    message(
                        work_language,
                        "记录中有已撤回的承诺；承诺不证明已经执行，撤回理由与后续安排仍需结合依据核验。",
                    )
                    if record.state == "withdrawn"
                    else message(
                        work_language,
                        "记录中有持续有效的承诺；承诺不证明已经执行，仍需按其内容与期限跟进。",
                    )
                ),
            )
            output.append(entry)
            continue
        values = {}
        seen = set()
        for fact in record.facts:
            if fact.name in seen:
                raise ProtocolError("duplicate_historical_fact")
            seen.add(fact.name)
            canonical(fact.value)
            refs = [resolve_at(r, record.occurred_at) for r in fact.sources]
            if refs and all(refs):
                values[fact.name] = fact.value
                entry["sources"] = unique_sources(
                    [*entry["sources"], *[r.model_dump(mode="json") for r in refs]]
                )

        def numbers(*names):
            if any(
                type(values.get(n)) not in (int, float) or not isfinite(values[n]) or values[n] < 0
                for n in names
            ):
                return None
            return [values[n] for n in names]

        if record.kind == "actual_action" and policy.mechanism == "capacity":
            pair = numbers("actual_participants", "capacity_at_action")
            if pair is not None:
                breach = pair[0] > pair[1]
                entry.update(
                    finding="verified_breach" if breach else "verified_within_limit",
                    explanation=message(
                        work_language,
                        "历史实际开放人数{p0}，当时有效容量{p1}；",
                        p0=pair[0],
                        p1=pair[1],
                    )
                    + (
                        message(work_language, "存在超容量记录。")
                        if breach
                        else message(work_language, "该记录未超容量；0人不构成未达标。")
                    ),
                )
        elif record.kind == "actual_action" and policy.mechanism == "resources":
            pair = numbers("actual_dev_days", "available_dev_days_at_action")
            if pair is not None:
                breach = pair[0] > pair[1]
                entry.update(
                    finding="verified_breach" if breach else "verified_within_limit",
                    explanation=message(
                        work_language,
                        "历史实际占用{p0}人日，当时可用{p1}人日；",
                        p0=pair[0],
                        p1=pair[1],
                    )
                    + (
                        message(work_language, "存在超用记录。")
                        if breach
                        else message(
                            work_language, "未发现该次占用超额；不要求停止方案另有正数上线日期。"
                        )
                    ),
                )
        elif record.kind == "completion_claim" and policy.mechanism in {"capacity", "resources"}:
            names = (
                ("claimed_participants", "actual_participants_at_claim")
                if policy.mechanism == "capacity"
                else ("claimed_dev_days", "actual_dev_days_at_claim")
            )
            pair = numbers(*names)
            if pair is not None:
                entry.update(
                    finding="claim_matches_record"
                    if pair[0] == pair[1]
                    else "verified_claim_mismatch",
                    explanation=message(
                        work_language,
                        "报告声明值{p0}，声明时点真实记录值{p1}；只核这项明确声明，不推断整份结果报告已上线。",
                        p0=pair[0],
                        p1=pair[1],
                    ),
                )
        elif record.kind == "completion_claim" and policy.mechanism == "tests":
            # These facts must describe the ledger AT THE CLAIM, not later tests.
            count = values.get("valid_test_count_at_claim")
            complete = values.get("test_ledger_complete_at_claim")
            if complete is True and type(count) is int and count >= 0:
                entry.update(
                    finding="verified_breach" if count == 0 else "claim_has_run_records",
                    explanation=message(
                        work_language, "声明已完成验证，但声明时点的完整记录无有效测试。"
                    )
                    if count == 0
                    else message(
                        work_language, "声明时点存在有效测试记录；数量不证明完成声明或结论质量。"
                    ),
                )
        elif record.kind == "actual_action" and policy.mechanism == "tests":
            entry.update(
                finding="recorded_action",
                explanation=message(
                    work_language, "有实际测试行动记录；运行不等于测试通过或覆盖充分。"
                ),
            )
        output.append(entry)
    return output
