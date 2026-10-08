import json

from sqlalchemy import select

from career_lab.assistant.retrieval import retrieve
from career_lab.contracts.actions import EvidenceRef
from career_lab.contracts.evaluation import (
    CandidateEvidence,
    EvidencePackage,
    RuleContext,
    TestObservation,
)
from career_lab.evidence.serializer import model_input, seal_input
from career_lab.storage.database import objects
from career_lab.storage.sessions import canonical


class EvidenceAssembler:
    def __init__(self, store, token_budget=16000):
        self.store, self.token_budget = store, token_budget

    def assemble_item(self, submission_id: str, criterion_id: str, mode: str) -> EvidencePackage:
        if mode not in {"oracle", "retrieved"}:
            raise ValueError("mode must be oracle or retrieved")
        with self.store.db.engine.connect() as conn:
            row = conn.execute(
                select(objects.c.session_id).where(
                    objects.c.id == submission_id, objects.c.kind == "submission"
                )
            ).first()
            if row is None:
                raise KeyError("submission not found")
            sid = row[0]
        sub = self.store.get_object(sid, submission_id, "submission")
        state = self.store.get_state(sid, sub["as_of_seq"])
        spec = self.store.get_spec(sid)
        criterion = next((c for c in spec.rubric.criteria if c.id == criterion_id), None)
        if not criterion:
            raise ValueError("unknown criterion")
        artifact = self.store.get_object(sid, sub["artifact_id"], "artifact")
        view = self.store.project_view(sid, "learner", sub["as_of_seq"])
        candidates, refs = [], {}

        def add(text, ref):
            eid = f"e{len(candidates) + 1}"
            candidates.append(CandidateEvidence(id=eid, version=ref.version, text=text))
            refs[eid] = ref

        for material in sorted(view.permitted_materials, key=lambda m: (m.id, m.version)):
            add(
                material.content,
                EvidenceRef(
                    kind="document",
                    object_id=material.id,
                    version=material.version,
                    observed_at_seq=sub["as_of_seq"],
                ),
            )
        add(
            canonical(state.configs["pilot"]),
            EvidenceRef(
                kind="config",
                object_id=sid,
                version=sub["config_version"],
                observed_at_seq=sub["as_of_seq"],
            ),
        )
        add(
            canonical(artifact["content"]),
            EvidenceRef(
                kind="artifact",
                object_id=artifact["id"],
                version=artifact["version"],
                observed_at_seq=sub["as_of_seq"],
            ),
        )
        # Complete ledger is authoritative about absence of approval, not merely retrieved text.
        add(
            canonical(
                {
                    "current_resources": state.resources,
                    "applied_rules": state.applied_rules,
                    "approval_ledger_complete": True,
                }
            ),
            EvidenceRef(
                kind="event",
                object_id=f"{sid}:ledger",
                version=state.version or 1,
                observed_at_seq=sub["as_of_seq"],
            ),
        )
        test_records = [
            t for t in self.store.list_objects(sid, "test") if t["as_of_seq"] < sub["as_of_seq"]
        ]
        history = [e for e in self.store.events(sid) if e.seq <= sub["as_of_seq"]]
        expected_tests = {
            e.payload["object_id"] for e in history if e.event_type == "test_assistant"
        }
        logs_complete = [e.seq for e in history] == list(
            range(1, sub["as_of_seq"] + 1)
        ) and expected_tests == {t["id"] for t in test_records}
        policy_seq = next((e.seq for e in history if e.event_type == "policy_updated"), None)
        for record in test_records:
            add(
                canonical(record),
                EvidenceRef(
                    kind="test_result",
                    object_id=record["id"],
                    version=1,
                    observed_at_seq=record["as_of_seq"],
                ),
            )
        context = RuleContext(
            **state.resources,
            plan=state.configs["pilot"],
            deliverable=artifact["content"],
            tests=tuple(
                TestObservation(
                    **{
                        k: t[k]
                        for k in ("id", "query", "fallback", "stale", "config_version", "as_of_seq")
                    }
                )
                for t in test_records
            ),
            work_costs={w.id: w.dev_days for w in spec.work_items},
            approvals=state.applied_rules,
            policy_updated="policy_updated" in state.applied_rules,
            logs_complete=logs_complete,
            config_version=sub["config_version"],
            policy_update_seq=policy_seq,
        )
        completeness = "complete"
        if mode == "retrieved":
            hits = retrieve(
                criterion.description, [{"id": c.id, "text": c.text} for c in candidates], limit=4
            )
            selected = {h["id"] for h in hits}
            candidates = [c for c in candidates if c.id in selected]
            # Retrieval completeness is unproven; do not silently score missing evidence.
            completeness, context = "missing", None
        item = EvidencePackage(
            item_id=f"{submission_id}:{criterion_id}:{mode}",
            task_type="criterion",
            criterion=criterion_id,
            claim=criterion.description + "\n" + artifact["content"]["rationale"],
            as_of_seq=sub["as_of_seq"],
            candidate_evidence=tuple(candidates),
            completeness=completeness,
            context=context,
            source_map={c.id: refs[c.id] for c in candidates},
        )
        # UTF-8 byte count is a conservative BPE upper-bound; no silent truncation.
        if len(canonical(model_input(item)).encode("utf-8")) > self.token_budget:
            item = item.model_copy(
                update={
                    "candidate_evidence": (),
                    "source_map": {},
                    "context": None,
                    "completeness": "overflow",
                }
            )
        return seal_input(item)
