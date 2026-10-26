"""Recognition layer pieces the demo recordings exposed (2026-10-26).

Whole-text candidates are cut into sentence units (so the model-advice slot no longer
abstains on whole materials), fused evidence names the rule's comparison first, the
matched source sentence prefers the claim's figures, every branch of a relation judgement
is recorded, and an unlisted e5 checkout still gets a real revision.
"""

from pathlib import Path

import pytest

from career_lab.contracts.v2.core import EvidenceRefV2
from career_lab.contracts.v2.evaluation import CandidateEvidenceV2
from career_lab.recognition import registry, relation
from career_lab.recognition.judge import _closest_sentence
from career_lab.recognition.units import candidate_units

SESSION = "a" * 32


def material(text: str, **ref) -> CandidateEvidenceV2:
    base = {"session_id": SESSION, "kind": "material", "object_id": "brief", "version": 1}
    return CandidateEvidenceV2(
        id="e-whole", text=text, ref=EvidenceRefV2(**base, observed_at_seq=0, **ref)
    )


def test_a_whole_material_without_a_span_is_cut_into_exact_units() -> None:
    text = "# 经理委托\n\n目前为项目预留的容量是30人，可用开发资源3人日。正式试点期限为第7天。"
    units = candidate_units(material(text))
    assert [u.text for u in units] == [
        "目前为项目预留的容量是30人，可用开发资源3人日。",
        "正式试点期限为第7天。",
    ]
    for unit in units:
        assert text[unit.ref.span_start : unit.ref.span_end] == unit.ref.quote == unit.text
        assert unit.ref.object_id == "brief" and unit.id.startswith("e-")
    assert len({u.id for u in units}) == 2


def test_a_quoted_candidate_with_a_span_keeps_its_offsets() -> None:
    text = "第一句在这里。第二句也在这里。"
    whole = material(text, span_start=10, span_end=10 + len(text), quote=text)
    units = candidate_units(whole)
    assert [(u.ref.span_start, u.ref.span_end) for u in units] == [(10, 17), (17, 25)]


def test_a_quote_without_a_span_and_a_single_sentence_stay_whole() -> None:
    placed_nowhere = material("第一句在这里。第二句也在这里。", quote="第二句也在这里。")
    assert candidate_units(placed_nowhere) == [placed_nowhere]
    single = material("# 标题\n\n只有一句话。")
    assert candidate_units(single) == [single]


class FakeEncoder:
    revision = "fake-encoder"

    def judge(self, claim, candidates, *, language, as_of, stack=None):
        # The model reads a contradiction out of both the old test record and the policy,
        # citing the old record first (retrieval order), as the demo recordings showed.
        return relation.Judgement(
            "contradicted",
            {"supported": 0.05, "contradicted": 0.9, "insufficient": 0.05},
            ("old-test", "policy-v2"),
            recognizer_id=relation.ENCODER_ID,
            revision=self.revision,
            fallback=False,
            reason="pair_aggregate",
            branches={"encoder": {"supported": 0.05, "contradicted": 0.9, "insufficient": 0.05}},
        )


@pytest.fixture
def fused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    monkeypatch.setattr(relation, "encoder_relation", lambda: FakeEncoder())
    monkeypatch.setattr(relation, "stack_for", lambda model: None)
    monkeypatch.setattr(relation, "fusion_alpha", lambda: 0.4)


CANDIDATES = [
    (
        "old-test",
        "出差住宿报销一晚能报多少 → 国内出差住宿报销上限为每人每晚500元；需保留票据。",
        5,
        5,
        None,
    ),
    (
        "policy-v2",
        "费用管理通知：国内出差住宿报销上限改为每人每晚400元；超出上限仍须事前取得经理书面批准。",
        12,
        12,
        None,
    ),
    ("brief", "目前为项目预留的容量是30人，可用开发资源3人日。", 0, 0, None),
]


