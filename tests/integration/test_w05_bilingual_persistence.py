"""Real c9 persistence with controlled trusted language injection, not a session-language binding."""
import json,hashlib,re
import pytest
from fastapi.testclient import TestClient
from test_w05_c8_persistence import prepared_env,cmd,feedback_bytes
from career_lab.contracts import v2 as C
from career_lab.api.reviews_v2 import create_review_evaluator,prepare_review_feedback,review_feedback_plan
from career_lab.api.feedback_integration import record_feedback_response,install_feedback_recovery
from career_lab.api.modules import ExtensionRegistry
from career_lab.api.app import create_app
from career_lab.storage.v2_lifecycle import record_review,point
from career_lab.evidence.v2.snapshot_reader import SnapshotEvidenceReader


@pytest.mark.parametrize('prepared_env',['zh','en'],indirect=True)
def test_w05_language_feedback_supplement_followup_persist_and_reopen(prepared_env,tmp_path):
    e=prepared_env;language=e['work_language'];store=e['store'];auth=e['auth'];before=feedback_bytes(e)
    original=C.FeedbackV2.model_validate(store.read(auth,e['feedback']).content)
    assert any(('作品明确关联' if language=='zh' else 'explicitly links') in x for x in original.verified_facts[0].summary)
    supplement=C.FeedbackResponseCreate(feedback_id=e['feedback'].object_id,feedback_version=1,kind='supplement',text='保留原文 / Keep this original.',
        evidence=(C.EvidenceRefV2(**e['source'].model_dump(),observed_at_seq=0,quote='CONTROLLED SOURCE QUOTE',span_start=0,span_end=23),))
    response=store.execute(auth,cmd(store,auth,'feedback.responses.create',supplement.model_dump(mode='json'),'bilingual-supplement'),record_feedback_response).objects[0]
    review=C.ReviewInput(subjects=(e['work'],),scope=(),purpose='结果报告' if language=='zh' else ' Result Report ',decision='no_go',followup_of=(response,))
    saved_ref=store.execute(auth,cmd(store,auth,'reviews.create',review.model_dump(mode='json'),'bilingual-followup'),record_review).objects[0]
    saved=C.ReviewRequest.model_validate(store.read(auth,saved_ref).content)
    # A new controlled capture records the real current point; source formation
    # times, quotations, log coverage and original snapshot remain unchanged.
    raw=json.loads(e['snapshot_path'].read_text());raw['captured_at']=point(store.view(auth).state).model_dump(mode='json')
    path=tmp_path/('followup-'+language+'.json');data=json.dumps(raw).encode();path.write_bytes(data)
    evaluator=create_review_evaluator(SnapshotEvidenceReader(path,hashlib.sha256(data).hexdigest()),work_language=language)
    prepared=prepare_review_feedback(evaluator,auth,saved)
    assert prepared['followup_status']=='linked_not_resolved' and prepared['followup_evidence_status']=='not_evaluated'
    txn=store.execute(auth,cmd(store,auth,'feedback.request',{'subject':saved_ref.model_dump(mode='json')},'bilingual-feedback'),lambda v,c,a:review_feedback_plan(v,c,a,prepared),derived_subject=saved_ref)
    report_ref=txn.objects[0]
    registry=ExtensionRegistry();install_feedback_recovery(registry);app=create_app(str(store.db.engine.url),extensions=registry)
    try:
        with TestClient(app) as client:
            header={'Authorization':'Bearer '+e['token']}
            result=client.get(f'/sessions/{auth.session_id}/feedback-records/{report_ref.object_id}',headers=header);assert result.status_code==200,result.text
            report=C.FeedbackV2.model_validate(result.json()['result']['result']['feedback'])
            assert any(('引文默认未核实' if language=='zh' else 'unverified by default') in x for x in report.next_options)
            refs=[r.verified_ref for r in report.verified_facts[0].references if r.verified_ref]
            assert refs[0].quote=='CONTROLLED SOURCE QUOTE' and refs[0].version==1
            response_get=client.get(f'/sessions/{auth.session_id}/feedback-responses/{response.object_id}',headers=header)
            assert response_get.status_code==200 and 'Keep this original.' in response_get.text and '保留原文' in response_get.text
    finally:app.state.store.close()
    assert feedback_bytes(e)==before
