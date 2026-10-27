"""Recognition-layer backstops found on real sessions (2026-10-27).

1. The stored relation record says which retrieval method each sentence actually ran, and
   the retrieval record names the method and whether it fell back to BM25.
2. The work replay keeps questions asked at the same business point in the order they were
   asked (asking does not advance the point; the store lists objects by id).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from career_lab.contracts.v2.core import EvidenceRefV2, VersionPoint, digest
from career_lab.contracts.v2.evaluation import CandidateEvidenceV2, EvidencePackageV2
from career_lab.recognition import behavior, judge, retrieval
from career_lab.recognition.base import FALLBACK_REVISION


@pytest.fixture(autouse=True)
def rules_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    monkeypatch.delenv("CAREER_LAB_RELATION_ENCODER", raising=False)
    monkeypatch.setattr(retrieval, "dense_scores", lambda query, texts: None)


AS_OF = VersionPoint(business_seq=3, workspace_revision=2, storage_revision=5)
POLICY = "国内出差住宿报销上限为每人每晚500元。超过上限需要经理审批。"


def ref(kind: str, object_id: str) -> EvidenceRefV2:
    return EvidenceRefV2(
        session_id="backstop-session", kind=kind, object_id=object_id, version=1, observed_at_seq=1
    )


def support_package(work: str, *materials: str) -> EvidencePackageV2:
    """A minimal R2.support package: the work as its only subject, plus material candidates."""
    subject = ref("product", "prd-1")
    candidates = [CandidateEvidenceV2(id="e-work", ref=subject, text=work)] + [
        CandidateEvidenceV2(id=f"e-{i}", ref=ref("material", f"m-{i}"), text=text)
        for i, text in enumerate(materials)
    ]
    body = {
        "schema_version": 2,
        "item_id": "backstop-r2-support",
        "task_type": "criterion",
        "criterion": "R2.support",
        "claim": work,
        "subjects": [subject.model_dump(mode="json")],
        "purpose": "R2.support",
        "as_of": AS_OF.model_dump(mode="json"),
        "applicability": "applicable",
        "candidate_evidence": [c.model_dump(mode="json") for c in candidates],
        "rule_context": {},
        "rule_bound": None,
        "completeness": "complete",
        "dropped_refs": [],
        "missing_refs": [],
    }
    return EvidencePackageV2(**body, input_hash=digest(body))


def stored_records(package: EvidencePackageV2) -> tuple[dict, dict]:
    analysis = judge.analyze_support(package, "zh")
    records = judge.RecognitionFeedback(None)._analysis_records(analysis, AS_OF)
    relation_record, retrieval_record = records[0], records[1]
    assert retrieval_record.recognizer_id == "retrieval-c2"
    return relation_record.model_dump(mode="json"), retrieval_record.model_dump(mode="json")


# 1. retrieval method in the stored records

WORK = "住宿每晚500元。超过上限需要经理审批。"


def test_stored_units_and_retrieval_record_say_bm25_ran_as_a_fallback() -> None:
    relation_record, retrieval_record = stored_records(support_package(WORK, POLICY))
    units = relation_record["outputs"]["units"]
    assert len(units) == 2
    assert all(u["retrieval"] == {"method": "bm25", "fallback": True} for u in units)
    assert retrieval_record["revision"] == FALLBACK_REVISION
    assert retrieval_record["fallback"] is True
    assert retrieval_record["outputs"]["method"] == "bm25"
    assert retrieval_record["outputs"]["requested_method"] == "rrf"
    assert {"per_sentence_top", "k", "candidates"} <= set(retrieval_record["outputs"])


def test_with_the_embedder_the_retrieval_record_stays_rrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieval, "dense_scores", lambda query, texts: np.linspace(0.9, 0.1, len(texts))
    )
    relation_record, retrieval_record = stored_records(support_package(WORK, POLICY))
    assert all(
        u["retrieval"] == {"method": "rrf", "fallback": False}
        for u in relation_record["outputs"]["units"]
    )
    assert retrieval_record["revision"] == "rrf"
    assert retrieval_record["fallback"] is False
    assert retrieval_record["outputs"]["method"] == "rrf"
    assert retrieval_record["outputs"]["requested_method"] == "rrf"


def test_a_pass_with_no_sentences_names_no_method() -> None:
    relation_record, retrieval_record = stored_records(support_package("好。", POLICY))
    assert relation_record["outputs"]["units"] == []
    assert retrieval_record["revision"] == "rrf"
    assert retrieval_record["fallback"] is False
    assert retrieval_record["outputs"]["method"] is None


def test_sentences_with_no_candidates_name_no_method() -> None:
    relation_record, retrieval_record = stored_records(support_package(WORK))
    assert all(
        u["retrieval"] == {"method": None, "fallback": False}
        for u in relation_record["outputs"]["units"]
    )
    assert retrieval_record["revision"] == "rrf"
    assert retrieval_record["outputs"]["method"] is None


# 2. same-point questions in storage order


def role_turn(object_id: str, seq: int, revision: int, role: str) -> SimpleNamespace:
    return SimpleNamespace(
        ref=SimpleNamespace(kind="role_turn", object_id=object_id),
        created_storage_revision=revision,
        content={
            "input": {"role_id": role, "text": f"{role} question {object_id}"},
            "as_of": {"business_seq": seq},
            "executor": {"kind": "human"},
        },
    )


def event(seq: int, kind: str, **data) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"ev-{seq}-{kind}",
        seq=seq,
        type=kind,
        data=data,
        refs=(),
        executor=SimpleNamespace(kind="human"),
    )


class ReplayView:
    """The parts of a session view ``symbols`` reads: public events and stored objects."""

    def __init__(self, objects, events=()):
        self.objects = list(objects)
        self.events = list(events)
        self.state = SimpleNamespace(business_seq=max((e.seq for e in self.events), default=0))

    def public_history(self, page, auth):
        found = [e for e in self.events if e.seq > page.since_seq]
        return SimpleNamespace(events=found, next_seq=self.state.business_seq)


def questions(view) -> list[str]:
    return [row["question"] for row in behavior.symbols(view, None) if "question" in row]


def test_questions_at_one_business_point_replay_in_storage_order() -> None:
    # Stored Chen, Chen, Daniel, Daniel, Grace, Grace; listed by object id.
    stored = [
        role_turn("t-a", 0, 15, "daniel"),
        role_turn("t-b", 0, 19, "grace"),
        role_turn("t-c", 0, 17, "daniel"),
        role_turn("t-d", 0, 21, "grace"),
        role_turn("t-e", 0, 9, "chen"),
        role_turn("t-f", 0, 13, "chen"),
    ]
    order = [row["symbol"].split(":")[1] for row in behavior.symbols(ReplayView(stored), None)]
    assert order == ["chen", "chen", "daniel", "daniel", "grace", "grace"]


def test_questions_still_sit_just_after_the_event_of_their_business_point() -> None:
    stored = [
        role_turn("t-late", 2, 30, "grace"),
        role_turn("t-y", 1, 12, "daniel"),
        role_turn("t-first", 0, 3, "chen"),
        role_turn("t-x", 1, 8, "chen"),
    ]
    events = [event(1, "material_read", material_id="brief"), event(2, "submitted")]
    rows = behavior.symbols(ReplayView(stored, events), None)
    assert [row["symbol"].split(":")[0] for row in rows] == [
        "ask",
        "read",
        "ask",
        "ask",
        "submit",
        "ask",
    ]
    assert [row["seq"] for row in rows] == [0, 1, 1, 1, 2, 2]
    assert questions(ReplayView(stored, events)) == [
        "chen question t-first",
        "chen question t-x",
        "daniel question t-y",
        "grace question t-late",
    ]
