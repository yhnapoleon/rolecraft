"""Additive tables only. No columns or historical rows in v1 are changed."""
from sqlalchemy import Table, Column, String, Text, Integer
from career_lab.storage.database import metadata

def text(name):return Column(name,Text,nullable=False)
def key(name):return Column(name,String,primary_key=True)
def integer(name):return Column(name,Integer,nullable=False)

v2_sessions=Table('v2_sessions',metadata,key('id'),text('bindings'),text('state'),integer('storage_revision'))
v2_credentials=Table('v2_credentials',metadata,key('id'),Column('session_id',String,nullable=False),Column('token_hash',String,unique=True,nullable=False),text('context'),integer('revoked'))
v2_objects=Table('v2_objects',metadata,key('session_id'),key('kind'),key('id'),Column('version',Integer,primary_key=True),text('record'),integer('created_revision'))
v2_heads=Table('v2_heads',metadata,key('session_id'),key('kind'),key('id'),integer('version'))
v2_relations=Table('v2_relations',metadata,key('session_id'),key('source_kind'),key('source_id'),Column('source_version',Integer,primary_key=True),key('target_kind'),key('target_id'),Column('target_version',Integer,primary_key=True))
v2_events=Table('v2_events',metadata,key('session_id'),Column('seq',Integer,primary_key=True),text('record'))
v2_transactions=Table('v2_transactions',metadata,key('session_id'),key('request_id'),text('fingerprint'),text('result'),text('boundary'))
v2_snapshots=Table('v2_snapshots',metadata,key('session_id'),Column('storage_revision',Integer,primary_key=True),text('state'))
v2_restores=Table('v2_restores',metadata,key('target_session_id'),text('request_id'),text('snapshot_hash'),text('result'))

v2_external_refs=Table('v2_external_refs',metadata,key('session_id'),key('kind'),key('id'),Column('version',Integer,primary_key=True),text('record'),integer('created_revision'))

v2_request_meta=Table('v2_request_meta',metadata,key('session_id'),key('request_id'),text('credential_id'),text('executor'),text('actor_id'),text('operation'),text('scope_refs'),text('job_ids'))
