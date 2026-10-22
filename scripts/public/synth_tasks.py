"""Synthetic data on real material for C10, C2 / C4 and C11 (where no real data fits).

    python -m scripts.public.synth_tasks reply queries intent
    python -m scripts.public.synth_tasks reply --smoke 3      # print, write nothing

Base: the real evidence units of ``public-synth-v1/units.jsonl`` (GitHub site-policy, KEPs,
Jira, TheAgentCompany, tau-bench; English originals with number-checked Chinese
translations). Units are grouped into contexts of 6 to 8 units of one document (KEPs
capped at 60 documents, long policies cut into up to 3 windows). Every family is generated
by DeepSeek from a fixed plan and kept only when a label-blind second pass agrees (G2v):

- ``public-reply-synth-v1`` (C10): a learner question and a colleague reply whose
  sentences follow a plan of ``grounded`` (restates a visible unit), ``conflict``
  (contradicts one), ``baseless`` (adds what no unit says) and, in half the replies,
  ``leak`` (discloses the colleague's internal note, a unit held out of the visible set).
  A reply is kept only when the reviewer, given the same visible units and note, labels
  every sentence as planned.
- ``public-queries-synth-v1`` (C2 / C4): questions to a knowledge assistant whose knowledge
  base is the context: ``in_direct`` / ``in_paraphrase`` (answered by a named unit),
  ``out_near`` (same topic, not answered) and ``out_far`` (unrelated). Kept when the
  reviewer, seeing only the units, picks the same answer unit or "none".
- ``public-intent-synth-v1`` (C11): what the learner says to a colleague while working with
  the context, one per intent of intent-v1 (styles rotated). Kept when the reviewer gives
  the same intent.

Split 60/20/20 by (language, document).
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict

from scripts.public.common import RELEASES, write_release
from scripts.recognition.synth import INTENTS, STYLES, USAGE, chat, parallel, split

POOL = RELEASES / "public-synth-v1" / "units.jsonl"
KEP_DOCS = 60
WINDOW = 7
MAX_WINDOWS = 3
ROLE = {
    "site-policy": ("the company's legal and compliance lead", "公司的法务合规负责人"),
    "kep": ("the release lead", "发布负责人"),
    "jira": ("the engineering lead", "研发负责人"),
    "theagentcompany": ("the team lead who assigned the task", "布置任务的团队负责人"),
    "tau-bench": ("the customer-service operations lead", "客服运营负责人"),
}
DESC = {
    "site-policy": ("a GitHub policy or terms document", "GitHub 的政策或服务条款"),
    "kep": ("a Kubernetes Enhancement Proposal record", "Kubernetes 功能提案（KEP）记录"),
    "jira": ("Jira issue records", "Jira 工单记录"),
    "theagentcompany": ("a project-management task assignment", "一份项目管理任务说明"),
    "tau-bench": ("a customer-service policy", "一份客服服务政策"),
}
REPLY_LABELS = ("grounded", "conflict", "baseless", "leak")
PLAN_TEXT = {
    "grounded": ("restate what [{u}] says, in your own words", "用自己的话转述 [{u}] 的内容"),
    "conflict": (
        "say something that contradicts [{u}] (a wrong number, a negation or the wrong object)",
        "说一句与 [{u}] 相矛盾的话（数字错、意思反了或对象错了）",
    ),
    "baseless": (
        "add a plausible detail that none of the materials contains",
        "补充一个听起来合理、但所有材料里都没有的细节",
    ),
    "leak": (
        "reveal the content of the internal note [{u}]",
        "透露内部备注 [{u}] 的内容",
    ),
}


def contexts(rng: random.Random) -> list[dict]:
    units = [json.loads(line) for line in POOL.open(encoding="utf-8")]
    by_doc = defaultdict(list)
    for u in units:
        if u["current"] and u["text_zh"]:
            by_doc[(u["source_id"], u["doc_id"])].append(u)
    docs = sorted(k for k, v in by_doc.items() if len(v) >= 5)
    keps = [d for d in docs if d[0] == "kep"]
    keep = set(rng.sample(keps, min(KEP_DOCS, len(keps)))) | {d for d in docs if d[0] != "kep"}
    out = []
    for key in sorted(keep):
        us = sorted(by_doc[key], key=lambda u: u["unit_id"])
        rng.shuffle(us)
        windows = [us[i : i + WINDOW] for i in range(0, len(us), WINDOW)]
        windows = [w for w in windows if len(w) >= 5][:MAX_WINDOWS] or [us[:WINDOW]]
        for n, window in enumerate(windows):
            out.append(
                {
                    "context_id": f"{key[0]}:{key[1]}#{n}",
                    "source_id": key[0],
                    "doc_id": key[1],
                    "units": [
                        {
                            "id": u["unit_id"],
                            "en": u["text_en"],
                            "zh": u["text_zh"],
                            "locator": u["locator"],
                            "url": u["url"],
                        }
                        for u in window
                    ],
                }
            )
    return out


def listing(units: list[dict], language: str, tag: str = "u") -> tuple[str, dict]:
    names = {}
    lines = []
    for i, u in enumerate(units, 1):
        name = f"{tag}{i}"
        names[name] = u["id"]
        lines.append(f"[{name}] {u[language]}")
    return "\n".join(lines), names


def grounded_on(ctx: dict) -> dict:
    return {
        "context_id": ctx["context_id"],
        "units": [{k: u[k] for k in ("id", "locator", "url")} for u in ctx["units"]],
    }


# ---------------------------------------------------------------- C10 replies


def reply_plan(rng: random.Random, visible: list[str], private: str | None) -> list[dict]:
    plan = [{"label": "grounded", "unit": u} for u in rng.sample(visible, rng.randint(2, 3))]
    for label in rng.sample(["conflict", "baseless"], rng.randint(1, 2)):
        unit = rng.choice(visible) if label == "conflict" else None
        plan.append({"label": label, "unit": unit})
    if private:
        plan.append({"label": "leak", "unit": private})
    rng.shuffle(plan)
    return plan


def gen_reply(ctx: dict, language: str, leak: bool, seed: float) -> dict | None:
    rng = random.Random(seed)
    zh = language == "zh"
    units = list(ctx["units"])
    rng.shuffle(units)
    private = [units.pop()] if leak else []
    visible_text, visible_names = listing(units, language)
    private_text, private_names = listing(private, language, "p")
    plan = reply_plan(rng, list(visible_names), next(iter(private_names), None))
    steps = "\n".join(
        f"{i}. " + PLAN_TEXT[p["label"]][1 if zh else 0].format(u=p["unit"])
        for i, p in enumerate(plan, 1)
    )
    role_en, role_zh = ROLE[ctx["source_id"]]
    desc_en, desc_zh = DESC[ctx["source_id"]]
    system = (
        f"你在为“同事回复核查”识别器写评测数据："
        f"{role_zh}依据{desc_zh}回答产品经理的问题。只输出 JSON。"
        if zh
        else f"You write evaluation data for a reply checker: {role_en} answers a product "
        f"manager's question based on {desc_en}. Output JSON only."
    )
    user = (
        (
            f"产品经理能看到的材料：\n{visible_text}\n"
            + (f"只有你能看到、不该透露的内部备注：\n{private_text}\n" if private else "")
            + "先写产品经理针对这些材料提的一个问题；再按下面的计划逐句写回复，顺序不变，"
            "每句自然、独立成句，不要出现方括号编号：\n"
            + steps
            + '\n输出 {"question": "...", "sentences": ["...", "..."]}，句数与计划相同。'
        )
        if zh
        else (
            f"Materials the product manager can see:\n{visible_text}\n"
            + (
                f"Internal note only you can see and must not disclose:\n{private_text}\n"
                if private
                else ""
            )
            + "First write one question the product manager asks about these materials. Then "
            "write the reply one sentence per plan step, in order; each sentence is natural, "
            "stands alone and never shows the bracketed names:\n"
            + steps
            + '\nOutput {"question": "...", "sentences": ["...", "..."]} with exactly one '
            "sentence per step."
        )
    )
    found = chat(system, user) or {}
    sentences = [s.strip() for s in found.get("sentences", []) if isinstance(s, str) and s.strip()]
    if len(sentences) != len(plan) or not (found.get("question") or "").strip():
        return None
    names = visible_names | private_names
    return {
        "question": found["question"].strip(),
        "sentences": [
            {"text": s, "label": p["label"], "unit_id": names.get(p["unit"])}
            for s, p in zip(sentences, plan, strict=True)
        ],
        "visible": [{"id": u["id"], "text": u[language]} for u in units],
        "private": [{"id": u["id"], "text": u[language]} for u in private],
    }


def review_reply(row: dict, language: str) -> list[str | None]:
    zh = language == "zh"
    visible = "\n".join(f"- {u['text']}" for u in row["visible"])
    private = "\n".join(f"- {u['text']}" for u in row["private"]) or ("（无）" if zh else "(none)")
    numbered = {str(i): s["text"] for i, s in enumerate(row["sentences"])}
    prompt = (
        "给回复里的每一句标一个标签：grounded（可见材料支持这句话）、conflict（与可见材料矛盾）、"
        "baseless（可见材料既不支持也不否定，也不是内部备注里的内容）、leak（说出了内部备注里的信息）。\n"
        f"可见材料：\n{visible}\n内部备注：\n{private}\n"
        '输出 {"labels": {"编号": "grounded|conflict|baseless|leak"}}。\n'
        if zh
        else "Label each sentence of the reply: grounded (a visible material supports it), "
        "conflict (it contradicts a visible material), baseless (the visible materials neither "
        "support nor contradict it, and it is not from the internal note), leak (it conveys "
        "information from the internal note).\n"
        f"Visible materials:\n{visible}\nInternal note:\n{private}\n"
        'Output {"labels": {"id": "grounded|conflict|baseless|leak"}}.\n'
    )
    found = (
        chat(
            "You are a careful annotator. Output JSON only.",
            prompt + json.dumps(numbered, ensure_ascii=False),
            temperature=0.0,
        )
        or {}
    )
    got = found.get("labels", {})
    return [got.get(str(i)) for i in range(len(row["sentences"]))]


def cmd_reply(ctxs: list[dict], smoke: int) -> None:
    jobs, meta = [], []
    rng = random.Random(61)
    for ctx in ctxs:
        for language in ("en", "zh"):
            for leak in (False, True):
                seed = rng.random()
                meta.append((ctx, language, leak))
                jobs.append(lambda c=ctx, lang=language, lk=leak, s=seed: gen_reply(c, lang, lk, s))
    made = parallel(jobs)
    pairs = [(m, r) for m, r in zip(meta, made, strict=True) if r]
    reviews = parallel([lambda r=r, lang=m[1]: review_reply(r, lang) for m, r in pairs])
    kept, rejected = [], []
    for ((ctx, language, leak), row), review in zip(pairs, reviews, strict=True):
        joiner = "" if language == "zh" else " "
        text, offsets, position = "", [], 0
        for i, s in enumerate(row["sentences"]):
            if i:
                text += joiner
                position += len(joiner)
            offsets.append((position, position + len(s["text"])))
            text += s["text"]
            position += len(s["text"])
        sentences = [
            s | {"index": i, "start": a, "end": b, "review": rv}
            for i, (s, (a, b), rv) in enumerate(zip(row["sentences"], offsets, review, strict=True))
        ]
        record = {
            "record_id": "",
            "language": language,
            "source_id": ctx["source_id"],
            "doc_id": ctx["doc_id"],
            "question": row["question"],
            "reply": text,
            "sentences": sentences,
            "visible": row["visible"],
            "private": row["private"],
            "has_problem": any(s["label"] != "grounded" for s in sentences),
            "has_leak": leak,
            "bucket": "public_synth",
            "label_tier": "G2v",
            "label_origin": (
                "generation plan, kept when a label-blind DeepSeek pass agreed on every sentence"
            ),
            "grounded_on": grounded_on(ctx),
            "transformations": [{"kind": "reply_authoring", "by": "deepseek-chat"}]
            + (
                [{"kind": "translation", "by": "deepseek-chat", "note": "units, numbers checked"}]
                if language == "zh"
                else []
            ),
            "publishable": True,
        }
        (kept if all(s["review"] == s["label"] for s in sentences) else rejected).append(record)
    for n, r in enumerate(kept):
        r["record_id"] = f"rs-{r['language']}-{n:05d}"
    split(kept, key_of=lambda r: (r["language"], r["doc_id"]), seed=23)
    labels = Counter((r["language"], s["label"]) for r in kept for s in r["sentences"])
    print("reply generated", len(pairs), "kept", len(kept), dict(labels), USAGE, flush=True)
    if smoke:
        for r in kept[:smoke]:
            print(
                json.dumps(
                    {k: r[k] for k in ("language", "source_id", "question")}, ensure_ascii=False
                )
            )
            for s in r["sentences"]:
                print("    ", s["label"], "|", s["text"])
        return
    write_release(
        RELEASES / "public-reply-synth-v1",
        {"replies.jsonl": kept, "rejected.jsonl": rejected},
        {
            "bucket": "public_synth",
            "task": "C10 reply check",
            "generator": {"provider": "deepseek", "model": "deepseek-chat"},
            "grounded_on": "data/releases/public-synth-v1/units.jsonl",
            "contexts": len(ctxs),
            "sentence_labels": {f"{a}:{b}": n for (a, b), n in sorted(labels.items())},
            "replies": dict(Counter(r["language"] for r in kept)),
            "usage": dict(USAGE),
        },
        f"""
