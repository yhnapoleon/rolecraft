"""The five recognition-layer requests of the product side (2026-10-26).

1. A judgement says how its candidates were retrieved (and whether that fell back).
2. The DTW distance to the nearest reference comes with its warping path.
3. The colleague reply check reads the visible sources unit by unit, and the number rule
   abstains when two candidates state conflicting figures of the same unit.
4. The learner state carries the AI PM brief when the aipm module provides one.
"""

from __future__ import annotations

import pytest

from career_lab.recognition import behavior, relation, reply, retrieval


@pytest.fixture(autouse=True)
def rules_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    monkeypatch.delenv("CAREER_LAB_RELATION_ENCODER", raising=False)
    monkeypatch.setattr(retrieval, "dense_scores", lambda query, texts: None)


# 1. retrieval method


def test_a_judgement_names_its_retrieval_method_and_fallback() -> None:
    found = relation.judge("住宿每晚500元。", [("policy", "国内出差住宿报销上限为每人每晚500元。")])
    assert found.retrieval == {"method": "bm25", "fallback": True}
    assert relation.judge("住宿每晚500元。", []).retrieval == {"method": None, "fallback": False}


# 2. DTW path


def test_the_dtw_path_is_monotone_and_ends_at_both_corners() -> None:
    mine = ["read:brief", "ask:tech:ask_limit", "test:normal", "test:normal", "submit"]
    reference = ["read:brief", "read:technical", "test:normal", "submit"]
    distance, path = behavior.dtw_path(mine, reference)
    assert distance == behavior.dtw(mine, reference) == 1.0
    assert (path[0]["i"], path[0]["j"]) == (0, 0)
    assert (path[-1]["i"], path[-1]["j"]) == (4, 3)
    for before, after in zip(path, path[1:], strict=False):
        assert 0 <= after["i"] - before["i"] <= 1 and 0 <= after["j"] - before["j"] <= 1
        assert (after["i"], after["j"]) != (before["i"], before["j"])
    # The extra test maps onto the reference's single test (a repeated j), at no cost.
    assert [s for s in path if s["j"] == 2] == [
        {"i": 2, "j": 2, "cost": 0.0},
        {"i": 3, "j": 2, "cost": 0.0},
    ]
    assert behavior.dtw_path([], reference)[1] == []


def test_identical_sequences_align_on_the_diagonal_for_free() -> None:
    sequence = ["read:a", "configure", "submit"]
    distance, path = behavior.dtw_path(sequence, list(sequence))
    assert distance == 0.0
    assert path == [{"i": i, "j": i, "cost": 0.0} for i in range(3)]


# 3. reply check over units + conflicting figures

BRIEF = (
    "# 经理委托\n\n目前为项目预留的容量是30人，可用开发资源3人日。正式试点期限为第7天。\n\n"
    "我需要据此决定本周邀请哪些人试用。"
)
APPROVALS = (
    "# 经理发布：资源审批规则\n\n发布人：经理。以下规则用于本轮容量、开发人日和期限申请。\n\n"
    "可审批上限：容量60人，开发资源6人日，期限第10天。\n\n"
    "申请需写请求条款、理由和拟实施配置。"
)


def test_a_claim_about_a_cap_agrees_with_the_candidate_stating_that_cap() -> None:
    claim = "可审批人数上限是60人。"
    candidates = [
        ("brief", "目前为项目预留的容量是30人。"),
        ("approvals", "可审批上限：容量60人。"),
    ]
    found = relation.rule_judge(claim, candidates, [0.6, 0.3])
    assert found.label == "supported" and found.evidence_ids == ("approvals",)
    assert found.reason.startswith("conflicting_figures|exceeds_limit:60>30 person|same_quantity")
    # Without the figure stated anywhere, exceeding a limit is still a contradiction.
    alone = relation.rule_judge(claim, candidates[:1], [0.3])
    assert alone.label == "contradicted" and alone.reason.startswith("exceeds_limit")


def test_a_plan_exceeding_the_capacity_stays_contradicted_whatever_repeats_its_figure() -> None:
    # The scenario's trap: the learner invites the whole 50-person list into a 30-person
    # capacity; the list's own "50 people" is not a cap the claim restates.
    found = relation.rule_judge(
        "首批邀请50人参加试点。",
        [
            ("brief", "目前为项目预留的容量是30人。"),
            ("coordination", "条目4：“候选名单INV-50共50人，拟在方案确认后发邀请。”"),
        ],
        [0.2, 0.7],
    )
    assert found.label == "contradicted" and found.evidence_ids == ("brief",)


class AbstainingEncoder:
    """A pair model that reads a paraphrase as 'insufficient', as C1 does on replies."""

    revision = "abstaining"

    def judge(self, claim, candidates, *, language, as_of, stack=None):
        return relation.Judgement(
            "insufficient",
            {"supported": 0.01, "contradicted": 0.01, "insufficient": 0.98},
            (),
            recognizer_id=relation.ENCODER_ID,
            revision=self.revision,
            fallback=False,
            reason="pair_aggregate",
            branches={"encoder": {"supported": 0.01, "contradicted": 0.01, "insufficient": 0.98}},
        )


