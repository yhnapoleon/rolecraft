"""Executable blocked-case evidence, not assertions that these are fixed.

Replace these expected failures with positive tests only after the formal W01
input upgrade. They document why W04 cannot yet claim full delivery.
"""
from datetime import datetime, timedelta, timezone

import pytest
from career_lab.contracts.v2 import DelegationGrant, Executor, ProtocolError
from test_runtime import build_runtime, session, send


def test_r3_still_blocks_scoped_role_turn_creation(tmp_path):
    rt=build_runtime("sqlite:///"+str(tmp_path/"blocked-scope.db"));owner,_=session(rt)
    grant=DelegationGrant(id="restricted",session_id=owner.session_id,actor_id="learner",
        executor=Executor(id="agent",kind="external_agent",delegation_id="restricted"),
        capabilities=("read","act"),allowed_objects=("faq",),allowed_actions=("turns.create",),
        expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=rt[0].issue_delegation(owner,grant);restricted=rt[0].authenticate(owner.session_id,token)
    with pytest.raises(ProtocolError,match="object not found"):
        send(rt,restricted,"turns.create","scope",{"role_id":"tech_lead","text":"请帮忙判断"})


def test_r3_unrelated_edit_still_blocks_fixed_job(tmp_path):
    rt=build_runtime("sqlite:///"+str(tmp_path/"blocked-stale.db"));auth,_=session(rt)
    started,_=send(rt,auth,"turns.create","turn",{"role_id":"tech_lead","text":"风险如何"})
    send(rt,auth,"work_products.create","unrelated",{"kind":"text","content":"与本次角色上下文无关的私人草稿"})
    for _ in range(3):rt[3].run_once()
    job=rt[3].jobs.get(started["result"]["queued_jobs"][0])
    assert job["status"]=="failed" and job["error"]=="ProtocolError"
    assert job["result"] is None
