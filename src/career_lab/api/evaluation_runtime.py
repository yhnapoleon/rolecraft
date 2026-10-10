"""scenario authorized sources/rules -> evaluation evidence -> the common fixed worker.

Only the frozen public source projection supplies material text. Business facts
carry either the source quote or the actual saved approval/configuration ref.
"""

import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_tables import v2_snapshots

if TYPE_CHECKING:
    from career_lab.api.registered_models import RegisteredModelFactory


class ScenarioEvidencePort:
    """Bind scenario's owned fact producer to real authorized store history."""

    def __init__(self, store, module):
        from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter

        self.store, self.module = store, module
        self._window_cache = {}
        adapter = ScenarioFactAdapter(
            module,
            authorize=lambda auth: store.authorize(auth, "read"),
            window_reader=self.window,
            record_reader=self.record,
            reference_resolver=self.reference,
        )
        self.source = adapter.source_reader
        self.rules = lambda auth, ref, at: self.with_business_response(
            auth, adapter.rule_provider(auth, ref, at)
        )
        self.submission_rules = lambda auth, submission: self.with_business_response(
            auth, adapter.submission_rule_provider(auth, submission)
        )

    def with_business_response(self, auth, snapshot):
        """State the recorded approval outcome, without grading the learner's choice."""
        from dataclasses import replace

        window = self.window(auth, snapshot.as_of)
        latest = {}
        for row in window.objects:
            if row.ref.kind != "business_decision":
                continue
            request = row.content.get("request", {}).get("object_id")
            if request and (
                request not in latest
                or row.created_storage_revision > latest[request].created_storage_revision
            ):
                latest[request] = row
        if not latest:
            return snapshot
        en = self.module.work_language == "en"
        labels = {
            "capacity": "Seats" if en else "名额",
            "dev_days": "Developer-days" if en else "开发人日",
            "deadline_day": "Deadline day" if en else "截止日",
        }
        statuses = {
            "approved": "Approved" if en else "已批准",
            "accepted": "Accepted" if en else "已接受",
            "rejected": "Declined" if en else "未批准",
            "countered": "Counteroffer awaiting acceptance" if en else "还价待接受",
        }

        def terms(values):
            return ", ".join(
                labels[key] + ": " + str(value) for key, value in values.items() if key in labels
            )

        lines = []
        refs = []
        for request, row in latest.items():
            decision = row.content
            status = decision["status"]
            requested = next((r.requested for r in window.snapshot.requests if r.id == request), {})
            result = (
                decision.get("granted")
                if status in {"approved", "accepted"}
                else decision.get("countered", {})
            )
            lines.append(
                (
                    ("Requested " if en else "申请：")
                    + terms(requested)
                    + "; "
                    + statuses.get(status, "Awaiting verification" if en else "待核验")
                    + ("; " + terms(result) if result else "")
                )
            )
            refs.append(self.source(auth, row.ref, snapshot.as_of).ref)
        return replace(
            snapshot,
            business_response=(
                "Recorded business decisions (rule checked): "
                if en
                else "已记录的业务决定（规则核实）："
            )
            + "\n".join(lines),
            business_response_refs=tuple(refs),
        )

    def points(self, auth, at):
        self.store.authorize(auth, "read")
        with self.store.db.engine.connect() as conn:
            return tuple(
                point(C.WorldStateV2.model_validate_json(raw))
                for raw in conn.execute(
                    select(v2_snapshots.c.state).where(
                        v2_snapshots.c.session_id == auth.session_id,
                        v2_snapshots.c.storage_revision <= at.storage_revision,
                    )
                ).scalars()
            )

    def window(self, auth, at):
        # Per-job memoization of immutable, authorization-scoped historical data.
        # Authorization is rechecked even when the original projection is reused.
        self.store.authorize(auth, "read")
        cache_key = C.digest([auth.model_dump(mode="json"), at.model_dump(mode="json")])
        if cache_key in self._window_cache:
            return self._window_cache[cache_key]
        from career_lab.scenarios.v2.evaluation_facts import ScenarioEvidenceWindow
        from career_lab.storage.v2_store import TransactionResult
        from career_lab.storage.v2_tables import v2_transactions

        points = self.points(auth, at)
        with self.store.db.engine.connect() as conn:
            transactions = [
                TransactionResult.model_validate_json(raw)
                for raw in conn.execute(
                    select(v2_transactions.c.result).where(
                        v2_transactions.c.session_id == auth.session_id
                    )
                ).scalars()
            ]
        completed = {
            t.transaction_id: point(t.state)
            for t in transactions
            if t.state.storage_revision <= at.storage_revision
        }

        def read(view):
            events = []
            cursor = 0
            complete = auth.allowed_objects is None and callable(view.public_history)
            while cursor < at.business_seq:
                if view.public_history is None:
                    complete = False
                    break
                history = view.public_history(C.ResourcePage(since_seq=cursor, limit=100), auth)
                if not history.acquisitions_complete or history.next_seq <= cursor:
                    complete = False
                    break
                events.extend(history.events)
                cursor = history.next_seq
            pairs = tuple(
                (event, completed[event.transaction_id])
                for event in events
                if event.transaction_id in completed
            )
            return ScenarioEvidenceWindow(
                self.module.snapshot(view),
                view.bindings,
                view.objects,
                pairs,
                points,
                tests_complete=auth.allowed_objects is None,
                events_complete=complete and len(pairs) == len(events),
            )

        result = self.store.query_at(auth, at, read)
        self._window_cache[cache_key] = result
        return result

    def record(self, auth, ref, at):
        if at is None:
            return self.store.query(auth, lambda view: view.get(ref))
        return self.store.query_at(auth, at, lambda view: view.get(ref))

    def reference(self, auth, ref, at):
        def read(view):
            if view.reference_allowed is None or not view.reference_allowed(ref):
                raise C.ProtocolError("object_not_found", status=404)

        return self.store.query_at(auth, at, read)


