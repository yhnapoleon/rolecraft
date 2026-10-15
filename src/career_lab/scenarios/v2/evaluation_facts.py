"""Trusted scenario fact producers for evaluation. No database, rubric policy or model calls.

The integrator supplies exact authorized history windows and existing object /
reference reads. A window is an in-process value, never an HTTP input schema.
Missing history/classification remains unknown. No learner text becomes a fact.
"""

from dataclasses import dataclass
import re
from career_lab.contracts.v2 import (
    AssistantConfig,
    BusinessDecision,
    EvidenceRefV2,
    ObjectRef,
    ProtocolError,
    SubmissionV2,
    TestResultV2,
    VersionPoint,
    canonical,
)
from career_lab.evidence.v2.ports import (
    RuleSnapshot,
    SourceRecord,
    VerifiedFact,
    model_generated,
    record_text,
)
from .engine import ScenarioSnapshot
from .module import point, ref_for
from .policy import effective_config, canonical_domains


@dataclass(frozen=True)
class ScenarioEvidenceWindow:
    snapshot: ScenarioSnapshot
    bindings: object
    objects: tuple = ()
    # (actual public event, actual completed transaction point)
    events: tuple = ()
    # Actual stored snapshot points, keyed by storage_revision. Never guessed.
    points: tuple = ()
    tests_complete: bool = False
    events_complete: bool = False


def before(a, b):
    return all(
        getattr(a, k) <= getattr(b, k)
        for k in ("business_seq", "workspace_revision", "storage_revision")
    )


def bare(ref):
    return ObjectRef.model_validate(
        {k: v for k, v in ref.model_dump(mode="json").items() if k in ObjectRef.model_fields}
    )


def hotel_question(query, locale):
    q = re.sub(r"[\s?？。.!！,，]", "", query).casefold()
    values = (
        (
            "住宿报销上限是多少",
            "国内出差住宿每晚的报销上限",
            "出差住宿报销一晚能报多少",
            "住宿报销金额",
        )
        if locale == "zh"
        else (
            "whatisthehotelreimbursementlimitpernight",
            "whatisthehotelreimbursementlimit",
            "whatisthemaximumhotelreimbursementpernight",
        )
    )
    return q in values


def test_materials(test):
    """Materials the test answer cited or retrieved from."""
    return {c.object_id for c in test.citations} | {c.material_id for c in test.execution.chunks}


def relevant_to_policy(test, locale):
    """The test checks the policy: it asked the hotel question or used the policy."""
    return "policy" in test_materials(test) or hotel_question(test.query, locale)


@dataclass(frozen=True)
class ConfigTestRuns:
    """Actual runs on one configuration version; retests followed the current policy update."""

    config_version: int
    runs: int
    retests: int


