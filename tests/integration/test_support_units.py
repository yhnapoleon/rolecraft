"""R2.support sentence units: rule splitting, per-sentence advice, aggregation and caching.

UNIT-01..08, SYN-01, CACHE-01/02 and COMP-01 (143 §3.5). Splitting is a rule
(``r2-support-units-v1``), not claim extraction. Every registration here is constructed
fixed weights or a fixture fit; nothing is trained and no model quality is claimed.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.core import EvidenceRefV2, FileRef, SourceIdentity, digest
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.jobs.worker import Worker, WorkerClaim
from career_lab.models.v3.bundle import json_bytes, save_bundle, sha
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.projection import relation_input, sentence_input
from career_lab.models.v3.registry import register_bundle
from career_lab.models.v3.units import split_sentences, support_units
from scripts.regression.published import write_catalog
from tests.regression.conftest import PublishedSession
from tests.unit.test_w08_models import examples as fixture_examples

ROOT = Path(__file__).resolve().parents[2]

# Marker characters that appear only in test sentences, never in scenario materials:
# a sentence with SUPPORT is judged SUPPORTED, with CONTRADICT CONTRADICTED, otherwise
# INSUFFICIENT; marked sentences select their candidate evidence. Constructed, not fitted.
SUPPORT, CONTRADICT = "◎", "✕"


def sentences(text: str) -> list[str]:
    found = split_sentences(text)
    assert all(text[s.start : s.end] == s.text for s in found)
    return [s.text for s in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "试点只开放给人工复核过的团队。若名额超过上限，需要先申请扩容！真的吗？先保留；再说",
            [
                "试点只开放给人工复核过的团队。",
                "若名额超过上限，需要先申请扩容！",
                "真的吗？",
                "先保留；",
                "再说",
            ],
        ),
        (
            "Defer until the owner is verified. Budget is 3.5 days, e.g. two people vs. one. "
            "Keep fallback etc. and log it! Ready? Yes; go.",
            [
                "Defer until the owner is verified.",
                "Budget is 3.5 days, e.g. two people vs. one.",
                "Keep fallback etc. and log it!",
                "Ready?",
                "Yes;",
                "go.",
            ],
        ),
        ("E.g. one option. I.e. the cheaper one.", ["E.g. one option.", "I.e. the cheaper one."]),
        # A period after a digit never ends a sentence, so inline numbering stays together.
        ("Scope covers 12. Next we wait.", ["Scope covers 12. Next we wait."]),
        ("预算是 3.5 人日。人数为 2.0 人。", ["预算是 3.5 人日。", "人数为 2.0 人。"]),
        ("他说：“先暂缓。”然后离开。", ["他说：“先暂缓。”", "然后离开。"]),
        ("真的？！好。", ["真的？！", "好。"]),
        (
            "要点：\n- 保留人工兜底\n- 记录未知条件。另行确认\n"
            "* 星号项\n• 圆点项\n1. 第一项\n2. 第二项",
            [
                "要点：",
                "保留人工兜底",
                "记录未知条件。",
                "另行确认",
                "星号项",
                "圆点项",
                "第一项",
                "第二项",
            ],
        ),
        (
            "Open the pilot to reviewed teams.\n\n"
            "- Keep human fallback\n- Record unknown conditions",
            [
                "Open the pilot to reviewed teams.",
                "Keep human fallback",
                "Record unknown conditions",
            ],
        ),
        (
            "第一段。\n\n第二段没有句号\n \t\n第三段。",
            ["第一段。", "第二段没有句号", "第三段。"],
        ),
        # A single line break inside a paragraph is not a sentence boundary.
        ("Line one continues\non the next line.", ["Line one continues\non the next line."]),
        ("  \n\n   ", []),
    ],
)
def test_unit_01_chinese_and_english_punctuation_decimals_abbreviations_and_lists(
    text: str, expected: list[str]
) -> None:
    assert sentences(text) == expected


def test_unit_01_spans_are_offsets_in_the_original_text() -> None:
    text = "  先暂缓。\n\n- 保留人工兜底\n"
    assert [(s.start, s.end, s.text) for s in split_sentences(text)] == [
        (2, 6, "先暂缓。"),
        (10, 16, "保留人工兜底"),
    ]


# HTTP helpers ------------------------------------------------------------------------


def marker_bundle(root: Path, *, fixture: bool = True) -> tuple[Path, FileRef]:
    config = {
        "preprocessing_revision": "historical-time-v1",
        "kind": "linear",
        "task_type": "relation",
        "seed": 5002,
        "max_features": 2,
        "vocabulary": {SUPPORT: 0, CONTRADICT: 1},
        "evidence_threshold": 0.5,
        "labels": list(LABELS["relation"]),
        "training_report": {"scope": "synthetic_fixed_weights", "fit_performed": False},
    }
    arrays = {
        "coef": np.array([[4.0, 0.0], [0.0, 4.0], [0.0, 0.0]]),
        "intercept": np.array([0.0, 0.0, 1.0]),
        "evidence_coef": np.array([3.0, 3.0]),
        "evidence_intercept": np.array([-1.0]),
        "idf": np.ones(2),
    }
    model = LinearCandidate.restore(config, arrays)
    data = root / "source"
    data.mkdir(parents=True)
    release = json_bytes({"fixture": fixture, "scope": "synthetic_fixed_weights_no_training"})
    split = json_bytes({"fixture": fixture, "scope": "synthetic_no_held_out_data"})
    (data / "release.json").write_bytes(release)
    (data / "split.json").write_bytes(split)
    ref = save_bundle(
        model,
        root / "bundle",
        source_root=data,
        training_release=FileRef(path="release.json", sha256=sha(release)),
        split_manifest=FileRef(path="split.json", sha256=sha(split)),
        source=SourceIdentity(base_commit="b" * 40, source_digest=digest("marker-no-fit")),
    )
    return root / "bundle", ref


@contextmanager
def registered_service(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    *,
    scope: str = "synthetic_fixture",
    bundle=None,
) -> Iterator[tuple[PublishedSession, FileRef]]:
    """A normal runtime app with one registration configured before it starts."""
    bundle_root, bundle_ref = (bundle or marker_bundle)(
        root / "model", fixture=scope == "synthetic_fixture"
    )
    registration = register_bundle(root / "registry", bundle_root, bundle_ref, scope=scope)
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(root / "registry"))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", registration.model_dump_json())
    monkeypatch.setenv("CAREER_LAB_MODEL_JOURNAL", str(root / "journal"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(root / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(root / "archive"))
    app = create_runtime_app("sqlite:///" + str(root / "session.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            made = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert made.status_code == 200, made.text
            body = made.json()
            yield (
                PublishedSession(
                    app,
                    client,
                    body["session_id"],
                    {"Authorization": "Bearer " + body["token"]},
                    language,
                ),
                registration,
            )
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def save_work(session: PublishedSession, content: str, key: str = "work") -> dict:
    response = session.send(
        "work-products",
        key,
        "work_products.create",
        {"kind": "text", "purpose": "commitment", "title": "Pilot decision", "content": content},
    )
    return next(ref for ref in response["objects"] if ref["kind"] == "product")


def review(session: PublishedSession, work: dict, key: str = "review") -> tuple[dict, dict]:
    """Submit a review of ``work``, run its job, read the feedback; returns (feedback, advice)."""
    transaction = session.send(
        "reviews",
        key,
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    response = session.get("feedback/" + transaction["result"]["review"]["object_id"])
    assert response.status_code == 200, response.text
    report = response.json()["result"]["result"]["items"][0]
    advice = [row for row in report["model_advice"] if row["criterion"] == "R2.support"]
    assert len(advice) == 1, report["model_advice"]
    return report, advice[0]


def plain(value):
    """Wire JSON without its schema_version markers."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if k != "schema_version"}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