class OncePerInputModel:
    """A provider repair loop cannot silently repeat the same semantic input."""

    retries = 0

    def __init__(self, model):
        self.model, self.revision, self.seen = model, model.revision, set()

    def complete(self, messages, tools):
        key = C.digest(messages[:2])
        if key in self.seen:
            raise RuntimeError("Explicit new review required after a failed model result")
        self.seen.add(key)
        return self.model.complete(messages, tools)


def create_feedback_handler(
    module, *, model=None, engine_factory: "RegisteredModelFactory | None" = None
):
    from career_lab.evidence.v2.ports import CriterionPolicy

    bundle = C.EvaluationBundle.model_validate_json(
        C.read_file(module.package.root, module.bindings.evaluation)
    )
    protocol = json.loads(C.read_file(module.package.root, bundle.protocol))
    if not protocol.get("installed"):
        return None
    if protocol.get("owner") != "W05" or bundle.mode != "advisory":
        raise C.ProtocolError("evaluation_runtime_unavailable", status=503)
    from career_lab.api.feedback_provenance import attach_provenance, feedback_provenance
    from career_lab.runtime.provenance import require_execution_snapshot
    from career_lab.scenarios.v2.release import require_evaluation

    require_evaluation(module.package.root, bundle, language=module.work_language)
    provenance = feedback_provenance(
        module,
        bundle,
        model,
        registered_model=engine_factory.identity if engine_factory is not None else None,
    )
    policies = tuple(CriterionPolicy(**p) for p in protocol["policies"])

    def traced(plan, reader, engine):
        from dataclasses import replace

        from career_lab.storage.v2_store import FeedbackReadTrace

        plan = attach_provenance(plan, provenance)
        traces = []
        for write in plan.writes:
            at = C.FeedbackV2.model_validate(write.content).as_of
            deps = {C.canonical(ref): ref for ref in write.dependencies}
            for record in reader.records.values():
                if record.created_at is None or any(
                    getattr(record.created_at, k) > getattr(at, k)
                    for k in ("business_seq", "workspace_revision", "storage_revision")
                ):
                    continue
                ref = C.ObjectRef.model_validate(
                    {
                        k: v
                        for k, v in record.ref.model_dump(mode="json").items()
                        if k in C.ObjectRef.model_fields
                    }
                )
                deps[C.canonical(ref)] = ref
            for name in ("verified_facts", "historical_responsibilities"):
                for i, _ in enumerate(write.content.get(name) or ()):
                    traces.append(
                        FeedbackReadTrace(write.ref, f"/{name}/{i}", tuple(deps.values()))
                    )
            for name in ("items", "rule_items"):
                for i, _ in enumerate(write.content.get(name) or ()):
                    traces.append(
                        FeedbackReadTrace(
                            write.ref, f"/{name}/{i}/explanation", tuple(deps.values())
                        )
                    )
            for name in ("business_response", "next_options", "independent_understanding"):
                if name in write.content:
                    traces.append(FeedbackReadTrace(write.ref, "/" + name, tuple(deps.values())))
            if engine_factory is not None:
                for index, advice in enumerate(write.content.get("model_advice") or ()):
                    traces.append(
                        FeedbackReadTrace(
                            write.ref,
                            f"/model_advice/{index}",
                            engine.dependencies[advice["input_hash"]],
                        )
                    )
        return replace(plan, feedback_read_traces=tuple(traces))

    def run(store, view, envelope, auth):
        from career_lab.api.reviews_v2 import (
            create_review_evaluator,
            prepare_review_feedback,
            review_feedback_plan,
        )
        from career_lab.evidence.v2.store_reader import StoreEvidenceReader
        from career_lab.evidence.v2.submission_evaluator import (
            SubmissionEvaluator,
            submission_feedback_plan,
        )
        from career_lab.rubrics.v4.feedback import FeedbackEngine
        from career_lab.rubrics.v4.judge import AdvisoryJudge
        from career_lab.rubrics.v4.support import EvidenceSupportVerifier

        require_execution_snapshot(provenance.code)
        module.check_bindings(view.bindings)
        source = ScenarioEvidencePort(store, module)
        reader = StoreEvidenceReader(
            store,
            auth,
            policies=policies,
            source_reader=source.source,
            rule_provider=source.rules,
            submission_rule_provider=source.submission_rules,
        )
        engine = (
            FeedbackEngine(
                AdvisoryJudge(
                    OncePerInputModel(model), EvidenceSupportVerifier(OncePerInputModel(model))
                )
            )
            if model is not None
            else FeedbackEngine()
        )
        if engine_factory is not None:
            engine = engine_factory.create(engine, envelope)
        subject = C.FeedbackInput.model_validate(envelope.command.payload).subject
        if subject.kind == "submission":
            submitted = C.SubmissionV2.model_validate(view.get(subject).content)
            prepared = SubmissionEvaluator(
                reader, engine=engine, work_language=module.work_language
            ).evaluate(auth, submitted)
            return traced(
                submission_feedback_plan(view, envelope.command, auth, prepared), reader, engine
            )
        request = C.ReviewRequest.model_validate(view.get(subject).content)
        prepared = prepare_review_feedback(
            create_review_evaluator(reader, engine=engine, work_language=module.work_language),
            auth,
            request,
        )
        return traced(review_feedback_plan(view, envelope.command, auth, prepared), reader, engine)

    return run
