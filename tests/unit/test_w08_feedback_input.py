"""Exact-work conversion plus the public registry CLI, using a literal negation oracle."""

from pathlib import Path

from test_w08_registration import registered

from career_lab.contracts import v2 as C
from career_lab.models.v3.registry_cli import main
from career_lab.rubrics.v4.support import registered_relation_input


def test_registered_input_retains_negation_and_excludes_self_citations(
    tmp_path: Path, capsys
) -> None:
    import json

    subject = C.EvidenceRefV2(
        session_id="literal-work",
        kind="product",
        object_id="decision",
        version=1,
        observed_at_seq=1,
    )
    source = subject.model_copy(update={"kind": "document", "object_id": "source"})
    fragment = subject.model_copy(update={"quote": "launch", "span_start": 7, "span_end": 13})
    raw = {
        "schema_version": 2,
        "item_id": "support",
        "task_type": "criterion",
        "criterion": "R2.support",
        "claim": "Evaluation responsibility: explain how evidence supports the decision.",
        "subjects": [subject.model_dump(mode="json")],
        "purpose": "commitment",
        "as_of": C.VersionPoint(
            business_seq=1, workspace_revision=1, storage_revision=1
        ).model_dump(mode="json"),
        "applicability": "applicable",
        "candidate_evidence": [
            C.CandidateEvidenceV2(
                id="whole-work", text="Do not launch; validation is incomplete.", ref=subject
            ).model_dump(mode="json"),
            C.CandidateEvidenceV2(
                id="independent-source", text="Validation is still open.", ref=source
            ).model_dump(mode="json"),
            C.CandidateEvidenceV2(id="partial-self-quote", text="launch", ref=fragment).model_dump(
                mode="json"
            ),
        ],
        "rule_context": {"mechanism": "v2.support"},
        "rule_bound": None,
        "completeness": "complete",
        "dropped_refs": [],
        "missing_refs": [],
    }
    item = registered_relation_input(
        C.EvidencePackageV2.model_validate(raw | {"input_hash": C.digest(raw)})
    )
    assert item.evidence.claim == "Do not launch; validation is incomplete."
    assert tuple(candidate.id for candidate in item.evidence.candidate_evidence) == (
        "independent-source",
    )
    assert item.evidence.criterion is None and item.task_type == "relation"
    _, _, ref = registered(tmp_path)
    path = tmp_path / "input.json"
    path.write_text(item.model_dump_json())
    assert (
        main(
            [
                "predict",
                "--registry",
                str(tmp_path / "registry"),
                "--registration-path",
                ref.path,
                "--registration-hash",
                ref.sha256,
                "--journal",
                str(tmp_path / "journal"),
                "--request-id",
                "literal-source-check",
                "--language",
                "en",
                "--allow-synthetic",
                "--input",
                str(path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["semantic_status"] == "synthetic_mechanism_only"
    assert result["public_prediction"]["status"] == "unavailable"
    assert result["affects_score"] is False