THREE_PARAGRAPHS = {
    "zh": (
        f"试点先只开放给已完成人工复核的团队{SUPPORT}。若名额超过上限，需要先申请扩容。\n\n"
        f"政策规定住宿上限为每晚500元{CONTRADICT}。超出部分必须事先取得书面批准。\n\n"
        "- 保留人工兜底\n- 记录未知条件"
    ),
    "en": (
        f"Open the pilot only to teams with completed human review{SUPPORT}. "
        "If seats exceed the limit, request capacity first.\n\n"
        f"The policy caps hotels at CNY 500 per night{CONTRADICT}. "
        "Any excess needs written approval in advance.\n\n"
        "- Keep human fallback\n- Record unknown conditions"
    ),
}
THREE_PARAGRAPH_LABELS = [
    "SUPPORTED",
    "INSUFFICIENT",
    "CONTRADICTED",
    "INSUFFICIENT",
    "INSUFFICIENT",
    "INSUFFICIENT",
]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_01_three_paragraph_work_is_judged_sentence_by_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = THREE_PARAGRAPHS[language]
    with registered_service(tmp_path, monkeypatch, language) as (session, _):
        work = save_work(session, content)
        report, advice = review(session, work)
    units = advice["units"]
    assert [unit["subject"]["quote"] for unit in units] == [
        s.text for s in split_sentences(content)
    ]
    assert [unit["index"] for unit in units] == list(range(6))
    for unit in units:
        subject = unit["subject"]
        assert subject["object_id"] == work["object_id"] and subject["kind"] == "product"
        assert content[subject["span_start"] : subject["span_end"]] == subject["quote"]
    assert len({unit["unit_hash"] for unit in units}) == 6
    assert [unit["label"] for unit in units] == THREE_PARAGRAPH_LABELS
    assert all(unit["status"] == "completed" for unit in units)
    assert plain(advice["aggregation"]) == {
        "policy": "r2-support-units-v1",
        "counts": {
            "supported": 1,
            "contradicted": 1,
            "insufficient": 4,
            "abstained": 0,
            "failed": 0,
            "skipped_short": 0,
            "over_budget": 0,
        },
    }
    assert advice["label"] == "CONTRADICTED"
    marked = {
        evidence
        for unit in units
        if unit["label"] != "INSUFFICIENT"
        for evidence in unit["evidence_ids"]
    }
    assert marked and set(advice["evidence_ids"]) == marked
    assert all(not unit["evidence_ids"] for unit in units if unit["label"] == "INSUFFICIENT")
    for ref in advice["citations"]:
        assert ref["session_id"] == session.session_id and ref["object_id"] != work["object_id"]
    assert advice["affects_score"] is False and advice["mode"] == "advisory"


