"""Test-only historical SQLite/outbox fixture; never install in production."""
from contextlib import contextmanager
import time
from uuid import uuid4
import json
from sqlalchemy import Table,Column,MetaData,String,Text,Integer,Float,select,insert,update,or_,and_
from career_lab.contracts.v2.core import ProtocolError,canonical,digest,AuthContext

metadata=MetaData()
records=Table('w05_revision_records',metadata,Column('session_id',String,primary_key=True),Column('kind',String,primary_key=True),
    Column('id',String,primary_key=True),Column('version',Integer,primary_key=True),Column('content',Text,nullable=False))
requests=Table('w05_revision_requests',metadata,Column('session_id',String,primary_key=True),Column('request_id',String,primary_key=True),
    Column('fingerprint',String,nullable=False),Column('result',Text,nullable=False))
jobs=Table('w05_evaluation_jobs',metadata,Column('id',String,primary_key=True),Column('session_id',String,nullable=False),
    Column('subject_kind',String,nullable=False),Column('subject_id',String,nullable=False),Column('auth',Text,nullable=False),
    Column('operation',String,nullable=False),Column('request_id',String,nullable=False),
    Column('status',String,nullable=False),Column('attempt',Integer,nullable=False),Column('lease',String),Column('expires_at',Float),
    Column('error_code',String),Column('feedback_id',String))
attempts=Table('w05_evaluation_attempts',metadata,Column('job_id',String,primary_key=True),Column('lease',String,primary_key=True),
    Column('number',Integer,nullable=False),Column('started_at',Float,nullable=False),Column('status',String,nullable=False),Column('error_code',String),
    Column('auth',Text,nullable=False),Column('operation',String,nullable=False),Column('request_id',String,nullable=False))


def register_tables(engine):metadata.create_all(engine)


