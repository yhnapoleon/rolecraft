"""Real read-only reader of an immutable, caller-authorized evidence snapshot.

This private adapter format is not a replacement public contract. W01 must
produce the authorized snapshot and validate current credentials before calling
it. No world state, event, queue, or responsibility is invented by this reader.
"""
from pathlib import Path
import hashlib,json
from career_lab.contracts.v2.core import EvidenceRefV2,ObjectRef,VersionPoint,Executor,ProtocolError,FileRef
from .ports import SourceRecord,ActivityRecord,ActivityLedger,RuleSnapshot,VerifiedFact,ResponsibilityFact,CriterionPolicy
from .history import before


class SnapshotEvidenceReader:
    def __init__(self,path,expected_sha256):
        raw=Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ProtocolError('evidence_snapshot_hash_mismatch')
        value=json.loads(raw)
        if value.get('schema_version')!=1:raise ProtocolError('evidence_snapshot_version')
        self.session_id=value['session_id'];self.actor_id=value['actor_id']
        self.captured_at=VersionPoint.model_validate(value['captured_at']);self.records={};self._visible={}
        self.evaluation=FileRef.model_validate(value['evaluation'])
        self._policies=tuple(CriterionPolicy(**p) for p in value['policies'])
        if not self._policies or len(self._policies)>24 or len({p.id for p in self._policies})!=len(self._policies):raise ProtocolError('invalid_evaluation_policy')
        self._rule_snapshots=value.get('rule_snapshots',[])
        for data in value['records']:
            ref=EvidenceRefV2.model_validate(data['ref']);point=VersionPoint.model_validate(data['created_at']) if data.get('created_at') else None
            if ref.session_id!=self.session_id or (point is not None and not before(point,self.captured_at)):raise ProtocolError('invalid_snapshot_record')
            key=self.key(ref)
            if key in self.records:raise ProtocolError('duplicate_snapshot_version')
            self._visible[key]=tuple(data.get('visible_to',()))
            self.records[key]=SourceRecord(ref=ref,text=data['text'],created_at=point,
                declared_refs=tuple(EvidenceRefV2.model_validate(r) for r in data.get('declared_refs',[])),
                author=Executor.model_validate(data['author']) if data.get('author') else None,
                executor=Executor.model_validate(data['executor']) if data.get('executor') else None,
                adopter=Executor.model_validate(data['adopter']) if data.get('adopter') else None,
                activity_kind=data.get('activity_kind'),activity_target=ObjectRef.model_validate(data['activity_target']) if data.get('activity_target') else None,actor_id=data.get('actor_id'))
        log=value.get('activity_ledger',{})
        self.ledger=ActivityLedger(records=tuple(ActivityRecord(
            ref=EvidenceRefV2.model_validate(a['ref']),kind=a['kind'],occurred_at=VersionPoint.model_validate(a['occurred_at']),
            executor=Executor.model_validate(a['executor']),actor_id=a['actor_id'],
            target=ObjectRef.model_validate(a['target']) if a.get('target') else None,counterparty=a.get('counterparty')) for a in log.get('records',[])),
            completeness=tuple(log.get('completeness',{}).items()),
            covered_from=VersionPoint.model_validate(log['covered_from']) if log.get('covered_from') else None,
            covered_through=VersionPoint.model_validate(log['covered_through']) if log.get('covered_through') else None,
            captured_at=self.captured_at)
        for kind,complete in self.ledger.completeness:
            if type(complete) is not bool:raise ProtocolError('invalid_log_completeness')
        self.snapshot_sha256=expected_sha256

    @staticmethod
    def key(ref):return (ref.session_id,ref.kind,ref.object_id,ref.version,ref.config_version)

    def authorize(self,auth):
        if auth.session_id!=self.session_id or auth.actor_id!=self.actor_id or 'read' not in auth.capabilities:
            raise ProtocolError('not_found',status=404)

    def read(self,auth,ref,as_of):
        self.authorize(auth)
        if ref.session_id!=auth.session_id or (auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects):
            raise ProtocolError('not_found',status=404)
        if not before(as_of,self.captured_at):raise ProtocolError('snapshot_window_unavailable')
        key=self.key(ref)
        if key in self.records and auth.actor_id not in self._visible[key]:raise ProtocolError('not_found',status=404)
        record=self.records.get(key)
        if record is None:raise KeyError(self.key(ref))
        return record  # The assembler/fact layer checks creation and validity.

    def activity_log(self,auth,as_of):
        self.authorize(auth)
        if not before(as_of,self.captured_at):raise ProtocolError('snapshot_window_unavailable')
        return self.ledger

    def policies(self):return self._policies

    def snapshot(self,auth,subject,as_of):
        self.authorize(auth)
        matches=[r for r in self._rule_snapshots if ObjectRef.model_validate(r['subject'])==subject and VersionPoint.model_validate(r['as_of'])==as_of]
        if len(matches)!=1:raise ProtocolError('rule_snapshot_unavailable')
        row=matches[0]
        def fact(raw):return VerifiedFact(raw['name'],raw['value'],tuple(EvidenceRefV2.model_validate(r) for r in raw['sources']))
        duties=tuple(ResponsibilityFact(criterion=r['criterion'],kind=r['kind'],occurred_at=VersionPoint.model_validate(r['occurred_at']),
            valid_from=VersionPoint.model_validate(r['valid_from']),valid_until=VersionPoint.model_validate(r['valid_until']) if r.get('valid_until') else None,
            scope=tuple(ObjectRef.model_validate(v) for v in r['scope']),sources=tuple(EvidenceRefV2.model_validate(v) for v in r['sources']),
            facts=tuple(fact(v) for v in r.get('facts',[])),state=r.get('state','active')) for r in row.get('responsibilities',[]))
        from career_lab.contracts.v2.world import TestResultV2
        return RuleSnapshot(as_of=as_of,facts=tuple(fact(f) for f in row.get('facts',[])),logs_complete=row.get('logs_complete',False),
            tests=tuple(TestResultV2.model_validate(t) for t in row.get('tests',[])),test_refs=tuple(EvidenceRefV2.model_validate(t) for t in row.get('test_refs',[])),
            config_version=row.get('config_version'),technical_failures=tuple(row.get('technical_failures',[])),
            business_response=row.get('business_response',''),business_response_refs=tuple(EvidenceRefV2.model_validate(r) for r in row.get('business_response_refs',[])),
            responsibilities=duties)