def attention_bundle(root: Path, *, fixture: bool = True) -> tuple[Path, FileRef]:
    """A NumPy attention encoder fitted on the W08 fixture records, with a 400-token budget."""
    model = AttentionEncoder(variant="pair", dimension=4, max_tokens=400)
    model.fit(fixture_examples(), epochs=1)
    data = root / "source"
    data.mkdir(parents=True)
    release = json_bytes({"fixture": True, "scope": "fixture_fit_mechanism_only"})
    split = json_bytes({"fixture": True, "scope": "synthetic_no_held_out_data"})
    (data / "release.json").write_bytes(release)
    (data / "split.json").write_bytes(split)
    ref = save_bundle(
        model,
        root / "bundle",
        source_root=data,
        training_release=FileRef(path="release.json", sha256=sha(release)),
        split_manifest=FileRef(path="split.json", sha256=sha(split)),
        source=SourceIdentity(base_commit="c" * 40, source_digest=digest("fixture-fit")),
    )
    return root / "bundle", ref


# Far beyond 400 tokens together with the scenario policy material; short ones fit.
LONG_SENTENCE = {
    "zh": "需要先核实负责人、范围与名额" * 45 + "。",
    "en": "We must first verify the owner, the scope and the seats " * 50 + ".",
}
SHORT_SENTENCES = {
    "zh": "试点先暂缓。保留人工兜底。",
    "en": "Defer the pilot. Keep human fallback.",
}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_03_sentence_over_the_encoder_limit_abstains_without_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    calls = []
    real_predict = AttentionEncoder.predict

    def counted(model, item):
        calls.append(item.evidence.claim)
        return real_predict(model, item)

    monkeypatch.setattr(AttentionEncoder, "predict", counted)
    content = SHORT_SENTENCES[language] + "\n\n" + LONG_SENTENCE[language]
    with registered_service(tmp_path, monkeypatch, language, bundle=attention_bundle) as (
        session,
        _,
    ):
        _, advice = review(session, save_work(session, content))
    *short, long = advice["units"]
    assert long["subject"]["quote"] == LONG_SENTENCE[language].strip()
    assert long["status"] == "abstained" and long["label"] is None
    assert long["reason_code"] == "unit_exceeds_encoder_limit"
    assert len(short) == 2 and all(unit["status"] == "completed" for unit in short)
    # The model never saw the long sentence, cut or whole; the others were judged as written.
    assert calls == [unit["subject"]["quote"] for unit in short]
    outcomes = [json.loads(p.read_text()) for p in (tmp_path / "journal").glob("*/outcome.json")]
    measured = [row for row in outcomes if row["prediction"]["reason_code"] is not None]
    assert len(measured) == 1 and measured[0]["status"] == "completed"
    size = measured[0]["input_size"]
    assert size["limit"] == 400 and size["tokens"] > 400
    assert advice["aggregation"]["counts"]["abstained"] == 1
    assert advice["status"] == "synthetic_mechanism_only" and advice["label"] == "INSUFFICIENT"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_03_work_whose_sentences_all_exceed_the_limit_reports_all_abstained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = LONG_SENTENCE[language] + "\n\n" + LONG_SENTENCE[language]
    with registered_service(tmp_path, monkeypatch, language, bundle=attention_bundle) as (
        session,
        _,
    ):
        _, advice = review(session, save_work(session, content))
    assert [unit["status"] for unit in advice["units"]] == ["abstained", "abstained"]
    assert advice["status"] == "unavailable" and advice["error_code"] == "all_units_abstained"
    assert advice["label"] is None and advice["evidence_ids"] == advice["citations"] == []