class RevisionRepository:
    def __init__(self,engine,authority,clock=None):self.engine,self.authority,self.clock=engine,authority,clock or time.time

    @contextmanager
    def transaction(self,write=False):
        with self.engine.connect() as conn:
            if write and conn.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
            else:conn.begin()
            try:yield conn;conn.commit()
            except BaseException:conn.rollback();raise

    def get(self,conn,sid,kind,oid,version=1):
        raw=conn.execute(select(records.c.content).where(records.c.session_id==sid,records.c.kind==kind,records.c.id==oid,records.c.version==version)).scalar_one_or_none()
        if raw is None:raise ProtocolError('not_found',status=404)
        return json.loads(raw)

    def put(self,conn,sid,kind,oid,content,version=1):
        try:old=self.get(conn,sid,kind,oid,version)
        except ProtocolError as error:
            if error.status!=404:raise
        else:
            if canonical(old)!=canonical(content):raise ProtocolError('immutable_record_conflict',status=409)
            return old
        conn.execute(insert(records).values(session_id=sid,kind=kind,id=oid,version=version,content=canonical(content)))
        return content

    def run(self,auth,command,handler):
        capability='submit' if command.operation=='submissions.create' else 'act'
        fingerprint=digest({'command':command.model_dump(mode='json'),'actor':auth.actor_id,
                            'executor':auth.executor.model_dump(mode='json'),'credential_id':auth.credential_id,
                            'capabilities':auth.capabilities,'allowed_actions':auth.allowed_actions,'allowed_objects':auth.allowed_objects})
        with self.transaction(True) as conn:
            self.authority.validate(conn,auth,capability,command.operation)
            if auth.actor_id!='learner':raise ProtocolError('capability_denied',status=403)
            if self.authority.protocol(conn,auth)!='v2':raise ProtocolError('v2_required',status=422)
            before=self.authority.state(conn,auth,lock=True)
            old=conn.execute(select(requests).where(requests.c.session_id==auth.session_id,requests.c.request_id==command.request_id)).mappings().first()
            if old:
                if old['fingerprint']!=fingerprint:raise ProtocolError('request_id_reused',status=409)
                return json.loads(old['result'])
            if before.business_seq!=command.expected_version or before.workspace_revision!=command.expected_workspace_revision:
                raise ProtocolError('version_conflict',status=409)
            result,after=handler(conn,before)
            if after!=before:
                self.authority.commit_transition(conn,auth,before,after,command.operation)
                if self.authority.state(conn,auth,lock=True)!=after:raise ProtocolError('workflow_transition_mismatch',status=409)
            conn.execute(insert(requests).values(session_id=auth.session_id,request_id=command.request_id,fingerprint=fingerprint,result=canonical(result)))
            return result

    def enqueue(self,conn,auth,kind,oid,operation,request_id):
        job_id=digest([auth.session_id,kind,oid,'evaluate-v4'])
        existing=conn.execute(select(jobs).where(jobs.c.id==job_id)).mappings().first()
        if existing:return job_id
        conn.execute(insert(jobs).values(id=job_id,session_id=auth.session_id,subject_kind=kind,subject_id=oid,
            auth=auth.model_dump_json(),operation=operation,request_id=request_id,status='queued',attempt=0))
        return job_id

    def claim(self,lease_seconds=30):
        now=self.clock()
        with self.transaction(True) as conn:
            expired=and_(jobs.c.status=='running',jobs.c.expires_at<=now)
            old_rows=conn.execute(select(jobs).where(expired)).mappings().all()
            for old in old_rows:
                conn.execute(update(attempts).where(attempts.c.job_id==old['id'],attempts.c.lease==old['lease']).values(status='lease_expired',error_code='lease_expired'))
            conn.execute(update(jobs).where(expired,jobs.c.attempt>=2).values(status='failed',error_code='lease_expired'))
            row=conn.execute(select(jobs).where(or_(jobs.c.status=='queued',expired),jobs.c.attempt<2)
                             .order_by(jobs.c.id).with_for_update()).mappings().first()
            if not row:return None
            lease=uuid4().hex
            conn.execute(update(jobs).where(jobs.c.id==row['id']).values(status='running',attempt=row['attempt']+1,lease=lease,expires_at=now+lease_seconds))
            conn.execute(insert(attempts).values(job_id=row['id'],lease=lease,number=row['attempt']+1,started_at=now,status='running',
                auth=row['auth'],operation=row['operation'],request_id=row['request_id']))
            return {**row,'lease':lease,'attempt':row['attempt']+1,'expires_at':now+lease_seconds,'status':'running'}

    def check_lease(self,conn,job):
        row=conn.execute(select(jobs).where(jobs.c.id==job['id'])).mappings().one()
        if row['status']!='running' or row['lease']!=job['lease'] or row['expires_at']<=self.clock():
            raise ProtocolError('lease_lost',status=409)
        return row

    def fail(self,job,code):
        with self.transaction(True) as conn:
            self.check_lease(conn,job)
            conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='failed',error_code=code))
            conn.execute(update(attempts).where(attempts.c.job_id==job['id'],attempts.c.lease==job['lease']).values(status='failed',error_code=code))

    def renew(self,job,lease_seconds=30):
        with self.transaction(True) as conn:
            self.check_lease(conn,job)
            conn.execute(update(jobs).where(jobs.c.id==job['id']).values(expires_at=self.clock()+lease_seconds))

    def retry_failed(self,conn,job_id,auth,operation,request_id):
        row=conn.execute(select(jobs).where(jobs.c.id==job_id)).mappings().one()
        if row['status']=='failed':
            conn.execute(update(jobs).where(jobs.c.id==job_id).values(status='queued',attempt=0,lease=None,expires_at=None,error_code=None,
                auth=auth.model_dump_json(),operation=operation,request_id=request_id))

    def finish(self,job,report,diagnostics):
        with self.transaction(True) as conn:
            self.check_lease(conn,job)
            auth=AuthContext.model_validate_json(job['auth'])
            self.authority.validate(conn,auth,'act',job['operation'])
            current=self.authority.state(conn,auth,lock=True)
            self.put(conn,auth.session_id,'feedback',report.id,{'feedback':report.model_dump(mode='json'),'diagnostics':diagnostics})
            after=current.model_copy(update={'workspace_revision':current.workspace_revision+1,'storage_revision':current.storage_revision+1})
            self.authority.commit_transition(conn,auth,current,after,'feedback.complete')
            if self.authority.state(conn,auth,lock=True)!=after:raise ProtocolError('workflow_transition_mismatch',status=409)
            conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='completed',feedback_id=report.id,error_code=None))
            conn.execute(update(attempts).where(attempts.c.job_id==job['id'],attempts.c.lease==job['lease']).values(status='completed'))
        return report
