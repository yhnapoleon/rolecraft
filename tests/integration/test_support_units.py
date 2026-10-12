"""R2.support sentence units: rule splitting, per-sentence advice, aggregation and caching.

UNIT-01..08, SYN-01, CACHE-01/02 and COMP-01 (143 §3.5). Splitting is a rule
(``r2-support-units-v1``), not claim extraction. Every registration here is constructed
fixed weights or a fixture fit; nothing is trained and no model quality is claimed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.core import FileRef, SourceIdentity, digest
from career_lab.models.v3.bundle import json_bytes, save_bundle, sha
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.registry import register_bundle
from career_lab.models.v3.units import split_sentences
from scripts.regression.published import write_catalog
from tests.regression.conftest import PublishedSession

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
