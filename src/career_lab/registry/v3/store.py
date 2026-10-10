"""Atomic file-only registry for runtime, evaluation and candidate manifests.

This registry preserves bytes. Model availability and execution remain the
responsibility of the installed model registry and runner adapters.
"""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from career_lab.contracts.v2.core import FileRef, ProtocolError, canonical, digest, read_file
from career_lab.contracts.v2.research import (
    CandidateBundle,
    EvaluationBundle,
    RuntimeBundle,
    SkillBundle,
    SkillSpec,
)

from .portability import validate_portability

Bundle = RuntimeBundle | EvaluationBundle | CandidateBundle
Dependency = Bundle | SkillBundle | SkillSpec
Kind = Literal["runtime", "evaluation", "candidate"]
MODELS: dict[Kind, type[Bundle]] = {
    "runtime": RuntimeBundle,
    "evaluation": EvaluationBundle,
    "candidate": CandidateBundle,
}


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Kind
    logical_id: str
    revision: str
    manifest: FileRef
    files: dict[str, FileRef]


def references(value: object) -> Iterator[FileRef]:
    """Walk typed manifest references without interpreting arbitrary prompt text."""
    if isinstance(value, FileRef):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from references(getattr(value, name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from references(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from references(child)


@dataclass(frozen=True)
class RunBinding:
    runtime_id: str
    evaluation_id: str


class BundleRegistry:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "registry.sqlite"
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS blobs(hash TEXT PRIMARY KEY, raw BLOB)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS bundles("
                "record_id TEXT PRIMARY KEY, kind TEXT, logical_id TEXT, revision TEXT, raw BLOB, "
                "UNIQUE(kind, logical_id, revision))"
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.database, timeout=10)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise ProtocolError("registry_storage_unavailable", status=503) from exc

    def register(self, kind: Kind, source: Path, manifest: FileRef) -> str:
        """Copy a complete manifest transactionally; never replace an identity."""
        if kind not in MODELS:
            raise ProtocolError("registry_schema_unsupported")
        raw = read_file(source, manifest)
        model = MODELS[kind].model_validate_json(raw)
        members: dict[str, FileRef] = {}
        content: dict[str, bytes] = {}
        self._collect(source, manifest, model, members, content)
        record = Registration(
            kind=kind,
            logical_id=model.id,
            revision=model.revision
            if isinstance(model, (RuntimeBundle, EvaluationBundle))
            else "1",
            manifest=manifest,
            files=members,
        )
        record_raw = canonical(record.model_dump(mode="json"))
        identity = digest(record.model_dump(mode="json"))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._save(connection, record, identity, record_raw, content)
        return identity

    @classmethod
    def _collect(
        cls,
        source: Path,
        manifest: FileRef,
        model: Dependency,
        members: dict[str, FileRef],
        content: dict[str, bytes],
        depth: int = 0,
    ) -> None:
        if isinstance(model, EvaluationBundle) and model.mode != "advisory":
            raise ProtocolError("scoring_adoption_not_authorized", status=403)
        if depth > 64:
            raise ProtocolError("registry_dependency_depth_exceeded")
        for ref in (manifest, *references(model)):
            if ref.path in members and members[ref.path] != ref:
                raise ProtocolError("registry_reference_conflict")
            members[ref.path] = ref
            raw = read_file(source, ref)
            validate_portability(raw, ref)
            content[ref.sha256] = raw
        children: tuple[tuple[FileRef, Dependency], ...] = ()
        if isinstance(model, RuntimeBundle) and model.skills is not None:
            children = (
                (model.skills, SkillBundle.model_validate_json(content[model.skills.sha256])),
            )
        elif isinstance(model, SkillBundle):
            children = tuple(
                (ref, SkillSpec.model_validate_json(content[ref.sha256])) for ref in model.members
            )
        elif isinstance(model, CandidateBundle):
            children = (
                (model.runtime, RuntimeBundle.model_validate_json(content[model.runtime.sha256])),
                (
                    model.evaluation,
                    EvaluationBundle.model_validate_json(content[model.evaluation.sha256]),
                ),
                (
                    model.parent,
                    TypeAdapter(RuntimeBundle | CandidateBundle).validate_json(
                        content[model.parent.sha256]
                    ),
                ),
            )
        for ref, child in children:
            cls._collect(source, ref, child, members, content, depth + 1)

    @staticmethod
    def _save(
        connection: sqlite3.Connection,
        record: Registration,
        identity: str,
        record_raw: str,
        content: dict[str, bytes],
    ) -> None:
        prior = connection.execute(
            "SELECT record_id FROM bundles WHERE kind=? AND logical_id=? AND revision=?",
            (record.kind, record.logical_id, record.revision),
        ).fetchone()
        if prior and prior[0] != identity:
            raise ProtocolError("registry_version_immutable", status=409)
        for sha, raw in content.items():
            existing = connection.execute("SELECT raw FROM blobs WHERE hash=?", (sha,)).fetchone()
            if existing and existing[0] != raw:
                raise ProtocolError("registry_blob_drift", status=409)
            connection.execute("INSERT OR IGNORE INTO blobs VALUES (?, ?)", (sha, raw))
        connection.execute(
            "INSERT OR IGNORE INTO bundles VALUES (?, ?, ?, ?, ?)",
            (identity, record.kind, record.logical_id, record.revision, record_raw),
        )

    def _load(self, identity: str) -> tuple[Registration, dict[str, bytes]]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT raw FROM bundles WHERE record_id=?", (identity,)
            ).fetchone()
            if row is None:
                raise ProtocolError("registry_unavailable", status=503)
            record = Registration.model_validate_json(row[0])
            if digest(record.model_dump(mode="json")) != identity:
                raise ProtocolError("registry_record_drift", status=409)
            members: dict[str, bytes] = {}
            for path, ref in record.files.items():
                blob = connection.execute(
                    "SELECT raw FROM blobs WHERE hash=?", (ref.sha256,)
                ).fetchone()
                if blob is None:
                    raise ProtocolError("registry_artifact_unavailable", status=503)
                if path != ref.path or hashlib.sha256(blob[0]).hexdigest() != ref.sha256:
                    raise ProtocolError("registry_blob_drift", status=409)
                members[path] = blob[0]
            return record, members

    def load(self, identity: str) -> Bundle:
        record, members = self._load(identity)
        return MODELS[record.kind].model_validate_json(members[record.manifest.path])

    def bind(self, runtime_id: str, evaluation_id: str) -> RunBinding:
        """Pin file identities only; this does not claim model or runner readiness."""
        if not isinstance(self.load(runtime_id), RuntimeBundle):
            raise ProtocolError("registry_runtime_required")
        if not isinstance(self.load(evaluation_id), EvaluationBundle):
            raise ProtocolError("registry_evaluation_required")
        return RunBinding(runtime_id, evaluation_id)

    def compare(self, baseline: RunBinding, candidate: RunBinding) -> None:
        """Validate the fixed evaluation condition before comparing run results."""
        self.bind(baseline.runtime_id, baseline.evaluation_id)
        self.bind(candidate.runtime_id, candidate.evaluation_id)
        if baseline.evaluation_id != candidate.evaluation_id:
            raise ProtocolError("registry_evaluation_changed", status=409)

    def resolve_manifest(self, identity: str, ref: FileRef) -> bytes:
        """Bind the root manifest, whose record pins logical ID, revision and exact bytes."""
        record, members = self._load(identity)
        if record.manifest != ref:
            raise ProtocolError("registry_manifest_mismatch", status=409)
        return members[ref.path]

    def resolve_file(self, identity: str, ref: FileRef) -> bytes:
        record, members = self._load(identity)
        if record.files.get(ref.path) != ref:
            raise ProtocolError("registry_file_not_bound", status=403)
        return members[ref.path]
