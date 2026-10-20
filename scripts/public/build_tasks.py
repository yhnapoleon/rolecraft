"""Real public data for the recognisers that had only synthetic data (C10, C4, C2, C5).

    .venv/Scripts/python.exe -m scripts.public.build_tasks [reply scope retrieval sequence]

Nothing here is written or labelled by a model; labels are the source datasets' own.

- ``public-reply-v1`` (C10 reply check): RAGTruth. ``sources.jsonl`` holds each source
  document cut into units (QA passages, news articles, Yelp business records);
  ``replies.jsonl`` holds the 17,790 LLM responses cut with the product's
  ``split_sentences``, each sentence labelled by the human word-level spans it overlaps:
  ``conflict`` (Evident / Subtle Conflict), ``baseless`` (Evident / Subtle Baseless Info) or
  ``grounded``. Official train / test (disjoint by source); dev = 10 % of train sources.
- ``public-scope-v1`` (C4 scope): CLINC150 (en; 150 in-scope intents + out-of-scope
  queries, official splits) and MASSIVE zh-CN + en-US (parallel; scenarios split into
  in-scope office tasks, near out-of-scope assistant tasks and far out-of-scope chit-chat /
  general knowledge). Same field names as ``assistant-queries-v1``.
- ``public-retrieval-v1`` (C2 retrieval): PrivacyQA (en). ``policies.jsonl`` = policy
  segments as units, ``queries.jsonl`` = real user questions with the expert-relevant
  segments and an ``answerable`` flag. Official train / test; dev = 10 % of train apps.
- ``public-sequence-v1`` (C5 behaviour): tau-bench agent runs and Jira issue histories as
  symbol sequences with real outcomes (environment reward; final resolution).
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import sys
import tarfile
from collections import Counter, defaultdict

from career_lab.models.v3.units import split_sentences
from scripts.public.common import RAW, RELEASES, copy_license, source_of, unit_id, write_release

MASSIVE_IN = {"calendar", "email", "lists", "datetime", "alarm"}
MASSIVE_FAR = {"general", "qa"}


def dev_of(key: str, share: float = 0.1, salt: str = "") -> bool:
    return random.Random(f"{salt}{key}").random() < share


def sources_block(ids: list[str]) -> dict:
    return {
        s: {
            k: source_of(s).get(k)
            for k in ("page", "url", "commit", "revision", "license", "license_sha256", "citation")
        }
        for s in ids
    }


# ---------------------------------------------------------------- C10: RAGTruth


def flatten(value, prefix: str = "") -> list[str]:
    """Yelp business record -> one line per field (reviews: one unit per sentence)."""
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "review_info" and isinstance(item, list):
                for n, review in enumerate(item):
                    stars, date = review.get("review_stars"), review.get("review_date", "")[:10]
                    head = f"Review {n + 1} ({stars} stars, {date})"
                    for s in split_sentences(review.get("review_text") or ""):
                        lines.append(f"{head}: {s.text}")
            elif isinstance(item, dict):
                parts = [f"{k}: {v}" for k, v in item.items() if v is not None]
                if parts:
                    lines.append(f"{prefix}{key}: " + "; ".join(parts))
            elif item is not None:
                lines.append(f"{prefix}{key}: {item}")
    return lines


def ragtruth_units(task: str, info) -> tuple[str | None, list[str]]:
    if task == "QA":
        texts = []
        for passage in re.split(r"passage \d+:", info["passages"]):
            texts += [s.text for s in split_sentences(passage.strip())]
        return info["question"], texts
    if task == "Summary":
        return None, [s.text for s in split_sentences(info)]
    return None, flatten(info)


def reply() -> None:
    out = RELEASES / "public-reply-v1"
    base = RAW / "ragtruth" / "repo" / "dataset"
    raw_sources = {}
    for line in (base / "source_info.jsonl").open(encoding="utf-8"):
        o = json.loads(line)
        raw_sources[o["source_id"]] = o
    responses = [json.loads(line) for line in (base / "response.jsonl").open(encoding="utf-8")]
    split_of = {}
    for r in responses:
        official = r["split"]
        split_of[r["source_id"]] = (
            "test"
            if official == "test"
            else "dev"
            if dev_of(r["source_id"], salt="rt")
            else "train"
        )
    sources = []
    for sid, o in sorted(raw_sources.items(), key=lambda kv: int(kv[0])):
        question, texts = ragtruth_units(o["task_type"], o["source_info"])
        seen, units = set(), []
        for n, text in enumerate(texts):
            text = text.strip()
            if text and text not in seen:
                seen.add(text)
                units.append({"id": unit_id("ragtruth", sid, n, text), "text": text})
        sources.append(
            {
                "source_id": sid,
                "task_type": o["task_type"],
                "origin": o["source"],
                "question": question,
                "units": units,
                "split": split_of.get(sid, "train"),
            }
        )
    replies = []
    for r in responses:
        spans = r["labels"]
        sentences = []
        for n, s in enumerate(split_sentences(r["response"])):
            hit = [x for x in spans if x["start"] < s.end and x["end"] > s.start]
            kinds = sorted({x["label_type"] for x in hit})
            label = (
                "conflict"
                if any("Conflict" in k for k in kinds)
                else "baseless"
                if kinds
                else "grounded"
            )
            sentences.append(
                {
                    "index": n,
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "label": label,
                    "span_types": kinds,
                    "implicit_true": any(x.get("implicit_true") for x in hit),
                }
            )
        replies.append(
            {
                "record_id": f"rt-{r['id']}",
                "source_id": r["source_id"],
                "task_type": raw_sources[r["source_id"]]["task_type"],
                "language": "en",
                "model": r["model"],
                "quality": r["quality"],
                "reply": r["response"],
                "sentences": sentences,
                "has_problem": any(x["label"] != "grounded" for x in sentences),
                "spans": spans,
                "split": split_of[r["source_id"]],
                "bucket": "public_real",
                "label_tier": "G1",
                "label_origin": "RAGTruth human word-level hallucination spans",
                "publishable": True,
            }
        )
    copy_license(out, "ragtruth")
    counts = Counter((r["split"], s["label"]) for r in replies for s in r["sentences"])
    write_release(
        out,
        {"sources.jsonl": sources, "replies.jsonl": replies},
        {
            "bucket": "public_real",
            "task": "C10 reply check",
            "sources": sources_block(["ragtruth"]),
            "replies_by_split": dict(Counter(r["split"] for r in replies)),
            "sentence_labels": {f"{k[0]}:{k[1]}": v for k, v in sorted(counts.items())},
            "task_types": dict(Counter(r["task_type"] for r in replies)),
        },
        f"""
