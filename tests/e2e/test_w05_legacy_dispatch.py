"""Legacy dispatch uses the real existing v1 store and rules-v3 implementation."""
import pytest
from career_lab.assistant.service import TrainingService
from career_lab.storage.sessions import SessionStore,digest
from career_lab.api.feedback import saved_feedback,generate_feedback
from career_lab.rubrics.v4.feedback import FeedbackDispatcher
from career_lab.contracts.v2.core import ProtocolError


def test_w05_dispatch_keeps_v3_and_saved_history_unchanged(tmp_path,spec):
    store=SessionStore(f'sqlite:///{tmp_path / "legacy.db"}');store.create_session(spec,'s')
    service=TrainingService(store)
    plan={'participants':20,'knowledge_domains':['stable_faq'],'launch_day':7,'update_strategy':'daily','fallback':'human','work_items':['scope_filter','human_fallback']}
    service.action('s','update_pilot',{'plan':plan},'config',0)
    artifact=service.save_artifact('s',{'goal':'试点目标','rationale':'有依据的小范围试点'},'artifact')
    sub=service.submit_plan('s',artifact['id'],1,'submit')
    calls=[]
    dispatcher=FeedbackDispatcher(lambda sid,oid:saved_feedback(store,sid,oid),lambda sid,oid:generate_feedback(store,sid,oid),lambda sid,oid:calls.append((sid,oid)))
    first=dispatcher.get_or_generate('rules-v3','s',sub['id']);before=digest(first)
    assert first['model_revision']=='rules-v3' and calls==[]
    assert digest(dispatcher.get_or_generate('rules-v3','s',sub['id']))==before
    assert store.get_state('s').status=='submitted'
    with pytest.raises(ValueError):service.action('s','resume',{},'resume',store.get_state('s').version)
    store.close()


def test_w05_unsupported_history_only_reads_an_existing_saved_report():
    def missing(*args):raise KeyError('missing')
    dispatcher=FeedbackDispatcher(missing,lambda *args:pytest.fail('must not substitute v3'),lambda *args:pytest.fail('must not substitute v4'))
    with pytest.raises(ProtocolError,match='historical rules unavailable'):dispatcher.get_or_generate('rules-v2','s','old')
    old={'model_revision':'rules-v2','items':[{'label':'INSUFFICIENT'}]}
    cached=FeedbackDispatcher(lambda *args:old,lambda *args:pytest.fail('no regeneration'),lambda *args:pytest.fail('no v4'))
    assert cached.get_or_generate('rules-v2','s','old') is old
