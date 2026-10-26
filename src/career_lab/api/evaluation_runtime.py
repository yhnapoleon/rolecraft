"""scenario authorized sources/rules -> evaluation evidence -> the common fixed worker.

Only the frozen public source projection supplies material text. Business facts
carry either the source quote or the actual saved approval/configuration ref.
"""

import json
from collections import OrderedDict
from concurrent.futures import Future
from threading import Lock
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from sqlalchemy import select

from career_lab.api.business_record import latest_decisions, recorded_decisions
from career_lab.api.feedback_provenance import attach_score_range
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.extensions import _ConfigTestRuns, _RuleCheckFacts
from career_lab.evidence.v2.ports import CriterionPolicy
from career_lab.evidence.v2.preview import prepare_preview_feedback
from career_lab.evidence.v2.store_reader import FixedWindowReads, StoreEvidenceReader
from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator
from career_lab.rubrics.v4.score_range import installed_rubric
from career_lab.runtime.model_slots import DEFAULT_INPUT_BYTES, ModelSlots
from career_lab.scenarios.v2.release import require_evaluation
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import references
from career_lab.storage.v2_tables import v2_snapshots

if TYPE_CHECKING:
    from career_lab.api.registered_models import RegisteredModelFactory


class ScenarioEvidencePort:
    """Bind scenario's owned fact producer to real authorized store history."""

    def __init__(self, store, module):
        from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter

        self.store, self.module = store, module
        self._window_cache = {}
        self._record_cache = {}
        self._reference_cache = set()
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
        self.draft_submission_rules = lambda auth, draft: self.with_business_response(
            auth, adapter.draft_submission_rule_provider(auth, draft)
        )
        self.test_runs = adapter.test_runs

    def with_business_response(self, auth, snapshot):
        """State the recorded approval outcome, without grading the learner's choice."""
        from dataclasses import replace

        window = self.window(auth, snapshot.as_of)
        latest = latest_decisions(window.objects)
        if not latest:
            return snapshot
        decisions = []
        refs = []
        for request, row in latest:
            decision = row.content
            status = decision["status"]
            requested = next((r.requested for r in window.snapshot.requests if r.id == request), {})
            result = (
                decision.get("granted")
                if status in {"approved", "accepted"}
                else decision.get("countered", {})
            )
            decisions.append((requested, status, result or {}))
            refs.append(self.source(auth, row.ref, snapshot.as_of).ref)
        return replace(
            snapshot,
            business_response=recorded_decisions(self.module.work_language, decisions),
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
        # Exact historical values are immutable inside this one evaluator. Keep live
        # credential/object checks, but do not decode the same full window per criterion.
        self.store.authorize(auth, "read", object_ids=(ref.object_id,))
        key = C.digest(
            [auth.model_dump(mode="json"), ref.model_dump(mode="json"), at.model_dump(mode="json")]
        )
        if key not in self._record_cache:
            self._record_cache[key] = self.store.query_at(auth, at, lambda view: view.get(ref))
        return self._record_cache[key]

    def reference(self, auth, ref, at):
        def read(view):
            if view.reference_allowed is None or not view.reference_allowed(ref):
                raise C.ProtocolError("object_not_found", status=404)

        self.store.authorize(auth, "read", object_ids=(ref.object_id,))
        key = C.digest(
            [auth.model_dump(mode="json"), ref.model_dump(mode="json"), at.model_dump(mode="json")]
        )
        if key not in self._reference_cache:
            self.store.query_at(auth, at, read)
            self._reference_cache.add(key)


class OncePerInputModel:
    """A provider repair loop cannot silently repeat the same semantic input."""

    retries = 0

    def __init__(self, model):
        self.model, self.revision, self.seen = model, model.revision, set()
        self.provider = getattr(model, "provider", None)

    def complete(self, messages, tools):
        key = C.digest(messages[:2])
        if key in self.seen:
            raise RuntimeError("Explicit new review required after a failed model result")
        self.seen.add(key)
        return self.model.complete(messages, tools)


def create_feedback_handler(
    module,
    *,
    model=None,
    slots: ModelSlots | None = None,
    engine_factory: "RegisteredModelFactory | None" = None,
):
    """``slots`` gives the Judge and support verifier separately; else ``model`` serves both."""
    if slots is not None:
        judge, support = slots.judge, slots.support
        judge_bytes, support_bytes = slots.judge_input_bytes, slots.support_input_bytes
        judge_url = slots.recorded_base_url("JUDGE")
        support_url = slots.recorded_base_url("SUPPORT")
    else:
        judge = support = model
        judge_bytes = support_bytes = DEFAULT_INPUT_BYTES
        judge_url = support_url = None

    installed = installed_evaluation(module)
    if installed is None:
        return None
    bundle, policies = installed
    from career_lab.api.feedback_provenance import attach_provenance, feedback_provenance
    from career_lab.runtime.provenance import require_execution_snapshot

    provenance = feedback_provenance(
        module,
        bundle,
        judge,
        registered_model=engine_factory.identity if engine_factory is not None else None,
        registered_models=engine_factory.identities if engine_factory is not None else None,
        support=support,
        base_url=judge_url,
        support_base_url=support_url,
    )
    rubric, rubric_sha256 = installed_rubric(module.package.root, bundle)

    def traced(plan, reader, engine):
        from dataclasses import replace

        from career_lab.storage.v2_store import FeedbackReadTrace

        plan = attach_score_range(attach_provenance(plan, provenance), rubric, rubric_sha256)
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
            for index, outcome in enumerate(write.content.get("outcomes") or ()):
                sources = references(outcome) or references(write.content.get("input_refs", ()))
                traces.append(FeedbackReadTrace(write.ref, f"/outcomes/{index}", sources))
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
        from career_lab.evidence.v2.submission_evaluator import submission_feedback_plan
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
        from career_lab.recognition import registry as recognizers

        recognizing = recognizers.root() is not None
        verifier = EvidenceSupportVerifier(
            OncePerInputModel(support) if support is not None else None,
            input_bytes=support_bytes,
        )
        if recognizing:
            # SUPPORT slot: recognizers check support first, the LLM only when undecided.
            from career_lab.recognition.judge import RecognizerSupportVerifier

            verifier = RecognizerSupportVerifier(verifier)
        engine = (
            FeedbackEngine(
                AdvisoryJudge(OncePerInputModel(judge), verifier, input_bytes=judge_bytes)
            )
            if judge is not None
            else FeedbackEngine()
        )
        if engine_factory is not None:
            engine = engine_factory.create(engine, envelope)
        if recognizing:
            from career_lab.recognition.judge import RecognitionFeedback

            engine = RecognitionFeedback(
                engine,
                view=view,
                auth=auth,
                verifier=verifier if judge is not None else None,
                language=module.work_language,
            )
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
        if request.preview_kind is not None:
            prepared = prepare_preview_feedback(reader, request, auth, module.work_language, source)
            return traced(
                review_feedback_plan(view, envelope.command, auth, prepared), reader, engine
            )
        prepared = prepare_review_feedback(
            create_review_evaluator(reader, engine=engine, work_language=module.work_language),
            auth,
            request,
        )
        return traced(review_feedback_plan(view, envelope.command, auth, prepared), reader, engine)

    def audited_run(store, view, envelope, auth):
        from career_lab.runtime.model_audit import audit_scope, phase

        with audit_scope(session_id=auth.session_id, request_id=envelope.command.request_id):
            with phase("feedback_handler"):
                return run(store, view, envelope, auth)

    return audited_run


def installed_evaluation(module):
    """The installed evaluation bundle of ``module`` and its frozen criteria, or None when
    the package installs no evaluation."""
    bundle = C.EvaluationBundle.model_validate_json(
        C.read_file(module.package.root, module.bindings.evaluation)
    )
    protocol = json.loads(C.read_file(module.package.root, bundle.protocol))
    if not protocol.get("installed"):
        return None
    if protocol.get("owner") != "W05" or bundle.mode != "advisory":
        raise C.ProtocolError("evaluation_runtime_unavailable", status=503)
    require_evaluation(module.package.root, bundle, language=module.work_language)
    return bundle, tuple(CriterionPolicy(**p) for p in protocol["policies"])


class RuleCheckEvidencePort(ScenarioEvidencePort):
    """One HTTP rule check reuses its authorized, versioned historical window.

    This port is not used by the feedback/colleague/assistant model input builders.
    No result survives the request. Credentials and object scope are checked on
    every access; material references still use the store's exact-time resolver.
    """

    def record(self, auth, ref, at):
        if at is None:
            # The adapter verifies the saved submission identity at the live point.
            # Reading that single record need not project unrelated later feedback.
            return self.store.read(auth, ref)
        if auth.allowed_objects is not None:
            return super().record(auth, ref, at)
        self.store.authorize(auth, "read", object_ids=(ref.object_id,))
        window = self.window(auth, at)
        record = next((row for row in window.objects if row.ref == ref), None)
        if record is None:
            raise C.ProtocolError("object_not_found", status=404)
        return record

    def reference(self, auth, ref, at):
        if ref.kind == "material":
            # source_reader has already validated this exact window. Resolving a
            # material does not require projecting every saved feedback again.
            self.store.resolve_reference(auth, ref, storage_revision=at.storage_revision)
            return None
        return super().reference(auth, ref, at)


class SubmissionRuleChecks:
    """Read-only rule checks for sessions of one scenario module: the inputs a person is about
    to submit (draft), or a saved submission again at its own point (saved). The rule items
    come from the same evaluation the feedback worker runs. No model runs, nothing is written.
    """

    def __init__(self, module, policies):
        self.module = module
        self.policies = policies
        self._saved_cache = WeakKeyDictionary()
        self._cache_lock = Lock()

    def draft(self, store, auth, request: C.SubmissionRuleCheckRequest) -> C.SubmissionRuleCheck:
        source = RuleCheckEvidencePort(store, self.module)
        reader = self._reader(store, auth, source, source.draft_submission_rules)
        submission = unsaved_submission(store, auth, reader, request)
        return self._check(auth, source, reader, submission, "draft")

    def draft_recognition(self, store, auth, request: C.SubmissionRuleCheckRequest) -> dict:
        """The slower sentence step of a draft check (recognition layer, demo edition): the
        C2 + C1 + C6 labels of the work this input would submit, or ``enabled: False`` when the
        layer is off. Read-only, like the check; the rule check itself stays fast."""
        from career_lab.api.recognition_signal import recognition_enabled, sentence_preview

        if not recognition_enabled():
            return {"session_id": auth.session_id, "enabled": False, "recognition": None}

        source = ScenarioEvidencePort(store, self.module)
        reader = self._reader(store, auth, source, source.draft_submission_rules)
        submission = unsaved_submission(store, auth, reader, request)
        evaluator = SubmissionEvaluator(
            FixedWindowReads(reader), work_language=self.module.work_language
        )
        _, packages = evaluator.rule_items(auth, submission)

        def title_of(ref):
            if ref.kind != "material":
                return None
            try:
                return self.module.package.material(ref.object_id, ref.version).title
            except Exception:  # noqa: BLE001 - a title is a courtesy; the sentence stands without it
                return None

        return {
            "session_id": auth.session_id,
            "enabled": True,
            "recognition": sentence_preview(packages, self.module.work_language, title_of)
            if packages
            else None,
        }

    def saved(self, store, auth, submission_id: str) -> C.SubmissionRuleCheck:
        # Only the owner's unrestricted reads can reuse a result. The module is
        # bound to one immutable scenario/evaluation package; the store, complete
        # authorization and current persisted point isolate the remaining inputs.
        if (
            auth.actor_id != "learner"
            or auth.executor.kind != "human"
            or auth.allowed_objects is not None
        ):
            return self._saved_uncached(store, auth, submission_id)
        _, at = store.session_metadata(auth)
        key = (C.canonical(auth), C.canonical(at), submission_id)
        with self._cache_lock:
            cache = self._saved_cache.setdefault(store, OrderedDict())
            future = cache.get(key)
            compute = future is None
            if compute:
                future = Future()
                cache[key] = future
                # Bounded per store/package, including in-flight entries. Evicted
                # callers still own their Future and receive their result normally.
                while len(cache) > 64:
                    cache.popitem(last=False)
            else:
                cache.move_to_end(key)
        if compute:
            try:
                result = self._saved_uncached(store, auth, submission_id)
            except BaseException as error:
                with self._cache_lock:
                    if cache.get(key) is future:
                        del cache[key]
                future.set_exception(error)
                raise
            future.set_result(result)
        result = future.result()
        # Waiting on another reader is not permission to outlive a revocation.
        store.authorize(auth, "read")
        return result.model_copy(deep=True)

    def _saved_uncached(self, store, auth, submission_id: str) -> C.SubmissionRuleCheck:
        submission = saved_submission(store, auth, submission_id)
        source = RuleCheckEvidencePort(store, self.module)
        reader = self._reader(
            store, auth, source, source.submission_rules, capture_at=submission.as_of
        )
        return self._check(auth, source, reader, submission, "saved")

    def _reader(self, store, auth, source, submission_rules, *, capture_at=None):
        return StoreEvidenceReader(
            store,
            auth,
            policies=self.policies,
            source_reader=source.source,
            rule_provider=source.rules,
            submission_rule_provider=submission_rules,
            capture_at=capture_at,
        )

    def _check(self, auth, source, reader, submission, basis):
        evaluator = SubmissionEvaluator(
            FixedWindowReads(reader), work_language=self.module.work_language
        )
        rule_items, packages = evaluator.rule_items(auth, submission)
        runs = source.test_runs(auth, submission.as_of) if packages else ()
        from career_lab.api.recognition_signal import recognition_enabled

        return C.SubmissionRuleCheck(
            basis=basis,
            session_id=auth.session_id,
            as_of=submission.as_of,
            submission=submission_ref(submission) if basis == "saved" else None,
            decision=submission.decision,
            products=submission.products,
            config=submission.config,
            evaluation=submission.evaluation,
            work_language=self.module.work_language,
            rule_items=rule_items,
            facts=rule_check_facts(packages, runs),
            # Only the writing-area preview shows sentence labels, and only with the recognition
            # layer on. The C1 pass costs seconds on CPU, so the check says it is pending and the
            # sentence step (draft_recognition) computes it after the rule items are on screen.
            recognition={"status": "pending"}
            if packages and basis == "draft" and recognition_enabled()
            else None,
        )


def rule_check_facts(packages, runs):
    """The verified facts the criteria were judged on, for the reader to phrase. Every
    criterion of one submission carries the same verified facts."""
    facts = {}
    for package in packages:
        facts.update(package.rule_context["facts"])
    updated = facts.get("affected_material_versions") or {}
    return _RuleCheckFacts(
        participants=facts.get("participants"),
        capacity=facts.get("capacity"),
        required_dev_days=facts.get("required_dev_days"),
        available_dev_days=facts.get("available_dev_days"),
        requested_launch_day=facts.get("requested_launch_day"),
        deadline_day=facts.get("deadline_day"),
        unapproved_resource_excess=facts.get("unapproved_resource_excess"),
        config_version=packages[0].rule_context["config_version"] if packages else None,
        policy_version=updated.get("policy"),
        adjustment_actions=facts.get("adjustment_action_count"),
        test_runs=tuple(
            _ConfigTestRuns(config_version=run.config_version, runs=run.runs, retests=run.retests)
            for run in runs
        ),
    )


def create_rule_checks(module):
    """None when the package installs no usable evaluation: the check is an optional read and
    never stops a runtime from starting; submitting reports the evaluation state itself."""
    try:
        installed = installed_evaluation(module)
    except C.ProtocolError:
        return None
    return None if installed is None else SubmissionRuleChecks(module, installed[1])


def unsaved_submission(store, auth, reader, request):
    """What submitting ``request`` now would save. It is built in memory and never written;
    the state must be the one the request was made against."""

    def current(view):
        return view.state, view.bindings, view.current_cycle

    state, bindings, cycle = store.query(auth, current)
    if state.status == "submitted":
        raise C.ProtocolError("session_submitted")
    if state.status == "paused":
        raise C.ProtocolError("session_paused")
    if cycle is None:
        raise C.ProtocolError("revision_cycle_required")
    at = reader.captured_at
    if (at.business_seq, at.workspace_revision) != (
        request.expected_version,
        request.expected_workspace_revision,
    ):
        raise C.ProtocolError("version_conflict", status=409)
    body = request.payload
    return C.SubmissionV2(
        id=C.digest(
            [
                auth.session_id,
                body.model_dump(mode="json"),
                at.model_dump(mode="json"),
                "unsaved-submission",
            ]
        ),
        session_id=auth.session_id,
        cycle=cycle.ref,
        decision=body.decision,
        products=body.products,
        config=body.config,
        evidence_refs=body.evidence_refs,
        as_of=at,
        scenario=bindings.scenario,
        evaluation=reader.evaluation,
        executor=auth.executor,
    )


def saved_submission(store, auth, submission_id):
    # record_submission freezes a fresh identity at version 1; a revision is another
    # submission, never an edit of this object. Project only that authorized record.
    ref = C.ObjectRef(
        session_id=auth.session_id, kind="submission", object_id=submission_id, version=1
    )
    return C.SubmissionV2.model_validate(store.read(auth, ref).content)


def submission_ref(submission):
    return C.ObjectRef(
        session_id=submission.session_id,
        kind="submission",
        object_id=submission.id,
        version=submission.version,
    )