def test_fused_evidence_names_the_rules_comparison_first(fused: None) -> None:
    found = relation.judge("作品写明：住宿上限 500 元。", CANDIDATES, language="zh", as_of=20)
    assert found.label == "contradicted"
    assert found.evidence_ids == ("policy-v2", "old-test")
    assert found.reason.startswith("late_fusion:0.4|exceeds_limit:500>400 cny")
    assert found.recognizer_id == relation.ENCODER_ID + "+rule"
    assert found.branches["alpha"] == 0.4
    assert found.branches["rule"]["contradicted"] > 0.8
    assert found.branches["encoder"]["contradicted"] == 0.9


def test_when_the_rule_has_nothing_to_compare_the_model_alone_decides(fused: None) -> None:
    found = relation.judge(
        "错误边界清楚后再向经理建议扩大范围。", CANDIDATES, language="zh", as_of=20
    )
    assert found.label == "contradicted" and found.evidence_ids == ("old-test", "policy-v2")
    assert found.reason == "pair_aggregate"
    assert found.branches["rule"] is None and found.branches["alpha"] == 0.4


def test_without_a_model_the_rule_records_its_own_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    monkeypatch.setattr(relation, "encoder_relation", lambda: None)
    found = relation.judge("住宿上限 400 元。", CANDIDATES, language="zh", as_of=20)
    assert found.label == "supported" and found.evidence_ids == ("policy-v2",)
    assert found.branches == {"rule": found.probabilities, "rule_window": 3}


# Five older answers repeat the old figure, so they outrank the current policy for a claim
# that repeats it too; the model's top-5 never sees the policy, the rule's window does.
OLD_ANSWER = "完整实际回答：国内出差住宿报销上限为每人每晚500元；超出上限须取得经理书面批准。"
OLD_ANSWERS = [(f"old-{i}", f"{OLD_ANSWER}（第 {i} 次）", 5, 5, None) for i in range(1, 6)]
# An allowance in force from the start of the session, about something else.
MEAL = ("meal", "餐费报销上限为每人每天100元；超出部分不予报销。", 0, 0, None)


def test_the_rule_reads_a_fresh_limit_below_the_models_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    monkeypatch.setattr(relation, "encoder_relation", lambda: None)
    candidates = OLD_ANSWERS + [CANDIDATES[1], MEAL, CANDIDATES[2]]
    found = relation.judge(
        "国内出差住宿报销上限为每人每晚 500 元。", candidates, language="zh", as_of=20
    )
    assert [t["evidence_id"] for t in found.top] == [c[0] for c in OLD_ANSWERS]
    # The policy that took effect mid-session (valid_from 12) joins the rule's window; the
    # meal allowance, in force from the start, stays subject to retrieval and is not read.
    assert found.label == "contradicted" and found.evidence_ids == ("policy-v2",)
    assert found.reason == "exceeds_limit:500>400 cny"
    assert found.branches["rule_window"] == 6
    # Without a fresh limit in the claim's unit, the window is just the top-k.
    plain = relation.judge("试点第一周先开放给 20 人。", candidates, language="zh", as_of=20)
    assert plain.branches["rule_window"] == 5


def test_the_matched_sentence_prefers_the_claims_figure() -> None:
    text = (
        "## 用户组\n\n新员工组共 80 人，主要问入口指引类问题。\n\n"
        "老员工组共 300 人，主要问政策类问题，入口指引类问题也有。"
    )
    claim = "首批只开放给新员工组的 80 人，先验证入口指引类问题"
    assert _closest_sentence(claim, text).startswith("新员工组共 80 人")
    # Without a figure in the claim, character overlap decides as before.
    assert _closest_sentence("老员工主要问政策类问题", text).startswith("老员工组共 300 人")


def test_an_unlisted_e5_checkout_gets_the_tree_hash_as_its_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "retrieval-e5"
    checkout.mkdir()
    (checkout / "config.json").write_text('{"hidden_size": 384}', encoding="utf-8")
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path))
    registry.load_all.cache_clear()
    try:
        entry = registry.get("retrieval-e5")
        assert entry is not None
        expected = registry.tree_sha256(checkout)
        assert (entry.sha256, entry.revision) == (expected, expected[:12])
        assert entry.revision != "unhashed"
    finally:
        registry.load_all.cache_clear()
