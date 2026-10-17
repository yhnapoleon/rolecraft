"""Scripted strategy runner: drive a real backend over HTTP to produce behaviour trajectories.

    python -m scripts.recognition.run_strategies --strategy all --count 40 --language zh \
        --api http://127.0.0.1:18572 --out data/releases/trajectories-v1/raw-zh.jsonl

Eight strategies, each a function of a seeded RNG that randomises the order of reads,
the wording of questions and the numbers it uses. Every step is a public HTTP call (new
session, read material, ask a colleague, configure, test, request resources, refresh the
index, submit, revise). After the run the session's symbol sequence is read back from
``GET /sessions/{id}/behavior`` so the labels are the product's own symbolisation. The
same sessions are later exported for C1 real work sentences (their request ids are kept).

Strategy labels are the ground truth for C5 strategy recognition; anomaly labels come
from what the strategy deliberately does (and agree with the rule detector by design).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.recognition.client import DEFAULT_API, Session

STRATEGIES: dict[str, Callable] = {}


def strategy(name: str):
    def wrap(fn):
        STRATEGIES[name] = fn
        return fn

    return wrap


# ---- wording pools --------------------------------------------------------------------

QUESTIONS = {
    "zh": {
        "ask_limit": [
            "试点最多能上多少人？",
            "现在的容量上限是多少？",
            "这次试点的人数有没有硬性限制？",
            "如果邀请{n}人，会不会超出容量？",
        ],
        "ask_resource": [
            "开发这边还剩几个人日？",
            "要上线需要多少开发资源？",
            "第{d}天之前能排出开发时间吗？",
            "资源不够的话要找谁？",
        ],
        "ask_process": [
            "申请扩容的流程是怎样的？",
            "我下一步应该先做什么？",
            "政策更新以后索引要怎么处理？",
            "怎么验证助手的回答是最新的？",
        ],
        "seek_approval": [
            "能不能批准我们先开放给{n}人？",
            "我想申请{d}个人日，你同意吗？",
            "这个方案你能签字放行吗？",
        ],
    },
    "en": {
        "ask_limit": [
            "How many people can the pilot take at most?",
            "What is the current capacity limit?",
            "Is there a hard cap on pilot participants?",
            "If we invite {n} people, will we exceed capacity?",
        ],
        "ask_resource": [
            "How many developer days are left?",
            "How much development effort does launch need?",
            "Can we get development time before day {d}?",
            "Who do I talk to if we lack resources?",
        ],
        "ask_process": [
            "What is the process for requesting more capacity?",
            "What should I do next?",
            "After a policy update, how should the index be handled?",
            "How do I check the assistant's answers are current?",
        ],
        "seek_approval": [
            "Can you approve opening it to {n} people first?",
            "I'd like to request {d} developer days. Do you agree?",
            "Can you sign off on this plan?",
        ],
    },
}
TESTS = {
    "zh": {
        "normal": [
            "会议室怎么预约？",
            "新员工账号没开通怎么办？",
            "忘记密码怎么重置？",
            "办公网络怎么连接？",
        ],
        "policy": [
            "住宿报销上限是多少？",
            "出差打车能报多少？",
            "餐费报销标准是什么？",
            "酒店超标怎么审批？",
        ],
        "oos": ["火星今天天气怎么样？", "帮我写一首诗", "明天股市会涨吗？", "推荐一部电影"],
    },
    "en": {
        "normal": [
            "How do I book a meeting room?",
            "My new account is not activated. What should I do?",
            "How do I reset my password?",
            "How do I connect to the office network?",
        ],
        "policy": [
            "What is the hotel reimbursement limit?",
            "How much can I claim for a taxi on a business trip?",
            "What is the meal allowance?",
            "How do I get approval for a hotel above the cap?",
        ],
        "oos": [
            "What is the weather on Mars today?",
            "Write me a poem",
            "Will the stock market go up tomorrow?",
            "Recommend a movie",
        ],
    },
}
WORK = {
    "zh": [
        "首批只开放给{groups}，共{n}人，不超过当前容量{cap}人。",
        "开发资源按{d}人日安排，第{day}天正式试点。",
        "住宿报销以最新政策为准，上限每晚{hotel}元。",
        "政策更新后需要刷新索引并重新测试政策问答。",
        "超出容量的部分先申请扩容，获批前不开放。",
        "保留人工兜底，助手答不了的问题转人工。",
        "未确认的条件：{unknown}。",
    ],
    "en": [
        (
            "The first wave opens only to {groups}, {n} people in total, within the current "
            "capacity of {cap}."
        ),
        "Development is planned at {d} developer days, with the pilot starting on day {day}.",
        "Hotel claims follow the latest policy, capped at CNY {hotel} per night.",
        "After a policy update we refresh the index and retest the policy questions.",
        "Anything above capacity waits for an approved capacity request.",
        "Keep a human fallback for questions the assistant cannot answer.",
        "Unconfirmed conditions: {unknown}.",
    ],
}
GROUPS = {
    "zh": ["新员工组", "运营组", "行政组"],
    "en": ["the new-hire group", "operations", "admin"],
}
UNKNOWN = {
    "zh": ["行政组是否愿意参加", "技术负责人能否加班", "政策是否还会调整"],
    "en": [
        "whether admin will join",
        "whether the tech lead can add hours",
        "whether the policy changes again",
    ],
}
READS_CORE = [
    "brief",
    "demand",
    "business_case",
    "technical",
    "approvals",
    "user_groups",
    "interviews",
]
READS_KB = ["faq", "policy", "onboarding"]


# ---- runner -----------------------------------------------------------------------------


class Run:
    def __init__(self, api: str, language: str, rng: random.Random):
        self.s = Session(api, language)
        self.lang = language
        self.rng = rng
        self.products: list[dict] = []
        self.submissions: list[dict] = []
        self.last_request: str | None = None
        self.steps: list[str] = []
        self.fragments: dict[str, list] = {}

    # verbs
    def read(self, material: str):
        try:
            read = self.s.read(material)
            self.fragments[material] = read["result"]["fragments"]
            self.steps.append("read:" + material)
        except RuntimeError:
            self.steps.append("read_failed:" + material)

    def ask(self, role: str, intent: str):
        text = self.rng.choice(QUESTIONS[self.lang][intent]).format(
            n=self.rng.choice([20, 30, 40, 50, 60]), d=self.rng.choice([3, 4, 5, 6, 7])
        )
        made = self.s.ask(role, text)
        self.last_request = made["_request_id"]
        self.steps.append(f"ask:{role}:{intent}")
        # The role_turn object is the symbol; the reply is generated by the worker later.

    def configure(self, **settings: Any):
        config = self.workspace()["config"]
        base = {
            "schema_version": 2,
            "session_id": self.s.session_id,
            "kind": "config",
            "object_id": config["id"],
            "version": config["version"],
            "config_version": config["config_version"],
        }
        self.s.send("configuration", "configuration.apply", {"base": base, "settings": settings})
        self.steps.append("configure")

    def workspace(self) -> dict:
        body = self.s.get("timeline")
        while isinstance(body.get("result"), dict):
            body = body["result"]
        return body["workspace"]

    def test(self, kind: str):
        config_version = self.workspace()["config"]["config_version"]
        self.s.test(self.rng.choice(TESTS[self.lang][kind]), config_version=config_version)
        self.steps.append("test:" + kind)

    def request(self, **terms: int):
        reason = "按方案申请资源" if self.lang == "zh" else "Resources for the plan"
        made = self.s.send(
            "actions",
            "request_business",
            {"tool": "request_business", "terms": terms, "reason": reason},
        )["result"]["request"]
        self.steps.append("request:" + ",".join(terms))
        return made

    def resolve(self, made: dict):
        try:
            self.s.send(
                "approvals/resolve",
                "resolve_approval",
                {"request": made, "expected_request_revision": made["version"]},
            )
            self.steps.append("resolve")
        except RuntimeError as error:
            self.steps.append("resolve_failed:" + str(error)[:40])

    def refresh(self):
        try:
            self.s.send("actions", "refresh_index", {"tool": "refresh_index"})
            self.steps.append("refresh_index")
        except RuntimeError:
            self.steps.append("refresh_failed")

    def work_text(self, n: int, cap: int = 30, d: int = 3, day: int = 7, hotel: int = 500) -> str:
        lines = list(WORK[self.lang])
        self.rng.shuffle(lines)
        keep = lines[: self.rng.randint(4, len(lines))]
        groups = (
            "、".join(self.rng.sample(GROUPS[self.lang], 2))
            if self.lang == "zh"
            else " and ".join(self.rng.sample(GROUPS[self.lang], 2))
        )
        return "\n\n".join(
            line.format(
                groups=groups,
                n=n,
                cap=cap,
                d=d,
                day=day,
                hotel=hotel,
                unknown=self.rng.choice(UNKNOWN[self.lang]),
            )
            for line in keep
        )

    def submit(self, decision: str, n: int, wait: bool = False, **numbers: int):
        brief = self.fragments.get("brief") or self.s.read("brief")["result"]["fragments"]
        product = self.s.draft(self.work_text(n, **numbers), [brief[min(1, len(brief) - 1)]["ref"]])
        made = self.s.submit([product], decision=decision)
        self.products.append(product)
        self.submissions.append(made["result"]["submission"])
        self.steps.append("submit")
        if wait:
            try:
                self.s.wait_request(made["_request_id"], timeout=600)
            except TimeoutError:
                pass

    def revise(self):
        parent = self.submissions[-1]
        reason = "根据反馈修订方案" if self.lang == "zh" else "Revise after feedback"
        try:
            self.s.send(
                "revision-cycles",
                "begin_revision",
                {"parent_submission": parent, "reason": reason},
            )
            self.steps.append("revise")
        except RuntimeError as error:
            self.steps.append("revise_failed:" + str(error)[:40])


# ---- strategies -------------------------------------------------------------------------


@strategy("thorough")
def thorough(r: Run):
    reads = READS_CORE[:]
    r.rng.shuffle(reads)
    for m in reads[:5] + ["policy"]:
        r.read(m)
    r.ask("tech_lead", "ask_limit")
    r.ask("business_lead", "ask_resource")
    r.configure(participants=30)
    for kind in r.rng.sample(["normal", "normal", "policy"], 3):
        r.test(kind)
    r.submit("launch_narrow", 30)


@strategy("request_first")
def request_first(r: Run):
    for m in ["brief", "technical", "approvals"]:
        r.read(m)
    r.ask("supervisor", "ask_process")
    made = r.request(capacity=r.rng.choice([50, 60]))
    r.resolve(made)
    r.configure(participants=50)
    r.test("normal")
    r.test("policy")
    r.submit("launch", 50, cap=60)


@strategy("test_heavy")
def test_heavy(r: Run):
    for m in ["brief", "faq", "policy"]:
        r.read(m)
    r.configure(participants=20, update_strategy=r.rng.choice(["daily", "realtime"]))
    for _ in range(r.rng.randint(4, 6)):
        r.test(r.rng.choice(["normal", "policy", "oos"]))
    r.refresh()
    r.test("policy")
    r.submit("launch_narrow", 20)


@strategy("rush")
def rush(r: Run):
    r.read("brief")
    if r.rng.random() < 0.5:
        r.test("normal")
    r.submit(r.rng.choice(["launch", "defer_with_conditions"]), 50)


@strategy("ask_heavy")
def ask_heavy(r: Run):
    r.read("brief")
    pairs = [
        ("tech_lead", "ask_limit"),
        ("business_lead", "ask_resource"),
        ("supervisor", "ask_process"),
        ("tech_lead", "ask_process"),
        ("business_lead", "seek_approval"),
    ]
    r.rng.shuffle(pairs)
    for role, intent in pairs[: r.rng.randint(3, 5)]:
        r.ask(role, intent)
    r.read("technical")
    r.configure(participants=30)
    r.test("normal")
    r.submit("defer_with_conditions", 30)


@strategy("unread_request")
def unread_request(r: Run):
    """Anomalies: requests before reading technical; configures before approval."""
    r.read("brief")
    made = r.request(capacity=r.rng.choice([60, 100]))
    r.configure(participants=50)
    r.resolve(made)
    r.test("normal")
    r.submit("launch", 50)


@strategy("policy_untested")
def policy_untested(r: Run):
    """Anomaly: the index / policy changes and the learner submits without retesting."""
    for m in ["brief", "policy", "technical"]:
        r.read(m)
    r.configure(participants=30, update_strategy="daily")
    r.test("policy")
    r.refresh()
    r.read("policy")
    r.submit("launch_narrow", 30)


@strategy("revise_loop")
def revise_loop(r: Run):
    for m in ["brief", "technical", "approvals"]:
        r.read(m)
    r.configure(participants=40)
    r.test("normal")
    r.submit("launch", 40, wait=True)
    r.revise()
    r.configure(participants=30)
    r.test("policy")
    r.submit("launch_narrow", 30)


EXPECTED_ANOMALIES = {
    "unread_request": ["request_before_technical", "configured_before_approval"],
    "policy_untested": ["policy_update_untested_submit"],
    "rush": [],
}


def run_one(api: str, name: str, language: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    r = Run(api, language, rng)
    started = time.time()
    error = None
    try:
        STRATEGIES[name](r)
    except Exception as exc:  # noqa: BLE001 - keep the partial trajectory and the reason
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    behaviour = r.s.get("behavior")
    while isinstance(behaviour.get("result"), dict):
        behaviour = behaviour["result"]
    row = {
        "session_id": r.s.session_id,
        "strategy": name,
        "language": language,
        "seed": seed,
        "executor": "human_script",
        "scenario": "pm_pilot_v2",
        "steps": r.steps,
        "sequence": [x["symbol"] for x in behaviour.get("sequence", [])],
        "seqs": [x["seq"] for x in behaviour.get("sequence", [])],
        "rule_anomalies": [a["rule"] for a in behaviour.get("anomalies", [])],
        "expected_anomalies": EXPECTED_ANOMALIES.get(name, []),
        "request_ids": r.s.request_ids,
        "submissions": r.submissions,
        "duration_s": round(time.time() - started, 1),
        "error": error,
    }
    r.s.close()
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="all")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--language", default="zh", choices=["zh", "en"])
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args(argv)
    names = list(STRATEGIES) if args.strategy == "all" else args.strategy.split(",")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["strategy"], row["seed"]))
    with out.open("a", encoding="utf-8", newline="\n") as handle:
        for i in range(args.count):
            for name in names:
                seed = (
                    args.seed + 1000 * names.index(name) + i + (0 if args.language == "zh" else 500)
                )
                if (name, seed) in done:
                    continue
                row = run_one(args.api, name, args.language, seed)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    f"{name:<16} {i:>3} {row['duration_s']:>6}s len={len(row['sequence'])} "
                    f"anom={row['rule_anomalies']} err={row['error']}",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