def counts(advice: dict) -> dict:
    return plain(advice["aggregation"]["counts"])


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_02_short_and_over_budget_sentences_are_counted_not_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    statement = {"zh": "第{}项已经核实{}。", "en": "Item {} is verified{}."}[language]
    short = {"zh": "好。行。", "en": "OK. Go."}[language]
    content = short + "\n\n" + " ".join(statement.format(i, SUPPORT) for i in range(1, 27))
    with registered_service(tmp_path, monkeypatch, language) as (session, _):
        _, advice = review(session, save_work(session, content))
    assert len(advice["units"]) == 24
    assert advice["units"][0]["subject"]["quote"] == statement.format(1, SUPPORT)
    assert advice["units"][-1]["subject"]["quote"] == statement.format(24, SUPPORT)
    assert counts(advice) == {
        "supported": 24,
        "contradicted": 0,
        "insufficient": 0,
        "abstained": 0,
        "failed": 0,
        "skipped_short": 2,
        "over_budget": 2,
    }
    # Two sentences were never judged, so the work is not shown as fully supported.
    assert advice["label"] == "INSUFFICIENT"
    assert len(list((tmp_path / "journal").glob("*/outcome.json"))) == 24


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_02_work_with_only_short_sentences_says_no_claim_was_judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = {"zh": "好。\n\n- 行\n- 可", "en": "OK.\n\n- Go\n- Yes"}[language]
    with registered_service(tmp_path, monkeypatch, language) as (session, _):
        _, advice = review(session, save_work(session, content))
    assert advice["units"] == [] and counts(advice)["skipped_short"] == 3
    assert advice["status"] == "unavailable" and advice["error_code"] == "claim_not_available"
    assert advice["label"] is None
    assert not (tmp_path / "journal").exists() or not any((tmp_path / "journal").iterdir())


