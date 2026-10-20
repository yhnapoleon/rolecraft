"""public-synth-v1: relation claims written by DeepSeek against real public evidence units.

    python -m scripts.public.synth_grounded --out data/releases/public-synth-v1
    python -m scripts.public.synth_grounded --smoke 8      # a few units, nothing written

Same protocol as relation-v3 (design 3.3), with the pm_pilot materials replaced by real
text from ``public-materials-v1``: GitHub site-policy sentences (and the sentences a later
commit rewrote), KEP facts and goals, Jira issue fields and Fix Version history,
TheAgentCompany PM tasks and the tau-bench service policies.

1. Pick informative gold units (numbers, obligations, approvals, versions) spread across
   documents; every superseded unit whose wording change touched a number or a modal verb
   is used for the old-version cell together with the sentence that replaced it.
2. For each gold unit, five neighbours from the same document (TF-IDF) form the pool of
   hard negatives; a negative that states the claim's own quantity is skipped.
3. Chinese: the gold, older and neighbour units are translated by DeepSeek (temperature
   0); a translation is kept only if it carries exactly the source's numbers.
4. DeepSeek writes one claim per legal cell of the generation matrix, four styles rotated;
   a label-blind second pass judges (claim, gold unit) and only agreeing claims are kept
   (G2v). Old-version claims also get the superseded unit as an expired candidate.
5. Split 60/20/20 by (language, source document).
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from scripts.public.common import PAIR, RELEASES, candidate, relation_record, write_release
from scripts.recognition.synth import USAGE, chat, parallel, split
from scripts.recognition.synth_relation import PHENOMENA, STYLES

MATERIALS = RELEASES / "public-materials-v1" / "units.jsonl"
ID_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b|\"[^\"]*\"")
NUM = re.compile(r"\d+(?:\.\d+)?")
INFORMATIVE = re.compile(
    r"\b(must|shall|may not|may only|only|within|at least|at most|up to|no later|no more|"
    r"requires?|required|prohibit\w*|not permitted|approv\w*|consent|authori[sz]\w*|deadline|"
    r"days?|hours?|months?|years?|percent|fees?|limits?|refund\w*|stage|milestone|status|"
    r"resolution|fix version|due date)\b|%|\$",
    re.I,
)
MODAL = re.compile(r"\b(must|shall|may|will|not|only|no)\b", re.I)
REQUEST = re.compile(r"request|approv|consent|permission|authori[sz]", re.I)
QUOTA = {
    "site-policy": 110,
    "kep": 100,
    "kep-goal": 30,
    "jira": 90,
    "theagentcompany": 20,
    "tau-bench": 40,
}
JIRA_HISTORIES = 40
SOURCES = {
    "site-policy": (
        "a GitHub policy or terms-of-service document",
        "a product or project manager at a company that uses GitHub, writing a plan, a "
        "compliance checklist or a status note",
        "GitHub 的政策或服务条款文档",
        "在使用 GitHub 的公司里写方案、合规清单或进度说明的产品/项目经理",
    ),
    "kep": (
        "a Kubernetes Enhancement Proposal (KEP) record",
        "a release or project manager writing a release-tracking note",
        "Kubernetes 功能提案（KEP）记录",
        "写版本跟踪记录的发布经理或项目经理",
    ),
    "jira": (
        "a Jira issue record of an open-source project",
        "a project manager writing a status report",
        "开源项目的 Jira 工单记录",
        "写进度汇报的项目经理",
    ),
    "theagentcompany": (
        "a project-management task assignment",
        "the project manager reporting their plan or progress on the task",
        "一份项目管理任务说明",
        "汇报这项任务计划或进展的项目经理",
    ),
    "tau-bench": (
        "an airline or retail customer-service policy",
        "an operations or product manager writing a process note",
        "航空或零售客服的服务政策",
        "写流程说明的运营或产品经理",
    ),
}


def quantities(text: str) -> set[str]:
    return set(NUM.findall(ID_TOKEN.sub(" ", text)))


def kind(unit: dict) -> str:
    if unit["source_id"] == "kep" and unit["text"].startswith(("A goal", "A non-goal")):
        return "kep-goal"
    return unit["source_id"]


def informative(unit: dict) -> bool:
    text = unit["text"]
    if unit["source_id"] == "kep":
        return " owned by " not in text
    if unit["source_id"] == "jira":
        return " is titled " not in text
    return 60 <= len(text) <= 320 and bool(INFORMATIVE.search(text) or quantities(text))


def select(units: list[dict], rng: random.Random) -> list[tuple[dict, dict | None]]:
    """(gold, older) pairs: round-robin over documents per source quota, plus histories."""
    by_id = {u["unit_id"]: u for u in units}
    picks: list[tuple[dict, dict | None]] = []
    pools: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for u in units:
        if u["current"] and informative(u):
            pools[kind(u)][u["doc_id"]].append(u)
    for name, quota in QUOTA.items():
        docs = {d: rng.sample(us, len(us)) for d, us in sorted(pools[name].items())}
        order = list(docs)
        rng.shuffle(order)
        taken = []
        while len(taken) < quota and any(docs.values()):
            for d in order:
                if docs[d] and len(taken) < quota:
                    taken.append(docs[d].pop())
        picks += [(u, None) for u in taken]
    # superseded site-policy sentences whose change touched a number or a modal verb
    for u in units:
        if u["source_id"] == "site-policy" and not u["current"]:
            new = by_id[u["superseded_by"]]
            if quantities(u["text"]) != quantities(new["text"]) or (
                set(MODAL.findall(u["text"].lower())) != set(MODAL.findall(new["text"].lower()))
            ):
                picks.append((new, u))
    # Jira: the most recent earlier Fix Version state of a sample of issues
    latest: dict[str, dict] = {}
    for u in units:
        if u["source_id"] == "jira" and not u["current"]:
            latest[u["superseded_by"]] = u  # history is in time order; keep the last
    keys = sorted(latest)
    for gid in rng.sample(keys, min(JIRA_HISTORIES, len(keys))):
        picks.append((by_id[gid], latest[gid]))
    return picks


def neighbours(picks, units: list[dict], k: int = 5) -> dict[str, list[dict]]:
    current = [u for u in units if u["current"]]
    by_doc, by_source = defaultdict(list), defaultdict(list)
    for u in current:
        by_doc[u["doc_id"]].append(u)
        by_source[u["source_id"]].append(u)
    out = {}
    for gold, _ in picks:
        if gold["unit_id"] in out:
            continue
        pool = [u for u in by_doc[gold["doc_id"]] if u["unit_id"] != gold["unit_id"]]
        if len(pool) < k:
            extra = [u for u in by_source[gold["source_id"]] if u["doc_id"] != gold["doc_id"]]
            pool += random.Random(gold["unit_id"]).sample(extra, min(40, len(extra)))
        texts = [gold["text"]] + [u["text"] for u in pool]
        matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(texts)
        scores = linear_kernel(matrix[0:1], matrix[1:]).ravel()
        ranked = [pool[i] for i in sorted(range(len(pool)), key=lambda i: -scores[i])]
        out[gold["unit_id"]] = [u for u in ranked if u["text"] != gold["text"]][:k]
    return out


def translate(units: list[dict]) -> dict[str, str]:
    """unit_id -> Chinese text, kept only when the numbers survive unchanged."""
    chunks = [units[i : i + 20] for i in range(0, len(units), 20)]

    def job(chunk):
        def run():
            found = (
                chat(
                    "You translate workplace documents. Output JSON only.",
                    "Translate each English sentence into natural simplified Chinese as it would "
                    "appear in a Chinese workplace document. Keep every number, version string, "
                    "identifier (e.g. KEP-127, KAFKA-9366, v1.27), product name and quoted title "
                    "exactly as written; do not add, drop or soften any information. "
                    'Output {"zh": {"<id>": "<Chinese>"}}.\n'
                    + json.dumps({u["unit_id"]: u["text"] for u in chunk}, ensure_ascii=False),
                    temperature=0.0,
                )
                or {}
            )
            return found.get("zh", {})

        return run

    merged = {}
    for batch in parallel([job(c) for c in chunks]):
        merged.update(batch)
    by_id = {u["unit_id"]: u for u in units}
    return {
        uid: zh.strip()
        for uid, zh in merged.items()
        if uid in by_id
        and isinstance(zh, str)
        and zh.strip()
        and sorted(NUM.findall(zh)) == sorted(NUM.findall(by_id[uid]["text"]))
    }


def legal_cells(gold: dict, older: dict | None) -> list[str]:
    if older is not None:
        return ["old_version"]
    cells = ["direct", "paraphrase", "negation", "unfounded_inference"]
    if quantities(gold["text"]):
        cells += ["number_format", "numeric_compare", "slot_mismatch"]
    if REQUEST.search(gold["text"]):
        cells.append("request_as_approval")
    return cells


def generate(language: str, gold: dict, text: str, older_text: str | None, cells, rng):
    zh = language == "zh"
    desc, voice, desc_zh, voice_zh = SOURCES[gold["source_id"]]
    asks = [
        {
            "cell": cell,
            "style": STYLES[language][(i + rng.randint(0, 3)) % 4],
            "do": PHENOMENA[cell][1] if zh else PHENOMENA[cell][2],
        }
        for i, cell in enumerate(cells)
    ]
    system = (
        f"原始文档：{desc_zh}。你在为“断言—证据关系”识别器写评测数据："
        f"写{voice_zh}依据这份文档时会写的句子。只输出 JSON。"
        if zh
        else f"Source document: {desc}. You write evaluation data for a claim-evidence relation "
        f"recognizer: sentences that {voice} might write while relying on this document. "
        "Output JSON only."
    )
    user = (
        ("原文事实：" if zh else "Source fact: ")
        + text
        + (
            (
                "\n旧版本（已被上面这条取代）："
                if zh
                else "\nOlder version (superseded by the above): "
            )
            + older_text
            if older_text
            else ""
        )
        + (
            "\n按下面每一项各写一句话，每句自成一句，不要提“原文”二字，也不要编造原文没有的编号或名称。"
            '输出 {"items": [{"cell": "...", "claim": "..."}]}。\n'
            if zh
            else "\nWrite one sentence for each task below; each stands alone, never mentions "
            '"the source" and invents no identifiers or names. '
            'Output {"items": [{"cell": "...", "claim": "..."}]}.\n'
        )
        + json.dumps(asks, ensure_ascii=False)
    )
    found = chat(system, user) or {}
    rows = []
    for item in found.get("items", []):
        cell, claim = item.get("cell"), (item.get("claim") or "").strip()
        if cell in cells and claim:
            style = next(a["style"] for a in asks if a["cell"] == cell)
            rows.append({"cell": cell, "label": PHENOMENA[cell][0], "claim": claim, "style": style})
    return rows


def review(language: str, rows: list[dict]) -> list[dict]:
    """Label-blind second pass on (claim, gold text); same wording as relation-v3."""
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
                        else "For each pair, judge the evidence-claim relation: SUPPORTED "
                        "(the evidence suffices to support the claim), CONTRADICTED (it "
                        "conflicts: a number beyond a cap, a negation, the wrong object, a "
                        "request treated as approval, a superseded value), "
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


def assemble(language: str, rows, near, zh_text, rng) -> list[dict]:
    def text_of(u):
        return zh_text[u["unit_id"]] if language == "zh" else u["text"]

    records = []
    for n, r in enumerate(rows):
        gold, older = r["gold"], r["older"]
        as_of, update = rng.randint(8, 24), 6
        cands = [
            candidate(
                gold["unit_id"],
                text_of(gold),
                observed=as_of - 1,
                valid_from=update if older else 0,
            )
        ]
        if older is not None:
            cands.append(
                candidate(older["unit_id"], text_of(older), observed=update - 1, valid_until=update)
            )
        claim_q = quantities(r["claim"])
        for u in near[gold["unit_id"]]:
            if len(cands) >= 4:
                break
            if language == "zh" and u["unit_id"] not in zh_text:
                continue
            if u["unit_id"] in {c["id"] for c in cands}:
                continue
            if claim_q & quantities(text_of(u)):
                continue  # states the claim's own quantity: ambiguous negative
            cands.append(candidate(u["unit_id"], text_of(u), observed=rng.randint(1, as_of - 1)))
        rng.shuffle(cands)
        pair_labels = {c["id"]: "UNRELATED" for c in cands}
        pair_labels[gold["unit_id"]] = PAIR[r["label"]]
        transformations = [{"kind": "claim_authoring", "by": "deepseek-chat", "cell": r["cell"]}]
        if language == "zh":
            transformations.insert(
                0, {"kind": "translation", "by": "deepseek-chat", "note": "numbers checked"}
            )
        records.append(
            relation_record(
                record_id=f"ps-{language}-{n:05d}",
                language=language,
                label=r["label"],
                claim=r["claim"],
                candidates=cands,
                pair_labels=pair_labels,
                gold_unit_ids=[gold["unit_id"]],
                split="",
                as_of=as_of,
                bucket="public_synth",
                source_id=gold["source_id"],
                phenomenon=r["cell"],
                style=r["style"],
                group=f"{gold['source_id']}:{gold['doc_id']}",
                review=r["review"],
                label_tier="G2v",
                label_origin="generation spec, kept when a label-blind DeepSeek pass agreed",
                grounded_on={
                    k: gold.get(k)
                    for k in ("unit_id", "text", "locator", "url", "revision", "source_id")
                }
                | (
                    {
                        "older": {
                            k: older.get(k) for k in ("unit_id", "text", "locator", "superseded_at")
                        }
                    }
                    if older
                    else {}
                ),
                transformations=transformations,
                publishable=True,
            )
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RELEASES / "public-synth-v1"))
    parser.add_argument("--per-unit", type=int, default=7)
    parser.add_argument("--smoke", type=int, default=0)
    args = parser.parse_args()
    units = [json.loads(line) for line in MATERIALS.open(encoding="utf-8")]
    rng = random.Random(41)
    picks = select(units, rng)
    if args.smoke:
        picks = rng.sample(picks, args.smoke)
    near = neighbours(picks, units)
    pool = {}
    for gold, older in picks:
        for u in [gold, older, *near[gold["unit_id"]]]:
            if u is not None:
                pool[u["unit_id"]] = u
    zh_text = translate(list(pool.values()))
    print(
        "picks",
        len(picks),
        Counter(g["source_id"] for g, _ in picks),
        "pool",
        len(pool),
        "translated",
        len(zh_text),
        USAGE,
        flush=True,
    )
    out_rows, rejected = [], []
    for language in ("en", "zh"):
        lrng = random.Random(51 if language == "en" else 52)
        jobs = []
        for gold, older in picks:
            if language == "zh" and (
                gold["unit_id"] not in zh_text or (older and older["unit_id"] not in zh_text)
            ):
                continue
            cells = legal_cells(gold, older)
            lrng.shuffle(cells)
            cells = cells[: args.per_unit]
            text = zh_text[gold["unit_id"]] if language == "zh" else gold["text"]
            older_text = (
                (zh_text[older["unit_id"]] if language == "zh" else older["text"])
                if older
                else None
            )
            seed = lrng.random()

            def job(
                gold=gold,
                older=older,
                text=text,
                older_text=older_text,
                cells=cells,
                seed=seed,
                language=language,
            ):
                made = generate(language, gold, text, older_text, cells, random.Random(seed))
                return [m | {"gold": gold, "older": older, "gold_text": text} for m in made]

            jobs.append(job)
        generated = [row for batch in parallel(jobs) for row in batch]
        reviewed = review(language, generated)
        agreed = [r for r in reviewed if r["review"] == r["label"]]
        rejected += [
            {k: v for k, v in r.items() if k not in ("gold", "older")}
            | {"language": language, "gold_unit_id": r["gold"]["unit_id"]}
            for r in reviewed
            if r["review"] != r["label"]
        ]
        out_rows += assemble(language, agreed, near, zh_text, lrng)
        print(language, "generated", len(generated), "agreed", len(agreed), USAGE, flush=True)
    split(out_rows, key_of=lambda r: (r["language"], r["group"]), seed=17)
    if args.smoke:
        for r in out_rows[:6]:
            print(
                json.dumps({k: r[k] for k in ("label", "phenomenon", "split")}, ensure_ascii=False),
                "|",
                r["model_input"]["claim"],
            )
            for c in r["model_input"]["candidate_evidence"]:
                print("    ", r["pair_labels"][c["id"]][:4], c["valid_until_seq"], c["text"][:150])
        return
    units_out = [
        {
            "unit_id": uid,
            "text_en": u["text"],
            "text_zh": zh_text.get(uid),
            "source_id": u["source_id"],
            "doc_id": u["doc_id"],
            "locator": u["locator"],
            "url": u.get("url"),
            "current": u["current"],
        }
        for uid, u in pool.items()
    ]
    counts = Counter((r["language"], r["label"]) for r in out_rows)
    pairs = sum(len(r["pair_labels"]) for r in out_rows)
    write_release(
        Path(args.out),
        {"relation.jsonl": out_rows, "rejected.jsonl": rejected, "units.jsonl": units_out},
        {
            "bucket": "public_synth",
            "generator": {"provider": "deepseek", "model": "deepseek-chat"},
            "grounded_on": "data/releases/public-materials-v1/units.jsonl",
            "spec": {
                "quota": QUOTA,
                "jira_histories": JIRA_HISTORIES,
                "per_unit": args.per_unit,
                "phenomena": {k: v[0] for k, v in PHENOMENA.items()},
                "split": "60/20/20 by (language, source document)",
            },
            "picks_by_source": dict(Counter(g["source_id"] for g, _ in picks)),
            "old_version_picks": sum(1 for _, o in picks if o),
            "labels": {f"{k[0]}:{k[1]}": v for k, v in sorted(counts.items())},
            "usage": dict(USAGE),
        },
        f"""
# public-synth-v1

Synthetic claims grounded on real public text: {len(out_rows)} claims, {pairs} claim-unit pairs,
Chinese and English. Each gold unit is a real sentence from ``public-materials-v1`` (GitHub
site-policy, Kubernetes KEPs, Public Jira Dataset, TheAgentCompany PM tasks, tau-bench
policies); old-version claims use real superseded text (a site-policy sentence a later
commit rewrote, or an earlier Jira Fix Version). The claims are written by DeepSeek from
the relation-v3 generation matrix and kept only when a label-blind DeepSeek pass agreed
(G2v; generator and reviewer share a vendor). Chinese evidence is a DeepSeek translation
of the English source, kept only when every number survived. Rejected claims:
{len(rejected)}. Split 60/20/20 by (language, source document). Same record layout as
relation-v3, plus ``grounded_on`` (locator, URL, revision) and ``transformations``.
Licences follow the sources (CC0-1.0, Apache-2.0, CC BY 4.0, MIT); see
``public-materials-v1/LICENSES``.
""",
    )
    print("records", len(out_rows), "pairs", pairs, "rejected", len(rejected), dict(counts), USAGE)


if __name__ == "__main__":
    main()
