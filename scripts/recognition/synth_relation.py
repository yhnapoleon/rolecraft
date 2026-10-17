"""relation-v3: claims against evidence units, in the encoder-return ``pair_aggregate`` shape.

For every unit of the pm_pilot materials (both languages, every version; the trial logs
``trial_details`` / ``failures`` are left out) the program enumerates the legal cells of
the v3 generation matrix (design 3.3) and DeepSeek writes one learner-voice claim per
cell, rotating four styles:

    direct / paraphrase / number_format          -> SUPPORTED     (pair: SUPPORTS)
    negation / numeric_compare / slot_mismatch /
    old_version / request_as_approval             -> CONTRADICTED  (pair: CONTRADICTS)
    unfounded_inference                           -> INSUFFICIENT  (pair: UNRELATED)

A label-blind second pass judges (claim, gold unit) and only agreeing claims are kept
(label tier G2v). Each claim gets the gold unit plus three hard negatives, all labelled
UNRELATED: the expired other version of the same fact (for old-version claims), two C2
nearest non-gold units, and a unit sharing a number with the claim in another slot.
Negatives that state the claim's own quantity are dropped as ambiguous.

Each record carries a relation ``model_input`` (purpose, claim, as_of, temporal context,
candidates with observed / valid-from / valid-until) so the reference
``encoder_inputs(model_input)`` builds the exact encoder text. Split 60/20/20 by
material (the fact root), so no fact's paraphrases cross partitions.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from scripts.recognition.synth import (
    ROOT,
    SCENARIO,
    USAGE,
    chat,
    parallel,
    split,
    write_release,
)

SKIP = {"trial_details", "failures", "world_private", "tech_diagnostics"}
STYLES = {
    "zh": ["简洁", "啰嗦", "口语", "条目式（以“- ”开头）"],
    "en": ["concise", "wordy", "casual", "bullet (starts with '- ')"],
}
PHENOMENA = {
    "direct": ("SUPPORTED", "直接复述这条事实", "state the fact directly"),
    "paraphrase": (
        "SUPPORTED",
        "换一种说法复述，意思不变，不照抄原文用词",
        "restate it in other words without copying its wording",
    ),
    "number_format": (
        "SUPPORTED",
        "复述时把数字换成中文数字、约数或换算写法（意思仍相同）",
        (
            "restate it writing the number differently (words, approximations, conversions) "
            "with the same meaning"
        ),
    ),
    "negation": (
        "CONTRADICTED",
        "说出与这条事实相反的话（否定它）",
        "say the opposite of the fact (negate it)",
    ),
    "numeric_compare": (
        "CONTRADICTED",
        "给出一个违反这条数值事实的数字（超过上限、少于下限或数值不同）",
        "use a number that violates the fact (above the cap, below the floor, or different)",
    ),
    "slot_mismatch": (
        "CONTRADICTED",
        "把这条事实里的数字安到另一个量上（数对了但对象错了）",
        "attach the fact's number to a different quantity (right number, wrong thing)",
    ),
    "old_version": (
        "CONTRADICTED",
        "沿用这条事实更新前的旧数值（旧值见“旧版本”）",
        "keep using the value from before this update (see 'older version')",
    ),
    "request_as_approval": (
        "CONTRADICTED",
        "把“提交了申请/可以申请”说成“已经批准/已经拿到”",
        "treat 'requested / may request' as 'already approved / already granted'",
    ),
    "unfounded_inference": (
        "INSUFFICIENT",
        "做一个与这条事实相关、但原文并未提供依据的推断或预测",
        "make a related inference or prediction the text gives no basis for",
    ),
}
PAIR = {"SUPPORTED": "SUPPORTS", "CONTRADICTED": "CONTRADICTS", "INSUFFICIENT": "UNRELATED"}
_NUM = re.compile(r"\d+(?:\.\d+)?")


def load_units(language: str) -> tuple[list[dict], dict]:
    from career_lab.recognition.units import split_material
    from career_lab.scenarios.v2.loader import load_package

    index = json.loads(
        (ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text(encoding="utf-8")
    )
    pkg = load_package(ROOT / index["main"][language]["root"])
    versions: dict[str, list[int]] = {}
    for m in pkg.materials:
        versions.setdefault(m.id, []).append(m.version)
    units = []
    for m in pkg.materials:
        if m.id in SKIP:
            continue
        for f_index, f in enumerate(m.fragments):
            for u in split_material(m.id, m.version, f.text, base=f.ref.span_start or 0):
                if u.kind == "heading" or len(u.text.strip()) < 10:
                    continue
                units.append(
                    {
                        "unit_id": "u-" + u.unit_id[:24],
                        "material_id": m.id,
                        "version": m.version,
                        "fragment": f_index,
                        "text": u.text,
                        "numbers": _NUM.findall(u.text),
                    }
                )
    return units, versions


def other_version(unit: dict, units: list[dict], versions: dict) -> dict | None:
    """The same fragment position in the material's other version, if its text differs."""
    if len(versions.get(unit["material_id"], [])) < 2:
        return None
    for u in units:
        if (
            u["material_id"] == unit["material_id"]
            and u["version"] != unit["version"]
            and u["fragment"] == unit["fragment"]
            and u["text"] != unit["text"]
        ):
            return u
    return None