@pytest.mark.parametrize(
    ("scope", "status"),
    [("synthetic_fixture", "synthetic_mechanism_only"), ("external_candidate", "completed")],
)
@pytest.mark.parametrize(
    ("marks", "expected"),
    [
        ((SUPPORT, SUPPORT, SUPPORT), "SUPPORTED"),
        ((SUPPORT, "", SUPPORT), "INSUFFICIENT"),
        ((SUPPORT, SUPPORT, ""), "INSUFFICIENT"),
        (("", "", ""), "INSUFFICIENT"),
    ],
)
def test_unit_04_insufficient_sentences_never_become_a_supported_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    status: str,
    marks: tuple[str, ...],
    expected: str,
) -> None:
    content = "\n\n".join(
        f"Paragraph {i} keeps human fallback{mark}." for i, mark in enumerate(marks, 1)
    )
    with registered_service(tmp_path, monkeypatch, "en", scope=scope) as (session, _):
        _, advice = review(session, save_work(session, content))
    assert advice["status"] == status and advice["label"] == expected
    assert [unit["label"] for unit in advice["units"]] == [
        "SUPPORTED" if mark else "INSUFFICIENT" for mark in marks
    ]
    supported = {e for u in advice["units"] if u["label"] == "SUPPORTED" for e in u["evidence_ids"]}
    assert set(advice["evidence_ids"]) == supported


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_unit_05_one_contradicted_sentence_decides_the_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, position: int
) -> None:
    sentence = {"zh": "第{}段写明保留人工兜底{}。", "en": "Paragraph {} keeps fallback{}."}[
        language
    ]
    marks = [SUPPORT, SUPPORT, SUPPORT]
    marks[position] = CONTRADICT
    content = "\n\n".join(sentence.format(i, mark) for i, mark in enumerate(marks, 1))
    with registered_service(tmp_path, monkeypatch, language, scope="external_candidate") as (
        session,
        _,
    ):
        work = save_work(session, content)
        _, advice = review(session, work)
    assert advice["status"] == "completed" and advice["label"] == "CONTRADICTED"
    assert [unit["label"] for unit in advice["units"]][position] == "CONTRADICTED"
    assert counts(advice)["contradicted"] == 1 and counts(advice)["supported"] == 2
    # Evidence is the union over the supported and contradicted sentences, each kept.
    union = {e for unit in advice["units"] for e in unit["evidence_ids"]}
    assert union and set(advice["evidence_ids"]) == union
    assert all(
        ref["session_id"] == session.session_id and ref["object_id"] != work["object_id"]
        for unit in advice["units"]
        for ref in unit["citations"]
    )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_06_restarted_job_reads_journaled_sentences_back_and_judges_only_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = THREE_PARAGRAPHS[language]
    judged: list[str] = []
    real_predict = LinearCandidate.predict

    def counted(model, item):
        judged.append(item.evidence.claim)
        return real_predict(model, item)

    monkeypatch.setattr(LinearCandidate, "predict", counted)
    with registered_service(tmp_path, monkeypatch, language) as (session, _):
        work = save_work(session, content)
        transaction = session.send(
            "reviews",
            "recovering-review",
            "reviews.create",
            {
                "subjects": [work],
                "scope": [],
                "purpose": "commitment",
                "decision": "defer_with_conditions",
            },
        )
        job = session.app.state.jobs.claim_job("controlled-worker")
        claim = WorkerClaim.from_job(job)
        real_replace = os.replace
        written: list[str] = []

        def stop_after_two_sentences(source, destination):
            real_replace(source, destination)
            if Path(destination).name == "outcome.json":
                written.append(str(destination))
                if len(written) == 2:
                    raise SystemExit("Controlled process loss after two sentences")

        with monkeypatch.context() as fault:
            fault.setattr(os, "replace", stop_after_two_sentences)
            with pytest.raises(SystemExit, match="after two sentences"):
                session.app.state.handlers[job["kind"]](job["payload"], claim)
        before = {path: Path(path).read_bytes() for path in written}
        assert len(judged) == 2
        reopened = create_runtime_app("sqlite:///" + str(tmp_path / "session.db"), provider="local")
        try:
            result = reopened.state.handlers[job["kind"]](job["payload"], claim)
            session.app.state.jobs.complete(job["id"], job["lease_token"], result)
        finally:
            reopened.state.store.close()
            reopened.state.v2_store.db.engine.dispose()
        assert len(judged) == 6, "only the four sentences without a journal were judged"
        assert {path: Path(path).read_bytes() for path in written} == before
        feedback = "feedback/" + transaction["result"]["review"]["object_id"]
        report = session.get(feedback).json()["result"]["result"]["items"][0]
        (advice,) = [row for row in report["model_advice"] if row["criterion"] == "R2.support"]
        assert [unit["label"] for unit in advice["units"]] == THREE_PARAGRAPH_LABELS
        journal = {
            str(path): path.read_bytes() for path in (tmp_path / "journal").glob("*/outcome.json")
        }
        assert len(journal) == 6
        for _ in range(3):
            assert session.get(feedback).json()["result"]["result"]["items"][0] == report
            assert not Worker(session.app.state.jobs, session.app.state.handlers).run_once()
        assert len(judged) == 6
        assert {
            str(path): path.read_bytes() for path in (tmp_path / "journal").glob("*/outcome.json")
        } == journal


