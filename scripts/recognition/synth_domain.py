"""it_ticket_pilot (design 6.1, data-only edition): a second domain for cross-domain tests.

    python -m scripts.recognition.synth_domain --out data/releases/it-ticket-v1

Same structure as pm_pilot (index_scope_resource_dependency): a knowledge assistant
pilot, here an IT service-desk ticket assistant. A fixed fact ledger drives DeepSeek's
drafting of the materials in both languages; the program then checks that every number
in a material is a ledger value and that each versioned fact appears in its version.
From those materials the relation generator (synth_relation) writes claims and the
query generator (synth) writes in-domain / out-of-domain assistant questions. Everything
is test-only data for E9 (train on pm_pilot, test here). The playable scenario (engine
content, release, evaluation facts) is not built in this edition.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from scripts.recognition import synth
from scripts.recognition import synth_relation as rel

LEDGER = {
    "concurrent_cap": 30,
    "dev_days": 3,
    "launch_day": 7,
    "sla_p2_v1_hours": 4,
    "sla_p2_v2_hours": 2,
    "sla_p1_minutes": 30,
    "approvable_concurrent": 60,
    "approvable_dev_days": 6,
    "approvable_day": 10,
    "finance": 15,
    "sales": 25,
    "rnd": 20,
    "candidates": 60,
    "password_reset_minutes": 15,
}
MATERIALS = {
    "brief": "主管的委托：接手服务台工单助手试点，决定首批开放哪些部门；当前并发工单上限、可用开发人日、正式试点日",
    "technical": "技术负责人的交接：并发工单上限的来源、实时同步需要额外开发、范围过滤与人工兜底",
    "approvals": "资源审批规则：可审批的并发上限、开发人日、期限；申请提交不等于批准",
    "departments": "候选部门名单：财务、销售、研发各多少人，合计",
    "faq": "知识库 FAQ：报修流程、密码重置时长、权限申请需要主管审批、VPN 连接",
    "sla_policy@1": "知识库 SLA 政策 v1：P1 响应时限、P2 响应时限（旧）",
    "sla_policy@2": "知识库 SLA 政策 v2：P2 响应时限更新（新），P1 不变",
}
KB = {"faq", "sla_policy"}
# Digits glued to letters (P1, v2) are identifiers, not ledger numbers.
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")


NAMES = {
    "concurrent_cap": ("当前并发工单上限（个）", "current concurrent ticket cap (tickets)"),
    "dev_days": ("可用开发资源（人日）", "available development effort (developer days)"),
    "launch_day": ("正式试点开始（第几天）", "formal pilot starts on day"),
    "sla_p2_v1_hours": ("P2 工单响应时限，旧版 v1（小时）", "P2 response time, old v1 (hours)"),
    "sla_p2_v2_hours": ("P2 工单响应时限，新版 v2（小时）", "P2 response time, new v2 (hours)"),
    "sla_p1_minutes": ("P1 工单响应时限（分钟）", "P1 response time (minutes)"),
    "approvable_concurrent": ("可审批的并发上限（个）", "approvable concurrent cap (tickets)"),
    "approvable_dev_days": ("可审批的开发资源（人日）", "approvable development effort (developer days)"),
    "approvable_day": ("可审批的最晚试点日（第几天）", "latest approvable pilot day"),
    "finance": ("财务部候选人数", "finance candidates"),
    "sales": ("销售部候选人数", "sales candidates"),
    "rnd": ("研发部候选人数", "R&D candidates"),
    "candidates": ("候选合计人数", "total candidates"),
    "password_reset_minutes": ("密码重置完成时长（分钟）", "password reset completion time (minutes)"),
}


def fill_keys(text: str) -> str:
    for key, value in sorted(LEDGER.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(key, str(value))
    return text


def draft(language: str) -> dict[str, list[str]]:
    zh = language == "zh"
    ledger = "; ".join(f"{NAMES[k][0 if zh else 1]}: {v}" for k, v in LEDGER.items())
    jobs = []
    for key, brief in MATERIALS.items():
        def job(key=key, brief=brief):
            version_note = (
                ("这是旧版 v1：P2 响应时限写 4 小时。" if zh else "This is the old v1: P2 response time is 4 hours.")
                if key.endswith("@1")
                else ("这是新版 v2：P2 响应时限更新为 2 小时。" if zh else "This is the new v2: P2 response time is updated to 2 hours.")
                if key.endswith("@2")
                else ""
            )
            found = synth.chat(
                "Output JSON only.",
                (
                    f"为一个企业 IT 服务台工单助手试点写一份工作材料：{brief}。{version_note}"
                    f"写 8 到 14 句中文，每句一个事实或要求，像真实的内部文件。只能使用这个账本里的数字："
                    f"{ledger}；不要出现账本以外的任何数字。"
                    '输出 {"sentences": ["..."]}'
                    if zh
                    else f"Write a working document for an enterprise IT service-desk ticket assistant "
                    f"pilot: {brief}. {version_note} Write 8 to 14 English sentences, one fact or "
                    f"requirement each, like a real internal document. Use only numbers from this ledger: "
                    f"{ledger}; no other numbers at all. "
                    'Output {"sentences": ["..."]}'
                ),
                temperature=0.6,
            ) or {}
            return key, [
                fill_keys(s.strip()) for s in found.get("sentences", []) if isinstance(s, str) and s.strip()
            ]
        jobs.append(job)
    allowed = {str(v) for v in LEDGER.values()}
    out, problems = {}, []
    for key, sentences in synth.parallel(jobs):
        kept = []
        for s in sentences:
            bad = [n for n in NUMBER.findall(s) if n not in allowed]
            if re.search(r"[a-z]+_[a-z0-9_]+", s):
                bad.append("ledger_key")
            if bad:
                problems.append({"material": key, "sentence": s, "numbers": bad})
            else:
                kept.append(s)
        out[key] = kept
    v1 = " ".join(out.get("sla_policy@1", []))
    v2 = " ".join(out.get("sla_policy@2", []))
    checks = {
        "v1_has_old": str(LEDGER["sla_p2_v1_hours"]) in v1,
        "v2_has_new": str(LEDGER["sla_p2_v2_hours"]) in v2,
    }
    return {"materials": out, "dropped": problems, "checks": checks}


def units_of(language: str, materials: dict[str, list[str]]) -> tuple[list[dict], dict]:
    units, versions = [], {}
    for key, sentences in materials.items():
        mid, _, version = key.partition("@")
        version = int(version or 1)
        versions.setdefault(mid, []).append(version)
        for i, s in enumerate(sentences):
            units.append(
                {
                    "unit_id": "it-" + synth.hashlib.sha256(f"{language}|{key}|{i}|{s}".encode()).hexdigest()[:22],
                    "material_id": mid,
                    "version": version,
                    "fragment": i,
                    "text": s,
                    "numbers": NUMBER.findall(s),
                    "domain": ("it_" + mid) if mid in KB else "investigation",
                }
            )
    return units, versions


def out_of_domain(language: str, n: int) -> list[dict]:
    zh = language == "zh"
    found = synth.chat(
        "Output JSON only.",
        (
            f"一个 IT 服务台工单助手只覆盖：报修流程、密码重置、权限申请、VPN、SLA 响应时限。写 {n} 个员工可能问、"
            f"但不在这些范围内的问题（一半是公司内其他事务，如报销、请假、会议室；一半与工作无关）。"
            '输出 {"items": ["..."]}'
            if zh
            else f"An IT service-desk assistant covers only: repair requests, password resets, access "
            f"requests, VPN and SLA response times. Write {n} questions employees might ask that fall "
            "outside that scope (half other company matters such as expenses, leave, meeting rooms; "
            'half unrelated to work). Output {"items": ["..."]}'
        ),
    ) or {}
    return [
        {"query": q.strip(), "language": language, "kind": "out_near" if i < n // 2 else "out_far"}
        for i, q in enumerate(found.get("items", []))
        if isinstance(q, str) and q.strip()
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--per-unit", type=int, default=9)
    args = parser.parse_args(argv)
    materials, relation_rows, query_rows, rejected = {}, [], [], []
    for language in ("zh", "en"):
        drafted = draft(language)
        materials[language] = drafted
        units, versions = units_of(language, drafted["materials"])
        rng = random.Random(41 if language == "zh" else 42)
        jobs = []
        for unit in units:
            older = rel.other_version(unit, units, versions)
            cells = rel.legal_cells(unit, older)[: args.per_unit]

            def job(unit=unit, older=older, cells=cells, seed=rng.random()):
                made = rel.generate(language, unit, cells, older, random.Random(seed))
                return [
                    m | {"gold": unit, "older": older if m["cell"] == "old_version" else None, "gold_text": unit["text"]}
                    for m in made
                ]

            jobs.append(job)
        generated = [r for batch in synth.parallel(jobs) for r in batch]
        reviewed = rel.review(language, generated)
        agreed = [r for r in reviewed if r["review"] == r["label"]]
        rejected += [{k: v for k, v in r.items() if k not in ("gold", "older")} for r in reviewed if r["review"] != r["label"]]
        records = rel.assemble(language, agreed, units, versions, rng)
        for r in records:
            r["record_id"] = r["record_id"].replace("rel3-", "relit-")
            r["split"] = "test"
            r["domain"] = "it_ticket_pilot"
        relation_rows += records
        kb_units = [u for u in units if u["material_id"] in KB]
        found = synth.gen_queries(language, kb_units, 3, "direct") + synth.gen_queries(language, kb_units, 3, "paraphrase")
        for q in found:
            q["domain"] = next(u["domain"] for u in kb_units if u["unit_id"] == q["answer_unit_id"])
        found += out_of_domain(language, 60)
        query_rows += [q | {"split": "test", "scenario": "it_ticket_pilot"} for q in found]
        print(language, "units", len(units), "relation", len(records), "queries", len(found), synth.USAGE, flush=True)
    out = Path(args.out)
    synth.write_release(
        out,
        {"relation.jsonl": relation_rows, "queries.jsonl": query_rows, "rejected.jsonl": rejected},
        {"ledger": LEDGER, "materials": list(MATERIALS), "per_unit": args.per_unit},
        f"""# it-ticket-v1

Second domain for cross-domain evaluation (E9): an IT service-desk ticket assistant
pilot with the same structure as pm_pilot. Materials were drafted by DeepSeek from a fixed
fact ledger; sentences with numbers outside the ledger were dropped by program. Relation
claims ({len(relation_rows)}) and assistant questions ({len(query_rows)}) follow the
pm_pilot generators exactly; all records are test-only. The playable scenario is not built.
""",
    )
    with (out / "materials.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(materials, handle, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