# public-reply-synth-v1

Synthetic colleague replies on real material for C10, Chinese and English: {len(kept)} replies,
{sum(labels.values())} sentences ({dict(sorted(labels.items()))}). Each reply answers a
learner question about one context of 5 to 7 real evidence units (site-policy, KEP, Jira,
TheAgentCompany, tau-bench; Chinese units are number-checked DeepSeek translations).
Sentences follow a plan of ``grounded`` / ``conflict`` / ``baseless`` and, in half the
replies, ``leak`` (the colleague discloses an internal note: one unit removed from
``visible`` and given in ``private``). DeepSeek wrote them; a reply was kept only when a
label-blind DeepSeek pass, given the same visible units and note, labelled every sentence
as planned (G2v; same vendor). Rejected replies: {len(rejected)}. Fields match
``public-reply-v1`` (``reply``, ``sentences`` with offsets and labels) plus ``visible`` /
``private`` for ``check_reply``. Split 60/20/20 by (language, document).
""",
    )


# ---------------------------------------------------------------- C2 / C4 queries


def gen_queries(ctx: dict, language: str, seed: float) -> list[dict]:
    rng = random.Random(seed)
    zh = language == "zh"
    text, names = listing(ctx["units"], language)
    answer = rng.sample(list(names), 3)
    desc_en, desc_zh = DESC[ctx["source_id"]]
    asks = (
        [{"kind": "in_direct", "unit": a} for a in answer]
        + [{"kind": "in_paraphrase", "unit": a} for a in answer]
        + [{"kind": "out_near", "unit": None}] * 2
        + [{"kind": "out_far", "unit": None}]
    )
    how = {
        "in_direct": ("直接问 [{u}] 能回答的问题", "ask a question that [{u}] answers, plainly"),
        "in_paraphrase": (
            "换一种说法问 [{u}] 能回答的问题，不要照抄原文用词",
            "ask a question that [{u}] answers, in other words than the text",
        ),
        "out_near": (
            "问一个同话题、但这些材料回答不了的问题",
            "ask a question on the same topic that none of these materials answers",
        ),
        "out_far": ("问一个与这些材料无关的问题", "ask a question unrelated to these materials"),
    }
    lines = [
        f"{i}. " + how[a["kind"]][0 if zh else 1].format(u=a["unit"]) for i, a in enumerate(asks, 1)
    ]
    found = (
        chat(
            f"你在为知识助手的检索和范围判断写评测数据，知识库是{desc_zh}。只输出 JSON。"
            if zh
            else f"You write evaluation data for a knowledge assistant's retrieval and scope "
            f"check; its knowledge base is {desc_en}. Output JSON only.",
            (
                f"知识库：\n{text}\n按下面每一项各写一个用户会问的问题，不要出现方括号编号：\n"
                if zh
                else f"Knowledge base:\n{text}\nWrite one user question for each item below; "
                "never show the bracketed names:\n"
            )
            + "\n".join(lines)
            + (
                '\n输出 {"questions": ["..."]}，数量与条目相同。'
                if zh
                else '\nOutput {"questions": ["..."]}, one per item.'
            ),
        )
        or {}
    )
    qs = [q.strip() for q in found.get("questions", []) if isinstance(q, str) and q.strip()]
    if len(qs) != len(asks):
        return []
    return [
        {"query": q, "kind": a["kind"], "answer_unit_id": names.get(a["unit"]), "names": names}
        for q, a in zip(qs, asks, strict=True)
    ]


def review_queries(ctx: dict, language: str, rows: list[dict]) -> list[str | None]:
    zh = language == "zh"
    text, names = listing(ctx["units"], language)
    numbered = {str(i): r["query"] for i, r in enumerate(rows)}
    found = (
        chat(
            "You are a careful annotator. Output JSON only.",
            (
                f"知识库：\n{text}\n"
                "对每个问题，给出能回答它的那一条的编号（如 u3）；没有任何一条能回答就写 none。"
                '输出 {"answers": {"编号": "u3|none"}}。\n'
                if zh
                else f"Knowledge base:\n{text}\nFor each question give the name of the entry that "
                "answers it (e.g. u3), or none if no entry answers it. "
                'Output {"answers": {"id": "u3|none"}}.\n'
            )
            + json.dumps(numbered, ensure_ascii=False),
            temperature=0.0,
        )
        or {}
    )
    got = found.get("answers", {})
    out = []
    for i in range(len(rows)):
        v = (got.get(str(i)) or "").strip().lower()
        out.append(None if v in ("none", "") else names.get(v, "?"))
    return out


def cmd_queries(ctxs: list[dict], smoke: int) -> None:
    rng = random.Random(71)
    meta = [(c, lang, rng.random()) for c in ctxs for lang in ("en", "zh")]
    made = parallel([lambda c=c, lang=lang, s=s: gen_queries(c, lang, s) for c, lang, s in meta])
    reviews = parallel(
        [
            lambda c=c, lang=lang, r=r: review_queries(c, lang, r) if r else []
            for (c, lang, _), r in zip(meta, made, strict=True)
        ]
    )
    kept, rejected = [], []
    for (ctx, language, _), rows, review in zip(meta, made, reviews, strict=True):
        for r, answer in zip(rows, review, strict=True):
            ok = answer == r["answer_unit_id"]
            record = {
                "record_id": "",
                "query": r["query"],
                "language": language,
                "kind": r["kind"],
                "answer_unit_id": r["answer_unit_id"],
                "review": answer,
                "answerable": r["kind"].startswith("in_"),
                "domain": ctx["source_id"],
                "doc_id": ctx["doc_id"],
                "context_id": ctx["context_id"],
                "kb_unit_ids": [u["id"] for u in ctx["units"]],
                "bucket": "public_synth",
                "label_tier": "G2v",
                "label_origin": (
                    "generation plan, kept when a label-blind DeepSeek pass picked the same answer"
                ),
                "grounded_on": grounded_on(ctx),
                "publishable": True,
            }
            (kept if ok else rejected).append(record)
    for n, r in enumerate(kept):
        r["record_id"] = f"qs-{r['language']}-{n:05d}"
    split(kept, key_of=lambda r: (r["language"], r["doc_id"]), seed=29)
    counts = Counter((r["language"], r["kind"]) for r in kept)
    print("queries kept", len(kept), "rejected", len(rejected), dict(counts), USAGE, flush=True)
    if smoke:
        for r in kept[: smoke * 3]:
            print(r["language"], r["kind"], "|", r["query"])
        return
    kb = [
        {
            "context_id": c["context_id"],
            "source_id": c["source_id"],
            "doc_id": c["doc_id"],
            "units": [
                {"id": u["id"], "en": u["en"], "zh": u["zh"], "locator": u["locator"]}
                for u in c["units"]
            ],
        }
        for c in ctxs
    ]
    write_release(
        RELEASES / "public-queries-synth-v1",
        {"queries.jsonl": kept, "rejected.jsonl": rejected, "kb.jsonl": kb},
        {
            "bucket": "public_synth",
            "task": "C2 retrieval / C4 scope",
            "generator": {"provider": "deepseek", "model": "deepseek-chat"},
            "grounded_on": "data/releases/public-synth-v1/units.jsonl",
            "contexts": len(ctxs),
            "counts": {f"{a}:{b}": n for (a, b), n in sorted(counts.items())},
            "usage": dict(USAGE),
        },
        f"""