# public-reply-v1

Real data for C10 (is each sentence of a reply grounded in what the speaker could see?):
RAGTruth, 17,790 responses of six LLMs (GPT-4, GPT-3.5, Llama-2 7/13/70B chat, Mistral-7B)
to 2,965 source documents (MS MARCO QA passages, CNN/DM and recent news to summarise,
Yelp business records to describe), with human word-level hallucination spans.

- ``sources.jsonl``: one row per source document; ``units`` = its sentences (QA passages,
  articles) or one line per field / review sentence (Yelp records); QA rows keep the
  ``question``. These are the ``visible`` sources of ``check_reply``.
- ``replies.jsonl``: one row per response, cut with the product's ``split_sentences``.
  Sentence label: ``conflict`` if it overlaps an Evident / Subtle Conflict span,
  ``baseless`` if it overlaps an Evident / Subtle Baseless Info span, else ``grounded``;
  ``span_types`` and ``implicit_true`` (baseless but true) are kept, and the raw spans too.

Sentence labels by split: {dict(sorted(counts.items()))}. Official train / test are
disjoint by source; dev is 10 % of the train sources. No leak cases (RAGTruth has no
private facts) and English only; ``public-reply-synth-v1`` adds both. Licence MIT.
""",
    )
    print("reply", len(sources), "sources", len(replies), "replies", dict(counts))


# ---------------------------------------------------------------- C4: CLINC150 + MASSIVE


def scope() -> None:
    out = RELEASES / "public-scope-v1"
    data = json.loads((RAW / "clinc150/repo/data/data_full.json").read_text(encoding="utf-8"))
    domains = json.loads((RAW / "clinc150/repo/data/domains.json").read_text(encoding="utf-8"))
    domain_of = {intent: d for d, intents in domains.items() for intent in intents}
    clinc = []
    for key, rows in data.items():
        split = {"train": "train", "val": "dev", "test": "test"}[key.replace("oos_", "")]
        for n, (text, intent) in enumerate(rows):
            inside = intent != "oos"
            clinc.append(
                {
                    "record_id": f"clinc-{key}-{n}",
                    "query": text,
                    "language": "en",
                    "kind": "in_direct" if inside else "out",
                    "answerable": inside,
                    "intent": intent,
                    "domain": domain_of.get(intent, "oos"),
                    "split": split,
                    "source_id": "clinc150",
                    "bucket": "public_real",
                    "label_tier": "G1",
                }
            )
    massive = []
    archive = tarfile.open(RAW / "massive" / "amazon-massive-dataset-1.1.tar.gz")
    for locale, language in (("zh-CN", "zh"), ("en-US", "en")):
        member = archive.extractfile(f"1.1/data/{locale}.jsonl")
        for line in io.TextIOWrapper(member, encoding="utf-8"):
            o = json.loads(line)
            scenario = o["scenario"]
            kind = (
                "in_direct"
                if scenario in MASSIVE_IN
                else "out_far"
                if scenario in MASSIVE_FAR
                else "out_near"
            )
            massive.append(
                {
                    "record_id": f"massive-{locale}-{o['id']}",
                    "parallel_id": o["id"],
                    "query": o["utt"],
                    "language": language,
                    "kind": kind,
                    "answerable": kind == "in_direct",
                    "domain": scenario,
                    "intent": o["intent"],
                    "annot_utt": o["annot_utt"],
                    "split": o["partition"],
                    "source_id": "massive",
                    "bucket": "public_real",
                    "label_tier": "G1",
                }
            )
    for source in ("clinc150", "massive"):
        copy_license(out, source)
    count = {
        "clinc150": dict(Counter((r["split"], r["kind"]) for r in clinc)),
        "massive": dict(Counter((r["language"], r["kind"]) for r in massive)),
    }
    write_release(
        out,
        {"clinc150.jsonl": clinc, "massive.jsonl": massive},
        {
            "bucket": "public_real",
            "task": "C4 scope",
            "sources": sources_block(["clinc150", "massive"]),
            "massive_partition": {
                "in_direct": sorted(MASSIVE_IN),
                "out_far": sorted(MASSIVE_FAR),
                "out_near": "every other scenario",
            },
            "counts": {
                k: {f"{a}:{b}": n for (a, b), n in sorted(v.items())} for k, v in count.items()
            },
        },
        f"""