class ScenarioFactAdapter:
    def __init__(self, module, *, authorize, window_reader, record_reader, reference_resolver):
        self.module = module
        self.authorize = authorize
        self.window_reader = window_reader
        self.record_reader = record_reader
        self.reference_resolver = reference_resolver

    def window(self, auth, at):
        self.authorize(auth)
        if auth.actor_id != "learner":
            raise ProtocolError("public_actor_required", status=403)
        window = self.window_reader(auth, at)
        if (
            window.snapshot.world.session_id != auth.session_id
            or point(window.snapshot.world) != at
        ):
            raise ProtocolError("rule_snapshot_time_mismatch", status=409)
        self.module.check_bindings(window.bindings)
        if at not in window.points:
            raise ProtocolError("source_time_unknown")
        return window

    def object(self, auth, ref, at):
        self.authorize(auth)
        if ref.session_id != auth.session_id:
            raise ProtocolError("object_not_found", status=404)
        row = self.record_reader(auth, bare(ref), at)
        if row.ref != bare(ref) or row.created_storage_revision > at.storage_revision:
            raise ProtocolError("evidence_version_mismatch")
        return row

    def source_reader(self, auth, ref, as_of):
        window = self.window(auth, as_of)
        if ref.session_id != auth.session_id:
            raise ProtocolError("object_not_found", status=404)
        if ref.kind == "material":
            self.reference_resolver(auth, ref, as_of)
            material = self.module.package.material(ref.object_id, ref.version)
            # The evaluator receives learner-readable original documents only.
            if any(
                f.disclosure.mode != "public"
                or (f.disclosure.actors and auth.actor_id not in f.disclosure.actors)
                for f in material.fragments
            ):
                raise ProtocolError("material_unavailable", status=404)
            activation = window.snapshot.material_activation.get(f"{ref.object_id}:{ref.version}")
            if activation is None or activation > as_of.business_seq:
                raise ProtocolError("material_unavailable", status=404)
            born = min(
                (p for p in window.points if p.business_seq >= activation and before(p, as_of)),
                key=lambda p: p.storage_revision,
                default=None,
            )
            if born is None:
                raise ProtocolError("source_time_unknown")
            path = self.module.package.rules["material_files"][ref.object_id][str(ref.version)]
            from career_lab.contracts.v2 import read_file

            text = read_file(self.module.package.root, self.module.files[path]).decode()
            actual = (
                ref
                if isinstance(ref, EvidenceRefV2)
                else EvidenceRefV2(
                    **ref.model_dump(),
                    observed_at_seq=as_of.business_seq,
                    valid_from_seq=activation,
                )
            )
            if actual.valid_from_seq != activation:
                raise ProtocolError("evidence_time_mismatch")
            return SourceRecord(actual, text, born)
        if ref.kind == "event":
            found = [(e, p) for e, p in window.events if e.id == ref.object_id and before(p, as_of)]
            if len(found) != 1:
                raise ProtocolError("object_not_found", status=404)
            event, born = found[0]
            if event.session_id != auth.session_id or ref.version != 1:
                raise ProtocolError("object_not_found", status=404)
            actual = EvidenceRefV2(**bare(ref).model_dump(), observed_at_seq=event.seq)
            if isinstance(ref, EvidenceRefV2) and (
                ref.observed_at_seq != event.seq or ref.valid_from_seq != 0
            ):
                raise ProtocolError("evidence_time_mismatch")
            return SourceRecord(actual, canonical(event), born)
        row = self.object(auth, ref, as_of)
        born = next(
            (p for p in window.points if p.storage_revision == row.created_storage_revision), None
        )
        if born is None:
            raise ProtocolError("source_time_unknown")
        actual = EvidenceRefV2(**row.ref.model_dump(), observed_at_seq=born.business_seq)
        return SourceRecord(actual, record_text(row.ref.kind, row.content), born)

    def rule_provider(self, auth, exact_product, as_of):
        row = self.object(auth, exact_product, as_of)
        if row.ref.kind != "product":
            raise ProtocolError("review_subject_required")
        from career_lab.contracts.v2 import WorkProductVersion

        product = WorkProductVersion.model_validate(row.content)
        refs = {
            canonical(bare(ref)): bare(ref) for ref in product.evidence_refs if ref.kind == "config"
        }
        # An exploratory work without an exact config link is not a commitment
        # to the current global configuration.
        config_ref = next(iter(refs.values())) if len(refs) == 1 else None
        return self._snapshot(auth, as_of, (exact_product,), config_ref, False)

    def submission_rule_provider(self, auth, saved_submission):
        ref = ObjectRef(
            session_id=auth.session_id,
            kind="submission",
            object_id=saved_submission.id,
            version=saved_submission.version,
        )
        self.authorize(auth)
        # Submission is created after its frozen as_of. Read at the current
        # authorized window solely to verify its identity, not its rule facts.
        stored = self.record_reader(auth, ref, None)
        if SubmissionV2.model_validate(stored.content) != saved_submission:
            raise ProtocolError("submission_input_changed")
        for product in saved_submission.products:
            self.object(auth, product, saved_submission.as_of)
        return self._submission_snapshot(auth, saved_submission)

    def draft_submission_rule_provider(self, auth, draft):
        """The rule facts these inputs get once submitted. ``draft`` is never saved."""
        self.authorize(auth)
        if draft.session_id != auth.session_id:
            raise ProtocolError("object_not_found", status=404)
        for product in draft.products:
            self.object(auth, product, draft.as_of)
        return self._submission_snapshot(auth, draft)

    def _submission_snapshot(self, auth, submission):
        return self._snapshot(
            auth,
            submission.as_of,
            submission.products,
            submission.config,
            submission.decision in {"launch", "launch_narrow"},
        )

    def test_runs(self, auth, at):
        """Actual runs per configuration version up to ``at``, with the retests among them
        that followed the current policy update. Technical failures are not runs. Without a
        complete test and event ledger the counts stay unknown (empty)."""
        window = self.window(auth, at)
        updates = self._policy_updates(window, at)
        if (
            not (window.tests_complete and window.events_complete)
            or window.snapshot.source_versions["policy"] != self._initial_policy()
            and not updates
        ):
            return ()
        since = max((event.seq for event, _ in updates), default=None)
        counts = {}
        for row in window.objects:
            if row.ref.kind != "test" or row.created_storage_revision > at.storage_revision:
                continue
            test = TestResultV2.model_validate(self.object(auth, row.ref, at).content)
            version = test.config_ref.config_version
            if test.status == "failed" or version is None or not before(test.as_of, at):
                continue
            retest = (
                since is not None
                and test.as_of.business_seq >= since
                and relevant_to_policy(test, self.module.package.locale)
            )
            runs, retests = counts.get(version, (0, 0))
            counts[version] = (runs + 1, retests + retest)
        return tuple(
            ConfigTestRuns(version, runs, retests)
            for version, (runs, retests) in sorted(counts.items())
        )

    def _initial_policy(self):
        return self.module.package.rules["initial_material_versions"]["policy"]

    @staticmethod
    def _policy_updates(window, at):
        """Recorded activations of the current policy version up to ``at``."""
        version = window.snapshot.source_versions["policy"]
        return [
            (e, p)
            for e, p in window.events
            if e.type == "initial_plan_applied"
            and before(p, at)
            and e.data.get("after_versions", {}).get("policy") == version
        ]

    def _snapshot(self, auth, at, subjects, config_ref, committed):
        window = self.window(auth, at)
        state = window.snapshot
        facts = []

        def source(ref):
            return self.source_reader(auth, ref, at).ref

        def add(name, value, *refs):
            # Revalidate every proof at the current credential and exact window.
            try:
                checked = tuple(source(ref) for ref in refs)
            except (ProtocolError, KeyError):
                return
            if checked:
                facts.append(VerifiedFact(name, value, checked))

        config = None
        config_source = None
        if config_ref is not None:
            config = AssistantConfig.model_validate(self.object(auth, config_ref, at).content)
            if ref_for("config", config) != config_ref:
                raise ProtocolError("config_version_mismatch")
            config_source = source(config_ref)
        tests = []
        test_refs = []
        for row in window.objects:
            if row.ref.kind != "test" or row.created_storage_revision > at.storage_revision:
                continue
            record = self.object(auth, row.ref, at)
            test = TestResultV2.model_validate(record.content)
            if not before(test.as_of, at) or (
                config_ref is not None and test.config_ref != config_ref
            ):
                continue
            tests.append(test)
            test_refs.append(source(row.ref))
        pairs = sorted(
            zip(tests, test_refs), key=lambda pair: (pair[0].as_of.storage_revision, pair[0].id)
        )
        tests = [t for t, _ in pairs]
        test_refs = [ref for _, ref in pairs]
        policy_version = state.source_versions["policy"]
        policy_ref = ObjectRef(
            session_id=auth.session_id, kind="material", object_id="policy", version=policy_version
        )
        changes = self._policy_updates(window, at)
        if window.events_complete and policy_version != self._initial_policy() and not changes:
            raise ProtocolError("policy_event_window_incomplete")
        proof_refs = tuple(ref for ref in (config_source, policy_ref) if ref is not None)
        if window.events_complete:
            add("change_log_complete", True, *proof_refs)
            add("policy_changed", bool(changes), *proof_refs)
        if config is None:
            return RuleSnapshot(at, tuple(facts), False, tuple(tests), tuple(test_refs))
        add("test_ledger_complete", window.tests_complete, config_source, *test_refs)
        add("current_obligation_verified", committed, config_source, *subjects)
        # Resources are checked against the initial public allocation and actual
        # approved decisions before producing resource numbers.
        allocated = dict(self.module.package.bundle.initial_resources)
        grants = []
        for row in sorted(window.objects, key=lambda row: row.created_storage_revision):
            if (
                row.ref.kind != "business_decision"
                or row.created_storage_revision > at.storage_revision
            ):
                continue
            decision = BusinessDecision.model_validate(self.object(auth, row.ref, at).content)
            if decision.status == "approved":
                allocated.update(decision.granted)
                grants.append(row.ref)
        if allocated == dict(state.world.resources):
            brief = ObjectRef(
                session_id=auth.session_id, kind="material", object_id="brief", version=1
            )
            technical = ObjectRef(
                session_id=auth.session_id, kind="material", object_id="technical", version=1
            )
            values = {
                "participants": config.participants,
                "capacity": allocated["capacity"],
                "required_dev_days": sum(
                    self.module.package.rules["work_costs"][w] for w in config.work_items
                ),
                "available_dev_days": allocated["dev_days"],
                "requested_launch_day": config.launch_day,
                "deadline_day": allocated["deadline_day"],
            }
            for name, value in values.items():
                add(name, value, config_source, brief, technical, *grants)
            add(
                "unapproved_resource_excess",
                values["participants"] > values["capacity"]
                or values["required_dev_days"] > values["available_dev_days"]
                or values["requested_launch_day"] > values["deadline_day"],
                config_source,
                brief,
                technical,
                *grants,
            )
        if changes:
            change, event_point = max(changes, key=lambda item: item[0].seq)
            event_ref = EvidenceRefV2(
                session_id=auth.session_id,
                kind="event",
                object_id=change.id,
                version=1,
                observed_at_seq=change.seq,
            )
            effective = effective_config(
                self.module.package, config, state.world.resources
            ).effective
            affects = (
                "policy_travel" in canonical_domains(self.module.package, effective.domains)
                or not effective.scope_filter
            )
            add("policy_change_seq", change.seq, event_ref, policy_ref)
            add("change_affects_subject", affects, config_source, policy_ref)
            add("affected_material_versions", {"policy": policy_version}, policy_ref)
            manual = (
                effective.update_strategy == "manual_policy"
                or "policy_travel"
                in canonical_domains(self.module.package, effective.manual_domains)
            )
            dynamic = []
            classified = not manual
            passing = []
            pass_known = not manual
            for test in tests:
                if test.as_of.business_seq < change.seq:
                    continue
                is_hotel = hotel_question(test.query, self.module.package.locale)
                if relevant_to_policy(test, self.module.package.locale):
                    dynamic.append(test.id)
                    # A model-generated answer stays pending verification: rules can check its
                    # recorded versions, never whether its text passes.
                    if not is_hotel or model_generated(test):
                        pass_known = False
                    else:
                        hotel = next(
                            f
                            for f in self.module.package.facts
                            if f.id == "hotel_limit" and f.version == policy_version
                        )
                        matched = [
                            c
                            for c in test.citations
                            if c.object_id == "policy"
                            and c.version == policy_version
                            and c.quote
                            and hotel.source.quote in c.quote
                        ]
                        if (
                            test.status == "answered"
                            and matched
                            and test.execution.used_versions.get("policy") == policy_version
                        ):
                            passing.append(test.id)
                elif not test_materials(test):
                    classified = False
            add("dynamic_test_ids", dynamic, config_source, *test_refs)
            add("dynamic_classification_complete", classified, config_source, *test_refs)
            if pass_known:
                add("passing_dynamic_test_ids", passing, policy_ref, config_source, *test_refs)
            actions = []
            for event, born in window.events:
                if event.seq <= change.seq or not before(born, at):
                    continue
                if (
                    event.type == "index_refreshed"
                    and event.data.get("after_versions", {}).get("policy") == policy_version
                ):
                    actions.append((event, born))
                elif event.type == "test_assistant" and any(
                    ref.object_id in dynamic for ref in event.refs
                ):
                    actions.append((event, born))
                elif event.type == "config_applied":
                    oid = event.data.get("config_id")
                    version = event.data.get("config_version")
                    relevant = [
                        row
                        for row in window.objects
                        if row.ref.kind == "config" and row.ref.object_id == oid
                    ]
                    now = next((row for row in relevant if row.ref.config_version == version), None)
                    prev = (
                        next(
                            (row for row in relevant if row.ref.config_version == version - 1), None
                        )
                        if type(version) is int
                        else None
                    )
                    keys = (
                        "domains",
                        "update_strategy",
                        "work_items",
                        "scope_filter",
                        "freshness_guard",
                        "manual_domains",
                        "fallback",
                    )
                    if (
                        now
                        and prev
                        and any(now.content.get(k) != prev.content.get(k) for k in keys)
                    ):
                        actions.append((event, born))
            action_refs = [
                EvidenceRefV2(
                    session_id=auth.session_id,
                    kind="event",
                    object_id=e.id,
                    version=1,
                    observed_at_seq=e.seq,
                )
                for e, _ in actions
            ]
            if window.events_complete:
                add("adjustment_log_complete", True, event_ref, config_source, *action_refs)
                add("adjustment_action_count", len(actions), event_ref, config_source, *action_refs)
            if pass_known and classified and tests:
                latest = max(
                    (t for t in tests if t.id in dynamic),
                    key=lambda t: t.as_of.storage_revision,
                    default=None,
                )
                if latest is not None:
                    add(
                        "adjustment_appropriate_verified",
                        latest.id in passing
                        and not (
                            set(
                                effective_config(
                                    self.module.package, config, state.world.resources
                                ).differences
                            )
                            & {
                                "work_items",
                                "update_strategy",
                                "scope_filter",
                                "fallback",
                                "manual_domains",
                                "freshness_guard",
                            }
                        ),
                        config_source,
                        policy_ref,
                        *test_refs,
                    )
        return RuleSnapshot(
            at,
            tuple(facts),
            window.tests_complete,
            tuple(tests),
            tuple(test_refs),
            config.config_version,
            tuple(t.id for t in tests if t.status == "failed"),
        )