# public-queries-synth-v1

Synthetic knowledge-assistant questions over real material for C2 (retrieval) and C4
(scope), Chinese and English, in the ``assistant-queries-v1`` layout: {len(kept)} questions
({dict(sorted(counts.items()))}). The knowledge base of each question is one context of
real evidence units (``kb.jsonl``, ``kb_unit_ids``): ``in_direct`` / ``in_paraphrase`` carry
the unit that answers them, ``out_near`` asks about the same topic without an answer in
the context, ``out_far`` is unrelated. DeepSeek wrote them from a plan; a question was kept
only when a label-blind DeepSeek pass, seeing the context, picked the same unit (or none)
(G2v; same vendor). The review checks answerability only: near versus far follows the
generation plan and is not reviewed (some "far" questions stay on the document's topic).
Rejected: {len(rejected)}. Split 60/20/20 by (language, document).
""",
    )


# ---------------------------------------------------------------- C11 intent


def gen_intent(ctx: dict, language: str, seed: float) -> list[dict]:
    rng = random.Random(seed)
    zh = language == "zh"
    text, _ = listing(rng.sample(ctx["units"], min(3, len(ctx["units"]))), language)
    styles = list(STYLES)
    rng.shuffle(styles)
    asks = [
        {"intent": intent, "style": styles[i % len(styles)]} for i, intent in enumerate(INTENTS)
    ]
    lines = [
        f"{i}. "
        + (
            f"意图：{INTENTS[a['intent']][0]}；文风：{STYLES[a['style']][0]}"
            if zh
            else f"intent: {INTENTS[a['intent']][1]}; style: {STYLES[a['style']][1]}"
        )
        for i, a in enumerate(asks, 1)
    ]
    role_en, role_zh = ROLE[ctx["source_id"]]
    found = (
        chat(
            f"你在为意图识别器造数据：产品经理在处理下面的材料时对{role_zh}说的话。只输出 JSON。"
            if zh
            else f"You write data for an intent recognizer: what a product manager working with "
            f"the material below says to {role_en}. Output JSON only.",
            (
                f"材料：\n{text}\n按下面每一项各写一句话，不要出现方括号编号：\n"
                if zh
                else f"Material:\n{text}\n"
                "Write one utterance for each item; never show the bracketed names:\n"
            )
            + "\n".join(lines)
            + (
                '\n输出 {"items": ["..."]}，数量与条目相同。'
                if zh
                else '\nOutput {"items": ["..."]}, one per item.'
            ),
        )
        or {}
    )
    items = [t.strip() for t in found.get("items", []) if isinstance(t, str) and t.strip()]
    if len(items) != len(asks):
        return []
    return [{"text": t, **a} for t, a in zip(items, asks, strict=True)]


def review_intent(rows: list[dict], language: str) -> list[dict]:
    zh = language == "zh"
    labels = ", ".join(INTENTS)
    guide = "; ".join(f"{k}: {v[0] if zh else v[1]}" for k, v in INTENTS.items())
    chunks = [rows[i : i + 40] for i in range(0, len(rows), 40)]

    def job(chunk):
        def run():
            numbered = {str(i): r["text"] for i, r in enumerate(chunk)}
            found = (
                chat(
                    "你是标注员，只输出 JSON。"
                    if zh
                    else "You are an annotator. Output JSON only.",
                    (
                        f"这些是产品经理对同事说的话。给每句标一个意图（{labels}）。定义：{guide}。"
                        '输出 {"labels": {"编号": "意图"}}。\n'
                        if zh
                        else "These are things a product manager says to a colleague. Label each "
                        f"with one intent ({labels}). Definitions: {guide}. "
                        'Output {"labels": {"id": "intent"}}.\n'
                    )
                    + json.dumps(numbered, ensure_ascii=False),
                    temperature=0.0,
                )
                or {}
            )
            got = found.get("labels", {})
            return [r | {"review": got.get(str(i))} for i, r in enumerate(chunk)]

        return run

    return [r for batch in parallel([job(c) for c in chunks]) for r in batch]


def cmd_intent(ctxs: list[dict], smoke: int) -> None:
    rng = random.Random(81)
    kept, rejected = [], []
    for language in ("en", "zh"):
        meta = [(c, rng.random()) for c in ctxs]
        made = parallel([lambda c=c, s=s, lang=language: gen_intent(c, lang, s) for c, s in meta])
        rows = []
        for (ctx, _), items in zip(meta, made, strict=True):
            rows += [
                i
                | {
                    "language": language,
                    "source_id": ctx["source_id"],
                    "doc_id": ctx["doc_id"],
                    "context_id": ctx["context_id"],
                }
                for i in items
            ]
        seen, unique = set(), []
        for r in rows:
            norm = re.sub(r"\s+", "", r["text"].casefold())
            if norm not in seen:
                seen.add(norm)
                unique.append(r)
        for r in review_intent(unique, language):
            r |= {
                "bucket": "public_synth",
                "label_tier": "G2v",
                "agreed": r["review"] == r["intent"],
                "label_origin": "generation plan, kept when a label-blind DeepSeek pass agreed",
            }
            (kept if r["agreed"] else rejected).append(r)
    split(kept, key_of=lambda r: (r["language"], r["doc_id"]), seed=31)
    counts = Counter((r["language"], r["intent"]) for r in kept)
    print("intent kept", len(kept), "rejected", len(rejected), dict(counts), USAGE, flush=True)
    if smoke:
        for r in kept[: smoke * 5]:
            print(r["language"], r["intent"], r["style"], "|", r["text"])
        return
    write_release(
        RELEASES / "public-intent-synth-v1",
        {"intent.jsonl": kept, "rejected.jsonl": rejected},
        {
            "bucket": "public_synth",
            "task": "C11 intent",
            "generator": {"provider": "deepseek", "model": "deepseek-chat"},
            "grounded_on": "data/releases/public-synth-v1/units.jsonl",
            "intents": list(INTENTS),
            "styles": list(STYLES),
            "counts": {f"{a}:{b}": n for (a, b), n in sorted(counts.items())},
            "usage": dict(USAGE),
        },
        f"""
# public-intent-synth-v1

Synthetic learner-to-colleague utterances for C11, Chinese and English, in the intent-v1
layout (``text``, ``intent``, ``style``, ``language``, ``review``, ``split``): {len(kept)}
utterances ({dict(sorted(counts.items()))}). Same five intents and four styles as
intent-v1, but each utterance is written while the product manager works with a context of
real material (site-policy, KEP, Jira, TheAgentCompany, tau-bench) instead of the pm_pilot
scenario, so it tests whether C11 carries over to other workplace topics. No public dataset
uses these five labels, hence synthetic. DeepSeek wrote them; kept only when a label-blind
DeepSeek pass gave the same intent (G2v; same vendor). Rejected: {len(rejected)}. Split
60/20/20 by (language, document).
""",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("families", nargs="+", choices=["reply", "queries", "intent"])
    parser.add_argument("--smoke", type=int, default=0)
    args = parser.parse_args()
    ctxs = contexts(random.Random(53))
    if args.smoke:
        ctxs = random.Random(1).sample(ctxs, args.smoke)
    print("contexts", len(ctxs), Counter(c["source_id"] for c in ctxs), flush=True)
    for family in args.families:
        {"reply": cmd_reply, "queries": cmd_queries, "intent": cmd_intent}[family](ctxs, args.smoke)


if __name__ == "__main__":
    main()
