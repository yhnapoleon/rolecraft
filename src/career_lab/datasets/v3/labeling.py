"""Durable annotation attempts; API and hash-bound offline receipts use the same payload.

The local outbox provides at-most-one dispatch while running. A crash after
sending leaves an uncertain attempt; it is never silently called again.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import time

from career_lab.contracts.v2.core import Executor, FileRef, ProtocolError, digest, read_file
from career_lab.contracts.v2.data import DatasetRecordV2, AnnotationDecision
from .common import json_bytes, sha, read_json, write_new, immutable_directory, check_payload
from .quality import policy_approval, verify_policy_approval
from .temporal import require_time_context
from .attestation import (same_semantics, annotation_payload, make_request,
                          parse_receipt, verify_attempt, rebuild_annotation, RECEIPT_FIELDS)


@dataclass(frozen=True)
class LabelResult:
    raw_output: str
    model_revision: str | None
    provider: str
    usage: dict
    invocation_id: str | None = None
    context_id: str | None = None
    independence_method: str | None = None


class ProviderHTTPFailure(RuntimeError):
    def __init__(self,details,usage=None,model_revision=None):
        super().__init__(f"provider_http_{details['http_status']}")
        self.details,self.usage,self.model_revision=details,usage or {},model_revision


class OpenAICompatibleExecutor:
    """Opt-in live adapter. No key lookup, default endpoint or automatic requests."""
    def __init__(self, client, endpoint, model, api_key):
        self.client, self.endpoint, self.model, self.api_key = client, endpoint, model, api_key

    def __call__(self, request):
        response = self.client.post(self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": request["request_id"]},
            json={"model": self.model, "messages": [
                {"role": "system", "content": request["instruction"]},
                {"role": "user", "content": json_bytes(request["model_input"]).decode()}],
                "response_format": {"type": "json_object"}})
        if response.is_error:
            try:body=response.json()
            except ValueError:body=None
            def redact(value):
                if isinstance(value,dict):return {k:("[redacted]" if k.casefold() in {"authorization","api_key","apikey","password","secret","token","access_token","refresh_token"} else redact(v)) for k,v in value.items()}
                if isinstance(value,list):return [redact(x) for x in value]
                if isinstance(value,str) and self.api_key:return value.replace(self.api_key,"[redacted]")
                return value
            body=redact(body)
            raw=json.dumps(body,ensure_ascii=False) if body is not None else redact(response.text)
            details={"http_status":response.status_code,"response_body":raw[:16384],"response_body_truncated":len(raw)>16384,
                     "request_id":redact(response.headers.get("x-request-id"))}
            raise ProviderHTTPFailure(details,body.get("usage") if isinstance(body,dict) else None,
                                      body.get("model") if isinstance(body,dict) else None)
        body = response.json()
        return LabelResult(body["choices"][0]["message"]["content"], body.get("model"),
                           "openai-compatible", body.get("usage") or {},
                           invocation_id=body.get("id") or "client-http:"+request["request_id"],
                           context_id=request["requested_context_id"],independence_method="fresh_context")


class AnnotationBatch:
    def __init__(self, path):
        self.path = Path(path)
        self.manifest = read_json(self.path / "batch.json")
        if self.manifest["id"] != digest({k: v for k, v in self.manifest.items() if k != "id"}):
            raise ProtocolError("batch_manifest_drift")
        if self.manifest.get("protocol") != "w07-label-outbox-v4":
            raise ProtocolError("batch_policy_revalidation_required")
        raw = read_file(self.path, FileRef.model_validate(self.manifest["records"]))
        rows = [DatasetRecordV2.model_validate(x) for x in json.loads(raw)]
        self.records = {r.record_id: r for r in rows}
        if len(self.records) != self.manifest["count"] or len(rows) != len(self.records):
            raise ProtocolError("batch_identity_mismatch")
        self._load_policy()
        self.db_path = self.path / "attempts.sqlite3"

    def _load_policy(self):
        if read_json(self.path / "batch.json") != self.manifest:
            raise ProtocolError("batch_manifest_drift")
        policy = json.loads(read_file(self.path, FileRef.model_validate(self.manifest["source_policy"])))
        approvals = policy["approvals"]
        if approvals.keys() != self.records.keys():
            raise ProtocolError("batch_policy_identity_mismatch")
        for rid, record in self.records.items():
            verify_policy_approval(record, approvals[rid])
        self.approvals = approvals
        return policy

    @classmethod
    def create(cls, path, records, *, annotation_version, executor: Executor, prompts=None,
               source_root=None, policies=None):
        records = list(records)
        if not records or len({r.record_id for r in records}) != len(records):
            raise ProtocolError("batch_requires_unique_records")
        if executor.kind not in {"external_agent", "reference_agent"}:
            raise ProtocolError("model_executor_required")
        prompts = prompts or ("w07-review-a-v1", "w07-review-b-v1", "w07-arbitrate-v1")
        if len(prompts) != 3 or len(set(prompts)) != 3:
            raise ProtocolError("independent_prompts_required")
        if source_root is None or policies is None:
            raise ProtocolError("source_policy_required", status=403)
        approved, approvals, quarantine = [], {}, []
        for record in records:
            record = DatasetRecordV2.model_validate(record.model_dump(mode="json"))
            if record.split == "test":
                raise ProtocolError("sealed_test_labeling_forbidden", status=403)
            check_payload(record.model_input.model_dump(mode="json"))
            try:
                approval = policy_approval(record, policies)
                require_time_context(record.model_input)
                for ref in record.provenance.actual_sources:
                    read_file(Path(source_root), ref)
            except ProtocolError as exc:
                quarantine.append({"record_id": record.record_id, "reason": exc.code})
                continue
            approved.append(record)
            approvals[record.record_id] = approval
        with immutable_directory(path) as root:
            rows = [r.model_dump(mode="json") for r in approved]
            policy = {"approvals": approvals, "quarantined": quarantine}
            write_new(root / "records.json", rows)
            write_new(root / "source-policy.json", policy)
            manifest = {"protocol": "w07-label-outbox-v4", "annotation_version": annotation_version,
                "executor": executor.model_dump(mode="json"), "prompts": list(prompts), "count": len(rows),
                "quarantined": quarantine,"output_schema":AnnotationDecision.model_json_schema(),
                "records": FileRef(path="records.json", sha256=sha(json_bytes(rows))).model_dump(mode="json"),
                "source_policy": FileRef(path="source-policy.json", sha256=sha(json_bytes(policy))).model_dump(mode="json")}
            manifest["id"] = digest(manifest)
            write_new(root / "batch.json", manifest)
            with sqlite3.connect(root / "attempts.sqlite3") as db:
                db.execute("CREATE TABLE attempts (record_id TEXT, phase INTEGER, attempt INTEGER, status TEXT, request_hash TEXT, request_json TEXT, result_path TEXT, result_sha256 TEXT, PRIMARY KEY(record_id, phase, attempt))")
        return cls(path)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _payload(self, record, phase):
        return annotation_payload(record, phase)

    def claim(self, record_id, phase, *, retry_failed=False, retry_unknown=False):
        if phase not in {1, 2, 3}:
            raise ProtocolError("invalid_annotation_phase")
        self._load_policy()  # Recheck frozen permission bytes before any sendable payload.
        if record_id not in self.records:
            raise ProtocolError("record_not_approved_for_labeling", status=403)
        record = self.records[record_id]
        if phase == 3:
            state = self.annotation(record_id)
            good = [p for p in state.passes if p.status == "success"]
            if len(good) < 2 or same_semantics(good[0].decision, good[1].decision):
                raise ProtocolError("adjudication_not_required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM attempts WHERE record_id=? AND phase=? ORDER BY attempt DESC LIMIT 1", (record_id, phase)).fetchone()
            if previous:
                if previous["status"] == "success":
                    self._read_result(previous)
                    return None
                if previous["status"] == "dispatched" and not retry_unknown:
                    raise ProtocolError("dispatch_outcome_unknown", status=409)
                if previous["status"] in {"failed", "empty"} and not retry_failed:
                    return None
                if previous["status"] == "dispatched":
                    db.execute("UPDATE attempts SET status='unknown' WHERE record_id=? AND phase=? AND attempt=?", (record_id, phase, previous["attempt"]))
            attempt = 1 if not previous else previous["attempt"] + 1
            request = make_request(record, self.manifest["annotation_version"], phase, attempt,
                self.manifest["prompts"][phase-1], self.manifest["executor"], self.approvals[record_id], self.manifest["id"],self.manifest["output_schema"])
            rh = digest(request)
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,NULL,NULL)", (record_id, phase, attempt, "dispatched", rh, json_bytes(request).decode()))
        return request | {"request_hash": rh}

    def receive(self, receipt):
        rid, phase, attempt = receipt["record_id"], receipt["phase"], receipt["attempt"]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM attempts WHERE record_id=? AND phase=? AND attempt=?", (rid, phase, attempt)).fetchone()
            if row is None:
                raise ProtocolError("annotation_unissued_receipt")
            request = json.loads(row["request_json"])
            if digest(request) != row["request_hash"]:
                raise ProtocolError("annotation_request_drift")
            parsed, error, raw_type = parse_receipt(request, receipt)
            if row["result_path"]:
                saved = self._read_result(row)
                if saved["receipt_hash"] != digest(receipt):
                    raise ProtocolError("annotation_receipt_conflict", status=409)
                return saved
            if row["status"] != "dispatched":
                raise ProtocolError("annotation_stale_attempt", status=409)
            stored = {"format": "w07-label-attempt-v4", "pass": parsed.model_dump(mode="json"),
                "request": request, "request_hash": digest(request), "source_policy": self.approvals[rid],
                "receipt": receipt, "receipt_hash": digest(receipt), "provider": receipt.get("provider"),
                "usage": receipt.get("usage") or {}, "elapsed_seconds": receipt.get("elapsed_seconds"),
                "error_code": error, "raw_return_type": raw_type, "received_at": datetime.now(timezone.utc).isoformat()}
            verify_attempt(self.records[rid], self.manifest["annotation_version"], json_bytes(stored))
            name = f"labels/passes/{request['request_id']}.json"
            target = self.path / name
            if target.exists():
                prior = read_json(target)
                verify_attempt(self.records[rid], self.manifest["annotation_version"], target.read_bytes())
                if prior["receipt_hash"] != stored["receipt_hash"]:
                    raise ProtocolError("annotation_receipt_conflict", status=409)
                stored = prior
            else:
                write_new(target, stored)
            db.execute("UPDATE attempts SET status=?, result_path=?, result_sha256=? WHERE record_id=? AND phase=? AND attempt=?", (parsed.status, name, sha(json_bytes(stored)), rid, phase, attempt))
        return stored

    def _read_result(self, row):
        raw = read_file(self.path, FileRef(path=row["result_path"], sha256=row["result_sha256"]))
        stored, parsed = verify_attempt(self.records[row["record_id"]], self.manifest["annotation_version"], raw)
        return stored

    def run(self, executor, *, retry_failed=False):
        self._load_policy()
        blocked = []
        for rid in self.records:
            for phase in (1, 2, 3):
                if phase == 3:
                    state = self.annotation(rid)
                    successes = [p for p in state.passes if p.status == "success"]
                    if len(successes) < 2 or same_semantics(successes[0].decision, successes[1].decision):
                        if len(successes)>=2 and state.status=="pending":
                            blocked.append({"record_id":rid,"phase":3,"code":"semantic_consensus_contract_upgrade_required"})
                        break
                try:
                    request = self.claim(rid, phase, retry_failed=retry_failed)
                except ProtocolError as exc:
                    blocked.append({"record_id": rid, "phase": phase, "code": exc.code})
                    break
                if request is None:
                    continue
                started = time.monotonic()
                receipt = {k: request[k] for k in (*RECEIPT_FIELDS, "request_hash")}
                try:
                    response = executor(request)
                    receipt.update(raw_output=response.raw_output, model_revision=response.model_revision,
                                   provider=response.provider, usage=response.usage,invocation_id=response.invocation_id,
                                   context_id=response.context_id,independence_method=response.independence_method)
                except ProviderHTTPFailure as exc:
                    receipt.update(raw_output=exc.details["response_body"],error_code=f"provider_http_{exc.details['http_status']}",
                        provider="openai-compatible",model_revision=exc.model_revision,usage=exc.usage,error_details=exc.details)
                except Exception as exc:
                    receipt.update(raw_output=None, error_code="provider_" + type(exc).__name__,error_details={"exception_type":type(exc).__name__})
                receipt["elapsed_seconds"] = time.monotonic() - started
                self.receive(receipt)
        return {"annotations": [self.annotation(rid) for rid in self.records], "blocked": blocked,
                "quarantined": self.manifest["quarantined"], "usage": self.usage()}

    def annotation(self, record_id):
        with self._db() as db:
            rows = db.execute("SELECT * FROM attempts WHERE record_id=? ORDER BY phase,attempt", (record_id,)).fetchall()
        verified = []
        for row in rows:
            if row["result_path"]:
                raw = read_file(self.path, FileRef(path=row["result_path"], sha256=row["result_sha256"]))
                stored, parsed = verify_attempt(self.records[record_id], self.manifest["annotation_version"], raw)
                verified.append((stored, parsed, raw))
        return rebuild_annotation(self.records[record_id], self.manifest["annotation_version"], verified)

    def usage(self):
        with self._db() as db:
            rows = db.execute("SELECT * FROM attempts").fetchall()
        results = [self._read_result(r) for r in rows if r["result_path"]]
        costs = [(r.get("usage") or {}).get("cost") for r in results]
        return {"attempts": len(rows), "successful": sum(r["status"] == "success" for r in rows),
            "failed": sum(r["status"] in {"failed", "empty"} for r in rows),
            "uncertain": sum(r["status"] in {"unknown", "dispatched"} for r in rows),
            "known_cost": sum(c for c in costs if type(c) in (int, float)),
            "cost_complete": len(costs) == len(rows) and all(type(c) in (int, float) for c in costs)}

    def artifacts(self):
        return {p.relative_to(self.path).as_posix(): p.read_bytes() for p in sorted((self.path / "labels").rglob("*.json"))}