def legal_cells(unit: dict, older: dict | None) -> list[str]:
    cells = ["direct", "paraphrase", "negation", "unfounded_inference"]
    if unit["numbers"]:
        cells += ["number_format", "numeric_compare", "slot_mismatch"]
    if older is not None and unit["version"] > older["version"]:
        cells.append("old_version")
    if unit["material_id"] == "approvals" or re.search(
        r"申请|审批|批准|request|approv", unit["text"], re.I
    ):
        cells.append("request_as_approval")
    return cells


def generate(language: str, unit: dict, cells: list[str], older: dict | None, rng: random.Random):
    zh = language == "zh"
    styles = STYLES[language]
    asks = []
    for i, cell in enumerate(cells):
        label, dz, de = PHENOMENA[cell]
        asks.append(
            {"cell": cell, "style": styles[(i + rng.randint(0, 3)) % 4], "do": dz if zh else de}
        )
    system = SCENARIO[language] + (
        "\n你在为“断言—证据关系”识别器写训练数据：写产品经理学员在方案里会写的句子。只输出 JSON。"
        if zh
        else "\nYou write training data for a claim-evidence relation recognizer: sentences a "
        "product-manager learner would write in a plan. Output JSON only."
    )
    user = (
        ("原文事实：" if zh else "Source fact: ")
        + unit["text"]
        + (
            (
                "\n旧版本（已被上面这条取代）："
                if zh
                else "\nOlder version (superseded by the above): "
            )
            + older["text"]
            if older is not None and "old_version" in cells
            else ""
        )
        + (
            "\n按下面每一项各写一句学员口吻的话，每句自成一句，不要提“原文”二字。"
            '输出 {"items": [{"cell": "...", "claim": "..."}]}。\n'
            if zh
            else "\nWrite one learner-voice sentence for each task below; each stands alone and "
            'never mentions "the source". Output {"items": [{"cell": "...", "claim": "..."}]}.\n'
        )
        + json.dumps(asks, ensure_ascii=False)
    )
    found = chat(system, user) or {}
    rows = []
    for item in found.get("items", []):
        cell = item.get("cell")
        claim = (item.get("claim") or "").strip()
        if cell in PHENOMENA and claim:
            style = next((a["style"] for a in asks if a["cell"] == cell), "")
            rows.append({"cell": cell, "label": PHENOMENA[cell][0], "claim": claim, "style": style})
    return rows