# public-scope-v1

Real data for C4 (is a question inside the assistant's scope?), in the field layout of
``assistant-queries-v1`` (``query``, ``language``, ``kind``, ``answerable``, ``domain``,
``split``).

- ``clinc150.jsonl`` (en): CLINC150 ``data_full``, 150 in-scope intents in 10 domains
  (``kind = in_direct``) and the out-of-scope queries (``kind = out``); official
  train / val (= dev) / test. The standard benchmark for out-of-scope detection.
- ``massive.jsonl`` (zh, en): MASSIVE 1.1 zh-CN and en-US, utterance-parallel
  (``parallel_id``). Scenarios are partitioned for a scope test: office tasks
  {sorted(MASSIVE_IN)} are in scope; chit-chat and general knowledge {sorted(MASSIVE_FAR)} are far
  out of scope; the other assistant tasks are near out of scope. Official partitions. Slot
  annotations (``annot_utt``) are kept.

Counts: {count}. The partition is ours (documented in the manifest); ``domain`` keeps
the original scenario so another split can be drawn. Licences: CLINC150 CC BY 3.0, MASSIVE
CC BY 4.0.
""",
    )
    print("scope", count)


# ---------------------------------------------------------------- C2: PrivacyQA


def retrieval() -> None:
    out = RELEASES / "public-retrieval-v1"
    csv.field_size_limit(10**8)
    base = RAW / "privacyqa/repo/data"
    segments: dict[str, dict[int, str]] = defaultdict(dict)
    queries: dict[str, dict] = {}
    inconsistent = 0
    for name in ("policy_train_data.csv", "policy_test_data.csv"):
        with (base / name).open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                doc, qid = row["DocID"].strip(), row["QueryID"].strip()
                index = int(row["SentID"].strip().rsplit("_", 1)[1])
                text = re.sub(r"\s+", " ", row["Segment"]).strip()
                if index in segments[doc] and segments[doc][index] != text:
                    inconsistent += 1
                segments[doc].setdefault(index, text)
                q = queries.setdefault(
                    qid,
                    {
                        "query": row["Query"].strip(),
                        "doc": doc,
                        "official": row["Split"].strip(),
                        "any": set(),
                        "votes": defaultdict(list),
                    },
                )
                if row["Split"].strip() == "train":
                    if row["Label"].strip() == "Relevant":
                        q["any"].add(index)
                else:
                    if row["Any_Relevant"].strip() == "Relevant":
                        q["any"].add(index)
                    votes = [row[f"Ann{i}"].strip() for i in range(1, 7)]
                    q["votes"][index] = [v for v in votes if v in ("Relevant", "Irrelevant")]
    policies = [
        {
            "doc_id": doc,
            "units": [
                {"id": unit_id("privacyqa", doc, i), "text": t}
                for i, t in sorted(units.items())
                if t
            ],
        }
        for doc, units in sorted(segments.items())
    ]
    rows = []
    for qid, q in sorted(queries.items()):
        majority = [
            i for i, v in q["votes"].items() if v and sum(x == "Relevant" for x in v) * 2 > len(v)
        ]
        split = q["official"]
        if split == "train" and dev_of(q["doc"], salt="pqa"):
            split = "dev"
        rows.append(
            {
                "record_id": f"pqa-{qid}",
                "query": q["query"],
                "language": "en",
                "doc_id": q["doc"],
                "relevant_unit_ids": [unit_id("privacyqa", q["doc"], i) for i in sorted(q["any"])],
                "relevant_majority_unit_ids": [
                    unit_id("privacyqa", q["doc"], i) for i in sorted(majority)
                ]
                if q["votes"]
                else None,
                "answerable": bool(q["any"]),
                "kind": "in_direct" if q["any"] else "out_near",
                "split": split,
                "source_id": "privacyqa",
                "bucket": "public_real",
                "label_tier": "G1",
                "label_origin": "PrivacyQA expert relevance (test: any of up to six annotators)",
            }
        )
    copy_license(out, "privacyqa")
    count = dict(Counter((r["split"], r["answerable"]) for r in rows))
    write_release(
        out,
        {"policies.jsonl": policies, "queries.jsonl": rows},
        {
            "bucket": "public_real",
            "task": "C2 retrieval (and C4 answerability)",
            "sources": sources_block(["privacyqa"]),
            "policies": len(policies),
            "units": sum(len(p["units"]) for p in policies),
            "queries": {f"{a}:{b}": n for (a, b), n in sorted(count.items())},
            "inconsistent_segments": inconsistent,
        },
        f"""
# public-retrieval-v1

Real data for C2 (find the policy sentence that answers a question) and for answerability:
PrivacyQA, questions that crowdworkers asked about 35 mobile apps' privacy policies,
with the policy segments that legal experts marked relevant.

- ``policies.jsonl``: one row per policy, ``units`` = its segments.
- ``queries.jsonl``: ``query``, ``doc_id``, ``relevant_unit_ids`` (train: the expert
  label; test: relevant for any of up to six annotators), ``relevant_majority_unit_ids``
  (test only), ``answerable`` (some segment is relevant) and ``kind`` (``in_direct`` when
  answerable, ``out_near`` when the policy does not answer it: same topic, not covered).

Counts (split, answerable): {count}. Official train / test; dev is 10 % of the train apps.
English only; ``public-queries-synth-v1`` adds Chinese questions over real material.
Licence MIT.
""",
    )
    print("retrieval", len(policies), "policies", count, "inconsistent", inconsistent)


# ---------------------------------------------------------------- C5: sequences


def tau_symbols(steps: list[dict]) -> list[str]:
    out = []
    for step in steps:
        if step["role"] == "user":
            out.append("user")
        elif step["role"] == "assistant":
            calls = step.get("tool_calls") or []
            out += [f"tool:{c['name']}" for c in calls] or ["reply"]
    return out


def jira_symbol(item: dict) -> str:
    field, frm, to = item["field"], item.get("from"), item.get("to")
    if field == "status":
        return f"status:{(to or '').strip().lower().replace(' ', '_')}"
    if field == "resolution":
        return f"resolution:{(to or 'cleared').strip().lower().replace(' ', '_')}"
    if field in ("Fix Version", "Version", "duedate"):
        name = {"Fix Version": "fix_version", "Version": "affects_version", "duedate": "due_date"}[
            field
        ]
        return f"{name}:{'move' if frm and to else 'set' if to else 'clear'}"
    if field == "assignee":
        return "assignee:set" if to else "assignee:clear"
    return field.lower().replace(" ", "_")


def sequence() -> None:
    out = RELEASES / "public-sequence-v1"
    materials = RELEASES / "public-materials-v1"
    tau = []
    for line in (materials / "trajectory-taubench.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        seq = tau_symbols(r["steps"])
        group = f"{r['domain']}-{r['task_id']}"
        tau.append(
            {
                "record_id": r["record_id"],
                "source_id": "tau-bench",
                "executor": r["executor"],
                "domain": r["domain"],
                "task_id": r["task_id"],
                "trial": r["trial"],
                "sequence": seq,
                "length": len(seq),
                "label": "success" if r["outcome"]["success"] else "failure",
                "reward": r["outcome"]["reward"],
                "split": "test" if dev_of(group, 0.2, "tau") else "train",
                "group": group,
                "bucket": "public_real",
                "label_tier": "G1",
                "label_origin": "tau-bench environment reward",
            }
        )
    jira = []
    for line in (materials / "trajectory-jira.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        seq = [jira_symbol(i) for step in r["steps"] for i in step["changes"]]
        resolution = (r["outcome"]["resolution"] or "unresolved").lower()
        label = (
            "fixed"
            if resolution in ("fixed", "done", "resolved", "completed")
            else ("unresolved" if resolution == "unresolved" else "closed_other")
        )
        jira.append(
            {
                "record_id": r["record_id"],
                "source_id": "jira",
                "executor": "human_team",
                "collection": r["collection"],
                "project": r["project"]["key"],
                "sequence": seq,
                "length": len(seq),
                "label": label,
                "resolution": r["outcome"]["resolution"],
                "status": r["outcome"]["status"],
                "days_to_resolve": r["outcome"]["days_to_resolve"],
                "fix_version_moves": r["features"]["fix_version_moves"],
                "split": "test" if dev_of(r["project"]["key"], 0.2, "jira") else "train",
                "group": r["project"]["key"],
                "bucket": "public_real",
                "label_tier": "G1",
                "label_origin": "final Jira resolution",
            }
        )
    for source in ("tau-bench", "jira"):
        if source == "jira":
            (out / "LICENSES").mkdir(parents=True, exist_ok=True)
            (out / "LICENSES" / "jira-LICENSE-CCBY4.0.md").write_bytes(
                (RAW / "jira" / "LICENSE-CCBY4.0.md").read_bytes()
            )
        else:
            copy_license(out, source)
    count = {
        "tau-bench": dict(Counter((r["split"], r["label"]) for r in tau)),
        "jira": dict(Counter((r["split"], r["label"]) for r in jira)),
    }
    write_release(
        out,
        {"taubench.jsonl": tau, "jira.jsonl": jira},
        {
            "bucket": "public_real",
            "task": "C5 behaviour sequences",
            "sources": sources_block(["tau-bench", "jira"]),
            "counts": {
                k: {f"{a}:{b}": n for (a, b), n in sorted(v.items())} for k, v in count.items()
            },
            "vocabulary": {
                "tau-bench": sorted({s for r in tau for s in r["sequence"]}),
                "jira": sorted({s for r in jira for s in r["sequence"]}),
            },
        },
        f"""
# public-sequence-v1

Real behaviour sequences with real outcomes for C5 (DTW / HMM / n-gram methods), in the
``sequence`` layout of ``trajectories-v1`` but with each source's own symbol vocabulary.

- ``taubench.jsonl``: tau-bench historical runs (gpt-4o and claude-3.5-sonnet, airline and
  retail). Symbols: ``user`` (a customer turn), ``tool:<name>`` (each tool call),
  ``reply`` (an agent message without a call). Label: ``success`` when the environment
  reward is 1. Split 80/20 by (domain, task), so trials of one task never cross.
- ``jira.jsonl``: the 400 public-materials Jira issues; symbols from the change log
  (``status:<to>``, ``fix_version:set|move|clear``, ``assignee:set|clear``, ...). Label:
  ``fixed`` / ``closed_other`` / ``unresolved`` from the final resolution. Split 80/20 by
  project.

Counts: {count}. Licences: tau-bench MIT, Public Jira Dataset CC BY 4.0.
""",
    )
    print("sequence", count)


if __name__ == "__main__":
    for name in sys.argv[1:] or ["reply", "scope", "retrieval", "sequence"]:
        {"reply": reply, "scope": scope, "retrieval": retrieval, "sequence": sequence}[name]()