def test_figure_first_keeps_the_figure_the_rule_found_over_an_abstaining_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relation, "encoder_relation", lambda: AbstainingEncoder())
    monkeypatch.setattr(relation, "stack_for", lambda model: None)
    monkeypatch.setattr(relation, "fusion_alpha", lambda: 0.4)
    hits = [retrieval.Hit(index=0, score=1.0, rank=1, method="bm25", bm25=0.12, dense=None)]
    monkeypatch.setattr(retrieval, "search", lambda *a, **k: (hits, "bm25", True))
    claim = "当前委托里的预留容量是30人。"
    candidates = [("brief", "目前为项目预留的容量是30人，可用开发资源3人日。")]
    averaged = relation.judge(claim, candidates)
    assert averaged.label == "insufficient" and averaged.reason.endswith("same_quantity:30 person")
    first = relation.judge(claim, candidates, figure_first=True)
    assert first.label == "supported" and first.evidence_ids == ("brief",)
    assert first.reason.endswith("|figure_found")
    assert first.branches["encoder"]["insufficient"] == 0.98


def test_a_fresher_limit_still_contradicts_the_superseded_figure() -> None:
    # The F04 case: the learner repeats the old 500 while the notice in force says 400.
    old = ("policy-v1", "国内出差住宿报销上限为每人每晚500元。", 0, 0, 13)
    new = ("policy-v2", "费用管理通知：国内出差住宿报销上限改为每人每晚400元。", 13, 13, None)
    found = relation.rule_judge("住宿每晚按500元报销。", [old, new], [0.6, 0.5])
    assert found.label == "contradicted" and found.evidence_ids == ("policy-v2",)


def test_the_reply_check_reads_the_sources_unit_by_unit() -> None:
    units = reply.unitize([("material:brief@1", BRIEF), ("material:approvals@1", APPROVALS)])
    assert all(u["source"] in {"material:brief@1", "material:approvals@1"} for u in units)
    assert not any(u["text"].startswith("#") for u in units)
    for unit in units:
        assert unit["span"] is not None
        source = BRIEF if unit["source"] == "material:brief@1" else APPROVALS
        assert source[unit["span"][0] : unit["span"][1]] == unit["text"]
    assert reply.unitize([("note", "只有一句话。")]) == [
        {"id": "note", "text": "只有一句话。", "source": "note", "span": None}
    ]
    dated = reply.unitize([("material:policy@2", "通知：住宿上限改为400元。", 13, 13, None)])
    assert dated[0]["validity"] == (13, 13, None)


def test_a_cited_cap_is_no_longer_contradicted_by_the_reserved_capacity() -> None:
    text = "按审批规则，可审批人数上限是60人。你先看一下申请记录。"
    checked = reply.check_reply(
        text, [("material:brief@1", BRIEF), ("material:approvals@1", APPROVALS)]
    )
    assert checked.recognizer_id == reply.ID
    rows = checked.outputs["sentences"]
    first = rows[0]
    assert first["label"] != "contradicted"
    assert {"decision", "expected_cost", "evidence_units"} <= set(first)
    assert checked.outputs["candidates"] > checked.outputs["sources"] == 2
    assert checked.outputs["retrieval"] == {"method": "bm25", "fallback": True}


def test_cited_units_name_their_source_and_place() -> None:
    checked = reply.check_reply(
        "住宿每晚报销上限是500元。",
        [
            (
                "material:policy@1",
                "# 差旅\n\n国内出差住宿报销上限为每人每晚500元。\n\n出租车单程上限200元。",
            )
        ],
    )
    row = checked.outputs["sentences"][0]
    # The taxi cap (200) is a limit the claim exceeds; the lodging unit the claim overlaps
    # more states its exact figure, so the rule sides with it instead of contradicting.
    assert row["label"] == "supported"
    assert row["evidence_ids"] == ["material:policy@1"]
    assert row["evidence_units"][0]["source"] == "material:policy@1"
    assert row["evidence_units"][0]["quote"] == "国内出差住宿报销上限为每人每晚500元。"
    assert row["evidence_units"][0]["span"] is not None


def test_a_reply_repeating_the_replaced_figure_is_still_contradicted() -> None:
    old = ("material:policy@1", "# 差旅\n\n国内出差住宿报销上限为每人每晚500元。", 0, 0, 13)
    new = ("material:policy@2", "# 通知\n\n国内出差住宿报销上限改为每人每晚400元。", 13, 13, None)
    row = reply.check_reply("住宿每晚报销上限是500元。", [old, new]).outputs["sentences"][0]
    assert row["label"] == "contradicted"
    assert row["evidence_ids"] == ["material:policy@2"]


# 4. AI PM brief in the learner state


def test_the_learner_state_carries_the_aipm_brief_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import career_lab.aipm as aipm

    stub = {
        "sequence": [{"symbol": "read:brief", "phase": "explore", "seq": 1}],
        "anomalies": [],
        "recognizer": "behavior-v1@rule-fallback",
    }
    monkeypatch.setattr(behavior, "analyze", lambda view, auth, language="zh": stub)
    assert "aipm" not in behavior.learner_state(None, None)
    brief = {"revision": "aipm-brief-v1", "focus_step": "validate_need", "gaps": ["口径冲突"]}
    monkeypatch.setattr(aipm, "colleague_brief", lambda view, auth, language: brief, raising=False)
    assert behavior.learner_state(None, None)["aipm"] == brief
    monkeypatch.setattr(aipm, "colleague_brief", lambda view, auth, language: None, raising=False)
    assert "aipm" not in behavior.learner_state(None, None)

    def broken(view, auth, language):
        raise RuntimeError("not an AI PM session")

    monkeypatch.setattr(aipm, "colleague_brief", broken, raising=False)
    assert "aipm" not in behavior.learner_state(None, None)