SAME_FACTS = (
    THREE_PARAGRAPHS,
    {
        "zh": (
            f"预算为 3.5 人日，例如两人各 1.75 天{SUPPORT}。容量上限为 8 个团队；超出需先申请。\n\n"
            "1. 先核实负责人\n2. 再确认范围\n\n"
            f"住宿超过每晚500元仍可直接报销{CONTRADICT}！这一点需要复核？"
        ),
        "en": (
            f"The budget is 3.5 person-days, e.g. two people at 1.75 days each{SUPPORT}. "
            "Capacity is capped at 8 teams; any excess needs a request first.\n\n"
            "1. Verify the owner first\n2. Then confirm the scope\n\n"
            f"Hotels above CNY 500 per night can still be reimbursed directly{CONTRADICT}! "
            "Does this need review?"
        ),
    },
)


@pytest.mark.parametrize("pair", range(len(SAME_FACTS)))
def test_unit_07_chinese_and_english_versions_of_one_fact_cut_and_conclude_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pair: int
) -> None:
    results = {}
    for language in ("zh", "en"):
        with monkeypatch.context() as scoped:
            with registered_service(tmp_path / language, scoped, language) as (session, _):
                _, results[language] = review(
                    session, save_work(session, SAME_FACTS[pair][language])
                )
    zh, en = results["zh"], results["en"]
    assert len(zh["units"]) == len(en["units"]) >= 5
    assert [u["label"] for u in zh["units"]] == [u["label"] for u in en["units"]]
    assert counts(zh) == counts(en)
    assert zh["label"] == en["label"] == "CONTRADICTED"
    assert zh["status"] == en["status"] == "synthetic_mechanism_only"


GOLDEN_PACKAGES = json.loads(
    (
        ROOT / "tests/contracts/expansion_v3/fixtures/model_assembly/split01-main-d163747.json"
    ).read_text()
)
LEAK_KEYS = {"gold", "probe", "hidden_probe", "annotation", "acceptable_evidence_sets"}


def keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_unit_08_sentence_inputs_carry_no_probe_gold_rule_bound_or_rule_derivations(
    language: str,
) -> None:
    (case,) = [row for row in GOLDEN_PACKAGES["cases"] if row["language"] == language]
    checked = 0
    for raw in case["packages"]:
        if raw["criterion"] != "R2.support":
            continue
        # The recorded HTTP package, given a hidden probe with its gold label and a rule bound.
        body = {k: v for k, v in raw.items() if k != "input_hash"}
        body["rule_context"] = body["rule_context"] | {
            "hidden_probe": {"gold": "CONTRADICTED", "acceptable_evidence_sets": [["x"]]}
        }
        body["rule_bound"] = {"schema_version": 2, "lower": "PARTIAL", "upper": "MET"}
        package = EvidencePackageV2.model_validate(body | {"input_hash": digest(body)})
        whole = relation_input(package)
        for unit in support_units(package).units:
            item = sentence_input(whole, unit.subject, unit.text)
            evidence = item.evidence
            dumped = item.model_dump(mode="json")
            assert evidence.claim == unit.text and evidence.subjects == (unit.subject,)
            assert evidence.rule_bound is None
            assert set(evidence.rule_context) == {"evidence_time_context"}
            assert set(evidence.rule_context["evidence_time_context"]) == {
                "policy",
                "status",
                "reference_seq",
                "validity_known_ids",
            }
            # Rule derivations (facts, decision, verified facts, ...) never appear as fields;
            # reference fields such as config_version legitimately do.
            derivations = set(raw["rule_context"]) - set(EvidenceRefV2.model_fields)
            assert derivations and not keys(dumped) & (LEAK_KEYS | derivations)
            text = json.dumps(dumped, ensure_ascii=False)
            assert "CONTRADICTED" not in text and raw["rule_context"]["decision"] not in text
            assert all(c.id.startswith("e-") for c in evidence.candidate_evidence)
            assert evidence.candidate_evidence == whole.evidence.candidate_evidence
            checked += 1
    assert checked >= 2


@contextmanager
def plain_service(root: Path, monkeypatch: pytest.MonkeyPatch, language: str):
    """The same normal runtime app with no registration configured."""
    for name in ("REGISTRY", "REGISTRATION", "REGISTRATIONS", "JOURNAL"):
        monkeypatch.delenv("CAREER_LAB_MODEL_" + name, raising=False)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(root / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(root / "archive"))
    app = create_runtime_app("sqlite:///" + str(root / "session.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            body = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            ).json()
            yield PublishedSession(
                app,
                client,
                body["session_id"],
                {"Authorization": "Bearer " + body["token"]},
                language,
            )
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def scoring(report: dict) -> dict:
    return {
        "rule_items": [
            (row["criterion"], row["label"], row["source"], row["rule_bound"])
            for row in report["rule_items"]
        ],
        "items": [(row["criterion"], row["label"], row["source"]) for row in report["items"]],
        "score_range": {
            key: report["score_range"][key] for key in ("lower", "upper", "denominator")
        },
        "coverage": (report["verified_coverage"], report["model_coverage"]),
    }


@pytest.mark.parametrize("language", ["zh", "en"])
def test_syn_01_synthetic_labels_are_always_marked_as_mechanism_and_never_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = THREE_PARAGRAPHS[language]
    with registered_service(tmp_path / "registered", monkeypatch, language) as (session, _):
        report, advice = review(session, save_work(session, content))
    assert advice["status"] == advice["error_code"] == "synthetic_mechanism_only"
    assert advice["label"] == "CONTRADICTED" and advice["evidence_ids"]
    assert all(unit["label"] for unit in advice["units"])
    registration = advice["registration"]
    assert registration["scope"] == "synthetic_fixture"
    assert registration["quality_validated"] is False
    assert report["provenance"]["registered_model"] == registration
    assert advice["affects_score"] is False and advice["mode"] == "advisory"
    assert all(row["source"] != "model_advice" for row in report["items"])
    with plain_service(tmp_path / "plain", monkeypatch, language) as other:
        baseline, _ = review_without_advice(other, save_work(other, content))
    assert scoring(report) == scoring(baseline)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_syn_01_external_labels_are_completed_advice_with_the_same_aggregation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    content = THREE_PARAGRAPHS[language]
    with registered_service(tmp_path, monkeypatch, language, scope="external_candidate") as (
        session,
        _,
    ):
        _, advice = review(session, save_work(session, content))
    assert advice["status"] == "completed" and advice["error_code"] is None
    assert advice["registration"]["scope"] == "external_candidate"
    assert [unit["label"] for unit in advice["units"]] == THREE_PARAGRAPH_LABELS
    assert advice["label"] == "CONTRADICTED"


def review_without_advice(session: PublishedSession, work: dict) -> tuple[dict, None]:
    transaction = session.send(
        "reviews",
        "review",
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    response = session.get("feedback/" + transaction["result"]["review"]["object_id"])
    report = response.json()["result"]["result"]["items"][0]
    assert not report.get("model_advice")
    return report, None