def review(language: str, rows: list[dict]) -> list[dict]:
    zh = language == "zh"
    chunks = [rows[i : i + 25] for i in range(0, len(rows), 25)]

    def job(chunk):
        def run():
            items = {
                str(i): {"claim": r["claim"], "evidence": r["gold_text"]}
                for i, r in enumerate(chunk)
            }
            found = (
                chat(
                    "You are a careful annotator. Output JSON only.",
                    (
                        "对每一对，判断证据与断言的关系：SUPPORTED（证据足以支持断言）、CONTRADICTED（证据与断言冲突，"
                        "包括数值超限、否定、对象错配、把申请当批准、使用已被取代的旧值）、INSUFFICIENT（证据相关但不足以支持或否定）。"
                        '输出 {"labels": {"编号": "SUPPORTED|CONTRADICTED|INSUFFICIENT"}}。\n'
                        if zh
                        else "For each pair, judge the evidence-claim relation: SUPPORTED (the "
                        "evidence "
                        "suffices to support the claim), CONTRADICTED (it conflicts: a "
                        "number beyond a cap, "
                        "a negation, the wrong object, a request treated as approval, a "
                        "superseded value), "
                        "INSUFFICIENT (related but neither establishes nor refutes it). "
                        'Output {"labels": {"id": "SUPPORTED|CONTRADICTED|INSUFFICIENT"}}.\n'
                    )
                    + json.dumps(items, ensure_ascii=False),
                    temperature=0.0,
                )
                or {}
            )
            got = found.get("labels", {})
            return [r | {"review": got.get(str(i))} for i, r in enumerate(chunk)]

        return run

    return [r for batch in parallel([job(c) for c in chunks]) for r in batch]


def candidate(unit: dict, *, valid_from: int, valid_until: int | None, observed: int) -> dict:
    return {
        "id": unit["unit_id"],
        "text": unit["text"],
        "material_id": unit["material_id"],
        "version": unit["version"],
        "observed_at_seq": observed,
        "valid_from_seq": valid_from,
        "valid_until_seq": valid_until,
    }


def assemble(
    language: str, rows: list[dict], units: list[dict], versions: dict, rng: random.Random
):
    from career_lab.recognition import relation, retrieval

    texts = [u["text"] for u in units]
    records = []
    for n, r in enumerate(rows):
        gold = r["gold"]
        older = r.get("older")
        as_of = rng.randint(8, 24)
        update_seq = 6
        multi = len(versions.get(gold["material_id"], [])) > 1
        gold_from = update_seq if (multi and gold["version"] > 1) else 0
        cands = [candidate(gold, valid_from=gold_from, valid_until=None, observed=as_of - 1)]
        if older is not None:
            cands.append(
                candidate(older, valid_from=0, valid_until=update_seq, observed=update_seq - 1)
            )
        claim_q = relation.quantities(r["claim"])
        hits, _, _ = retrieval.search(r["claim"], texts, k=12, method="rrf")
        for h in hits:
            if len(cands) >= 4:
                break
            u = units[h.index]
            if u["unit_id"] in {c["id"] for c in cands} or u["material_id"] == gold["material_id"]:
                continue
            if claim_q & relation.quantities(u["text"]):
                continue  # states the claim's own quantity: ambiguous negative
            cands.append(
                candidate(u, valid_from=0, valid_until=None, observed=rng.randint(1, as_of - 1))
            )
        rng.shuffle(cands)
        pair_labels = {c["id"]: "UNRELATED" for c in cands}
        pair_labels[gold["unit_id"]] = PAIR[r["label"]]
        model_input = {
            "task_type": "relation",
            "criterion": None,
            "purpose": "commitment",
            "claim": r["claim"],
            "as_of": {
                "business_seq": as_of,
                "workspace_revision": as_of,
                "storage_revision": as_of,
            },
            "applicability": "applicable",
            "rule_context": {
                "evidence_time_context": {
                    "policy": "historical-evidence-time-v1",
                    "status": "known",
                    "reference_seq": as_of,
                    "validity_known_ids": [c["id"] for c in cands],
                }
            },
            "candidate_evidence": [
                {
                    "id": c["id"],
                    "text": c["text"],
                    "observed_at_seq": c["observed_at_seq"],
                    "valid_from_seq": c["valid_from_seq"],
                    "valid_until_seq": c["valid_until_seq"],
                }
                for c in cands
            ],
            "completeness": "complete",
        }
        records.append(
            {
                "record_id": f"rel3-{language}-{n:05d}",
                "language": language,
                "label": r["label"],
                "evidence_ids": [gold["unit_id"]] if r["label"] != "INSUFFICIENT" else [],
                "gold_unit_ids": [gold["unit_id"]],
                "pair_labels": pair_labels,
                "phenomenon": r["cell"],
                "style": r["style"],
                "fact_root": gold["material_id"],
                "gold_material": f"{gold['material_id']}@{gold['version']}",
                "review": r["review"],
                "label_tier": "G2v",
                "model_input": model_input,
            }
        )
    return records


