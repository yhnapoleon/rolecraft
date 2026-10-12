"""EXP-07: the authorized export carries one relation record per sentence of the learner's work.

The sentences are cut by the product's own R2.support splitting (``r2-support-units-v1``),
so each exported sentence has the ``unit_hash`` of the unit the registered model judged in
feedback. The records sit beside the assistant-answer relation records and are told apart
by ``relation_source`` in the evaluator-side source map. No gold enters a model input.
The registration is constructed fixed weights (scope synthetic_fixture), never trained.
"""

import json
from pathlib import Path

import pytest

from career_lab.jobs.worker import Worker
from career_lab.models.v3.registry import register_bundle
from tests.integration.test_live_export import LiveSession, command
from tests.integration.test_support_units import THREE_PARAGRAPHS, marker_bundle

# Keys that would carry hidden probes, gold or rule derivations into a model input.
FORBIDDEN = {"probe", "probes", "hidden_probes", "gold", "gold_label", "label", "rule_bound"}


def keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


class UnitSession(LiveSession):
    """A live session whose submitted work is the three-paragraph R2.support sample."""

    def submit_three_paragraphs(self) -> dict:
        read = self.send(
            "actions",
            "read",
            "read_material",
            {
                "tool": "read_material",
                "material": {
                    "schema_version": 2,
                    "session_id": self.session_id,
                    "kind": "material",
                    "object_id": "brief",
                    "version": 1,
                },
            },
        )
        self.content = THREE_PARAGRAPHS[self.language]
        made = self.send(
            "work-products",
            "draft",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": "Decision",
                "content": self.content,
                "evidence_refs": [read["result"]["fragments"][1]["ref"]],
            },
        )
        self.product = next(ref for ref in made["objects"] if ref["kind"] == "product")
        self.send(
            "tests",
            "trial",
            "tests.create",
            {
                "query": "What is the hotel reimbursement limit?"
                if self.language == "en"
                else "住宿报销上限是多少？",
                "config_version": 0,
            },
        )
        submitted = self.send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [self.product]},
        )
        assert Worker(self.app.state.jobs, self.app.state.handlers).run_once()
        feedback = self.client.get(
            "/sessions/"
            + self.session_id
            + "/feedback/"
            + submitted["result"]["submission"]["object_id"],
            headers=self.headers,
        )
        assert feedback.status_code == 200, feedback.text
        report = feedback.json()["result"]["result"]["items"][0]
        (advice,) = [row for row in report["model_advice"] if row["criterion"] == "R2.support"]
        return advice


@pytest.mark.parametrize("language", ["zh", "en"])
def test_exp_07_work_sentences_are_exported_with_the_inference_unit_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    bundle_root, bundle_ref = marker_bundle(tmp_path / "model")
    registration = register_bundle(
        tmp_path / "registry", bundle_root, bundle_ref, scope="synthetic_fixture"
    )
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(tmp_path / "registry"))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", registration.model_dump_json())
    monkeypatch.setenv("CAREER_LAB_MODEL_JOURNAL", str(tmp_path / "journal"))
    session = UnitSession(tmp_path, language)
    try:
        advice = session.submit_three_paragraphs()
        assert advice["status"] == "synthetic_mechanism_only"
        judged = [(unit["unit_hash"], unit["subject"]["quote"]) for unit in advice["units"]]
        assert len(judged) == 6
        session.authorize()
        plain = session.export(tmp_path / "plain")
        output = tmp_path / "export"
        response = command(
            "export",
            "--live",
            *session.connection(),
            "--output",
            output,
            "--key-file",
            session.key_file,
            "--authorization",
            session.grant_file,
            "--relation-units",
        )
    finally:
        session.close()
    assert response.returncode == 0, response.stdout + response.stderr
    assert plain.returncode == 0, plain.stdout + plain.stderr
    # Without the option the export is the existing one: only the assistant answer.
    assert json.loads(plain.stdout)["families"]["relation"]["records"] == 1
    summary = json.loads(response.stdout)
    sources = json.loads((output / "audit/source-map.json").read_text())
    rows = {
        row["record_id"]: row
        for line in (output / "data/train.inputs.jsonl").read_text().splitlines()
        for row in [json.loads(line)]
    }
    relation = {
        rid: sources[rid]
        for rid, row in rows.items()
        if row["model_input"]["task_type"] == "relation"
    }
    by_source: dict[str, list[str]] = {}
    for rid, entry in relation.items():
        by_source.setdefault(entry.get("relation_source"), []).append(rid)
    assert sorted(by_source) == ["assistant_answer", "work_unit"]
    assert len(by_source["assistant_answer"]) == 1
    units = sorted(
        (sources[rid]["unit_index"], sources[rid]["unit_hash"], rid)
        for rid in by_source["work_unit"]
    )
    # Same sentences, same order, same unit identity as the units the model judged.
    assert [
        (unit_hash, rows[rid]["model_input"]["evidence"]["claim"]) for _, unit_hash, rid in units
    ] == judged
    assert all(sources[rid]["unit_policy"] == "r2-support-units-v1" for _, _, rid in units)
    assert summary["families"]["relation"]["records"] == 7
    for _, _, rid in units:
        evidence = rows[rid]["model_input"]["evidence"]
        assert evidence["rule_bound"] is None
        assert set(evidence["rule_context"]) == {"evidence_time_context"}
        assert not keys(evidence["candidate_evidence"]) & FORBIDDEN
        assert {"probe", "probes", "hidden_probes", "gold", "gold_label"}.isdisjoint(keys(evidence))
        (subject,) = evidence["subjects"]
        assert subject["quote"] == evidence["claim"]
        # The work itself never serves as its own candidate evidence.
        assert all(c["text"] != session.content for c in evidence["candidate_evidence"])
    labels = [
        json.loads(line) for line in (output / "data/train.labels.jsonl").read_text().splitlines()
    ]
    assert all(label["status"] == "pending" for label in labels)
    audit = command("validate-data", "--export", output)
    assert audit.returncode == 0, audit.stdout + audit.stderr
