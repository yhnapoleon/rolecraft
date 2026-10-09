"""Authorized historical reads adapted to the existing dataset snapshot port.

This module never mounts learner routes, runs a model or writes business state.
The research snapshot is kept in memory; only current-permission source reads
and explicit model-input fields can leave the process.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from career_lab.api.evaluation_runtime import ScenarioEvidencePort
from career_lab.api.modules import Gateway
from career_lab.api.scenario_history import HistoricalScenarioReader
from career_lab.contracts import v2 as C
from career_lab.datasets.v3.common import sha
from career_lab.datasets.v3.export import (
    ExportResult,
    ExportUnit,
    FrozenSnapshot,
    SourceObject,
    export_from_port,
    object_key,
)
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, base_ref
from career_lab.evidence.v2.ports import CriterionPolicy, SourceRecord
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.research.authorization import (
    ResearchAuthorization,
    SignedAuthorization,
    public_identity,
    validate,
    within,
)
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_snapshot import SnapshotPortAdapter

SOURCE_KINDS = frozenset(
    {
        "product",
        "test",
        "material",
        "config",
        "business_request",
        "business_decision",
        "submission",
        "review",
        "event",
        "role_turn",
        "role_reply",
    }
)


@dataclass(frozen=True)
class LiveCapture:
    result: ExportResult
    sources: dict[str, bytes]
    authorization: dict[str, object]
    snapshot_hash: str
    empty_reasons: dict[str, str]
    source_index: dict[str, dict[str, object]]
    execution_failures: tuple[dict[str, object], ...]


class AuthorizedSnapshotPort:
    def __init__(
        self,
        gateway: Gateway,
        module: ScenarioModule | HistoricalScenarioReader,
        auth: C.AuthContext,
        authorization: SignedAuthorization,
        key: bytes,
        identity: C.SourceIdentity,
    ) -> None:
        self.gateway = gateway
        self.module = module
        self.auth = auth
        self.authorization = authorization
        self.key = key
        self.identity = identity
        self.units: list[ExportUnit] = []
        self.execution_failures: list[dict[str, object]] = []
        self.sources: dict[str, SourceObject] = {}
        self.files: dict[str, bytes] = {}
        self.source_index: dict[str, dict[str, object]] = {}
        self.snapshot_hash = ""
        self.empty_reasons: dict[str, str] = {}
        self.grant: ResearchAuthorization | None = None

    def read_snapshot(self, session_id: str, point: C.VersionPoint) -> FrozenSnapshot:
        grant = validate(
            self.authorization,
            key=self.key,
            session_id=session_id,
            purpose="dataset_export",
            point=point,
        )
        self.gateway.store.authorize(self.auth, "read")
        if (
            self.auth.session_id != session_id
            or self.auth.credential_id != grant.issuer_credential_id
        ):
            raise C.ProtocolError("research_authorization_reader_mismatch", status=403)
        self.grant = grant
        raw = SnapshotPortAdapter(self.gateway.store, self.identity.source_digest).read_snapshot(
            session_id, point
        )
        self.module.check_bindings(raw.bindings)
        if self.module.package.bundle.split == "test":
            raise C.ProtocolError("sealed_test_export_forbidden", status=403)
        self.snapshot_hash = raw.snapshot_hash
        kinds = {row.ref.kind for row in raw.objects}
        self.empty_reasons = {
            "relation": "no_eligible_test_records",
            "criterion": "no_eligible_submission_records",
            "trajectory": "branch_projection_unavailable"
            if "branch" in kinds
            else "no_branch_records",
            "acquisition": "acquisition_projection_unavailable"
            if "acquisition" in kinds
            else "no_acquisition_records",
        }
        bundle = C.EvaluationBundle.model_validate_json(
            C.read_file(self.module.package.root, raw.bindings.evaluation)
        )
        protocol = json.loads(C.read_file(self.module.package.root, bundle.protocol))
        policies = tuple(CriterionPolicy(**value) for value in protocol["policies"])
        source = ScenarioEvidencePort(self.gateway.store, self.module)
        reader = StoreEvidenceReader(
            self.gateway.store,
            self.auth,
            policies=policies,
            source_reader=source.source,
            rule_provider=source.rules,
            submission_rule_provider=source.submission_rules,
        )
        assembler = EvidenceAssemblerV2(reader, work_language=self.module.work_language)
        for row in raw.objects:
            if row.ref.kind not in {"test", "submission"}:
                continue
            try:
                self.gateway.store.read(self.auth, row.ref, storage_revision=point.storage_revision)
                if row.ref.kind == "test":
                    self._test(reader, C.TestResultV2.model_validate(row.content), row.ref)
                else:
                    self._submission(reader, assembler, C.SubmissionV2.model_validate(row.content))
            except C.ProtocolError as error:
                if error.status not in {403, 404}:
                    raise
                # An inaccessible object contributes no body or identity to the export.
                continue
        return FrozenSnapshot(
            session_id,
            self.auth.actor_id,
            point,
            tuple(self.sources[key] for key in sorted(self.sources)),
            self.identity.source_digest,
            "env_run",
        )

    def _source(
        self, reader: StoreEvidenceReader, ref: C.ObjectRef, at: C.VersionPoint
    ) -> tuple[SourceRecord, C.FileRef]:
        if ref.kind not in SOURCE_KINDS:
            raise C.ProtocolError("export_source_kind_forbidden", status=403)
        source = reader.read(self.auth, ref, at)
        if source.created_at is None:
            raise C.ProtocolError("source_time_unknown")
        assert self.grant is not None
        if not within(self.grant.from_point, source.created_at) or not within(
            source.created_at, self.grant.through_point
        ):
            raise C.ProtocolError("research_authorization_window", status=403)
        bare = base_ref(source.ref)
        key = object_key(bare)
        self.sources[key] = SourceObject(
            bare,
            source.text,
            source.created_at,
            (self.auth.actor_id,),
            validity_known=ref.kind != "material",
            valid_from_seq=source.ref.valid_from_seq,
            valid_until_seq=source.ref.valid_until_seq,
        )
        path = "audit/sources/" + key + ".txt"
        data = source.text.encode("utf-8")
        self.files[path] = data
        self.source_index[path] = {
            "ref": bare.model_dump(mode="json"),
            "available_at": source.created_at.model_dump(mode="json"),
            "sha256": sha(data),
            "language": self.module.work_language,
            "span_start": 0,
            "span_end": len(source.text),
            "executor": source.executor.model_dump(mode="json") if source.executor else None,
        }
        return source, C.FileRef(path=path, sha256=sha(data), media_type="text/plain")

    def _unit(
        self,
        reader: StoreEvidenceReader,
        package: C.EvidencePackageV2,
        executor: C.Executor,
        captured_at: datetime,
        extra: Iterable[C.FileRef] = (),
    ) -> None:
        files = {ref.path: ref for ref in extra}
        for ref in (
            *package.subjects,
            *package.dropped_refs,
            *(c.ref for c in package.candidate_evidence),
        ):
            _, file = self._source(reader, ref, package.as_of)
            files[file.path] = file
        # Rule derivations, evaluator labels and private context never become model features.
        body = package.model_dump(mode="json", exclude={"input_hash"})
        body.update(rule_context={}, rule_bound=None)
        package = C.EvidencePackageV2(**body, input_hash=C.digest(body))
        family = package.task_type
        model = (
            C.RelationInput(evidence=package)
            if family == "relation"
            else C.CriterionInput(evidence=package)
        )
        public_facts = tuple(
            sorted(f.id for f in self.module.package.facts if f.disclosure.mode == "public")
        )
        structure = self.module.package.bundle.structure_id
        self.units.append(
            ExportUnit(
                family,
                model,
                C.Lineage(
                    structure_id=structure,
                    component_id=structure,
                    fact_root_ids=public_facts,
                    session_id=self.auth.session_id,
                    run_id=self.auth.session_id,
                ),
                C.Provenance(
                    command="python -m career_lab.datasets.v3 export --live",
                    source=self.identity,
                    executor=executor,
                    actual_sources=tuple(files[path] for path in sorted(files)),
                    captured_at=captured_at,
                ),
                split=self.module.package.bundle.split,
                language=self.module.work_language,
                evaluation_time_known=True,
            )
        )

    def _test(self, reader: StoreEvidenceReader, test: C.TestResultV2, ref: C.ObjectRef) -> None:
        assert self.grant is not None
        if test.status == "failed" or not test.answer:
            source = reader.read(self.auth, ref, self.grant.through_point)
            if source.created_at is None or not within(self.grant.from_point, source.created_at):
                raise C.ProtocolError("research_authorization_window", status=403)
            known_errors = {
                "prohibited_topic",
                "no_retrieval_hit",
                "outside_scope",
                "manual_verification_required",
                "stale_source_guard",
            }
            self.execution_failures.append(
                {
                    "ref": ref.model_dump(mode="json"),
                    "status": test.status,
                    "reason": "test_failed" if test.status == "failed" else "test_empty_output",
                    "error_code": test.error_code if test.error_code in known_errors else None,
                    "executor": test.execution.executor.model_dump(mode="json"),
                }
            )
            return
        _, file = self._source(reader, ref, self.grant.through_point)
        candidates = []
        for citation in test.citations:
            source, _ = self._source(reader, citation, test.as_of)
            text = citation.quote or source.text
            candidates.append(
                C.CandidateEvidenceV2(
                    id="source-" + C.digest(citation)[:24], text=text, ref=citation
                )
            )
        body = dict(
            schema_version=2,
            item_id=test.id,
            task_type="relation",
            criterion=None,
            claim=test.answer,
            subjects=(),
            purpose="result",
            as_of=test.as_of.model_dump(mode="json"),
            applicability="undetermined",
            candidate_evidence=[candidate.model_dump(mode="json") for candidate in candidates],
            rule_context={},
            rule_bound=None,
            completeness="complete" if candidates else "missing",
            dropped_refs=(),
            missing_refs=(),
        )
        package = C.EvidencePackageV2(**body, input_hash=C.digest(body))
        self._unit(reader, package, test.execution.executor, test.execution.executed_at, (file,))

    def _submission(
        self,
        reader: StoreEvidenceReader,
        assembler: EvidenceAssemblerV2,
        submission: C.SubmissionV2,
    ) -> None:
        if not submission.products:
            return
        snapshot = reader.submission_snapshot(self.auth, submission)
        refs = list(submission.evidence_refs)
        for product in submission.products:
            refs.extend(reader.read(self.auth, product, submission.as_of).declared_refs)
        assert self.grant is not None
        for policy in reader.policies():
            package = assembler.assemble(
                auth=self.auth,
                subject_id=submission.id,
                subjects=submission.products,
                evidence_refs=tuple(refs),
                purpose="commitment",
                decision=submission.decision,
                as_of=submission.as_of,
                policy=policy,
                snapshot=snapshot,
                anchor_mode="submission",
                requested_at=submission.as_of,
            )
            self._unit(reader, package, submission.executor, self.grant.issued_at)


def capture_session(
    gateway: Gateway,
    module: ScenarioModule | HistoricalScenarioReader,
    auth: C.AuthContext,
    authorization: SignedAuthorization,
    key: bytes,
    identity: C.SourceIdentity,
    point: C.VersionPoint,
) -> LiveCapture:
    port = AuthorizedSnapshotPort(gateway, module, auth, authorization, key, identity)
    result = export_from_port(port, auth.session_id, point, lambda _: port.units)
    assert port.grant is not None
    return LiveCapture(
        result,
        port.files,
        public_identity(port.grant),
        port.snapshot_hash,
        port.empty_reasons,
        port.source_index,
        tuple(port.execution_failures),
    )