def cmd_relation(args) -> None:
    out_rows, rejected = [], []
    for language in ("zh", "en"):
        rng = random.Random(31 if language == "zh" else 32)
        units, versions = load_units(language)
        pick = units if len(units) <= args.units else rng.sample(units, args.units)
        jobs = []
        for _round, unit in [(r, u) for r in range(args.rounds) for u in pick]:
            older = other_version(unit, units, versions)
            cells = legal_cells(unit, older)
            rng.shuffle(cells)
            cells = cells[: args.per_unit]
            job_seed = rng.random()

            def job(unit=unit, older=older, cells=cells, seed=job_seed, language=language):
                made = generate(language, unit, cells, older, random.Random(seed))
                return [
                    m
                    | {
                        "gold": unit,
                        "older": older if m["cell"] == "old_version" else None,
                        "gold_text": unit["text"],
                    }
                    for m in made
                ]

            jobs.append(job)
        generated = [row for batch in parallel(jobs) for row in batch]
        reviewed = review(language, generated)
        agreed = [r for r in reviewed if r["review"] == r["label"]]
        rejected += [
            {k: v for k, v in r.items() if k not in ("gold", "older")}
            for r in reviewed
            if r["review"] != r["label"]
        ]
        out_rows += assemble(language, agreed, units, versions, rng)
        print(
            language,
            "units",
            len(pick),
            "generated",
            len(generated),
            "agreed",
            len(agreed),
            USAGE,
            flush=True,
        )
    split(out_rows, key_of=lambda r: (r["language"], r["fact_root"]), seed=13)
    pairs = sum(len(r["pair_labels"]) for r in out_rows)
    write_release(
        Path(args.out),
        {"relation.jsonl": out_rows, "rejected.jsonl": rejected},
        {
            "per_unit": args.per_unit,
            "units": args.units,
            "rounds": args.rounds,
            "phenomena": {k: v[0] for k, v in PHENOMENA.items()},
            "pair_label_order": ["SUPPORTS", "CONTRADICTS", "UNRELATED"],
            "split": "60/20/20 by (language, material)",
        },
        f"""# relation-v3

Claim-evidence relation data for C1 (XLM-R ``pair_aggregate``), Chinese and English, built
on every pm_pilot material version. {len(out_rows)} claims, {pairs} claim-unit pairs.
Labels come from the generation specification (phenomenon -> label) and were kept only
when a label-blind DeepSeek pass agreed (tier G2v; generator and reviewer share a vendor,
which is a stated limitation). Rejected claims: {len(rejected)}.
Each record's ``model_input`` follows the relation EvidencePackage shape, so the reference
``encoder_inputs`` builds the encoder text; ``pair_labels`` maps every candidate to
SUPPORTS / CONTRADICTS / UNRELATED. Old-version claims include the superseded unit with
``valid_until_seq`` before the reference time (labelled UNRELATED: expired evidence).
Split 60/20/20 by (language, material) so a fact's paraphrases never cross partitions.
""",
    )
    print("relation records", len(out_rows), "pairs", pairs, "rejected", len(rejected), USAGE)
