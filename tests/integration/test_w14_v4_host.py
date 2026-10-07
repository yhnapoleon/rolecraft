"""Real standard assembly for the original v4 host and the shared Agent port."""
from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import point
from test_w14_vertical_runtime import connect


def test_context_fixed_language_independent_models_and_gateway_objects(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        response=c.get('/sessions/'+sid+'/workbench',headers=h)
        assert response.status_code==200,response.text
        context=response.json()['result']['result']
        assert context['session']=={'protocol':2,'sessionId':sid,'workLanguage':'zh','scenarioHash':app.state.scenario_v2.bindings.scenario.sha256}
        assert context['semantic']=={'roles':'waiting_model','feedback':'waiting_model','assistant':'waiting_model'}
        assert context['available']['objects.read'] and context['available']['workbench.read']
        assert context['timeline']['as_of']==context['as_of']
        state=c.get('/sessions/'+sid,headers=h).json()['state']
        obj=c.get('/sessions/'+sid+'/objects/material/brief/1',headers=h)
        assert obj.status_code==200 and obj.json()['content']['fragments']
        assert c.get('/sessions/'+sid,headers=h).json()['state']==state
        assert c.post('/sessions',json={'schema_version':2,'scenario':'pm_pilot_v2','work_language':'en'}).json()['code']=='work_language_unavailable'
        legacy=c.post('/sessions',json={'scenario':'pm_pilot'})
        assert legacy.status_code==200 and 'schema_version' not in legacy.json()
    finally:app.state.store.close()


def test_server_owns_config_versions_and_stale_base_is_rejected(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        cfg=app.state.scenario_v2.package.baseline(sid)
        base=C.ObjectRef(session_id=sid,kind='config',object_id=cfg.id,version=cfg.version,config_version=cfg.config_version).model_dump(mode='json')
        result=send('configuration','config','configuration.apply',{'base':base,'settings':{'participants':12}})
        saved=c.get('/sessions/'+sid+'/workbench',headers=h).json()['result']['result']['timeline']['workspace']['config']
        assert saved['version']==2 and saved['config_version']==1 and saved['participants']==12
        before=result['state']
        response=c.post('/sessions/'+sid+'/configuration',headers=h,json={'schema_version':2,'request_id':'stale',
            'expected_version':before['business_seq'],'expected_workspace_revision':before['workspace_revision'],
            'operation':'configuration.apply','payload':{'base':base,'settings':{'participants':18}}})
        assert response.status_code==409 and response.json()['code']=='object_version_conflict'
        assert c.get('/sessions/'+sid,headers=h).json()['state']==before
    finally:app.state.store.close()


def test_history_port_uses_persisted_receipts_same_transaction_and_expiry(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        store=app.state.v2_store;auth=store.authenticate(sid,h['Authorization'].split(' ',1)[1])
        initial=store.query(auth,lambda view:view.public_history(C.ResourcePage(limit=1),auth))
        assert initial.material_reads==() and initial.acquisitions_complete
        ref=C.ObjectRef(session_id=sid,kind='material',object_id='brief',version=1).model_dump(mode='json')
        actual=send('actions','read','read_material',{'tool':'read_material','material':ref})
        window,reader=store.query(auth,lambda view:(view.public_history(C.ResourcePage(limit=1),auth),view.public_history))
        assert window.acquisitions_complete and len(window.material_reads)==1
        assert [f.model_dump(mode='json',exclude={'fact_ids'}) for f in window.material_reads[0].fragments]==actual['result']['fragments']
        assert window.next_seq==min(window.as_of.business_seq,1)
        import pytest
        with pytest.raises(C.ProtocolError) as expired:reader(C.ResourcePage(),auth)
        assert expired.value.code=='reference_view_expired'
        observation=c.get('/sessions/'+sid+'/observation',headers=h)
        assert observation.status_code==200,observation.text
        assert app.state.w06 is not None
    finally:app.state.store.close()


def test_whole_public_source_span_is_exact_and_private_file_is_denied(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        module=app.state.scenario_v2;store=app.state.v2_store;auth=store.authenticate(sid,h['Authorization'].split(' ',1)[1])
        name=module.package.rules['material_files']['policy']['1']
        text=C.read_file(module.package.root,module.files[name]).decode()
        ref=C.EvidenceRefV2(session_id=sid,kind='material',object_id='policy',version=1,observed_at_seq=0,quote=text,span_start=0,span_end=len(text))
        assert store.query(auth,lambda view:view.reference_allowed(ref))
        import pytest
        with pytest.raises(C.ProtocolError):store.query(auth,lambda view:view.reference_allowed(ref.model_copy(update={'quote':text[:-1]+'x'})))
        private=C.ObjectRef(session_id=sid,kind='material',object_id='world_private',version=1)
        with pytest.raises(C.ProtocolError):store.query(auth,lambda view:view.reference_allowed(private))
    finally:app.state.store.close()


def test_public_material_recovery_redacts_only_internal_fact_links(tmp_path):
    import json
    from sqlalchemy import select
    from career_lab.storage.v2_tables import v2_transactions
    app,c,sid,h,send=connect(tmp_path)
    try:
        material=C.ObjectRef(session_id=sid,kind='material',object_id='brief',version=1).model_dump(mode='json')
        before=c.get('/sessions/'+sid,headers=h).json()['state']
        actual=send('actions','source','read_material',{'tool':'read_material','material':material})
        recovered=c.get('/sessions/'+sid+'/requests/source',headers=h).json()['response']
        direct=c.get('/sessions/'+sid+'/objects/material/brief/1',headers=h).json()
        with app.state.v2_store.db.engine.connect() as conn:
            raw=json.loads(conn.execute(select(v2_transactions.c.result).where(v2_transactions.c.session_id==sid,v2_transactions.c.request_id=='source')).scalar_one())
        assert any(f['fact_ids'] for f in raw['result']['fragments'])
        expected=[{k:v for k,v in f.items() if k!='fact_ids'} for f in raw['result']['fragments']]
        assert actual['result']['fragments']==expected==recovered['result']['fragments']
        assert all('fact_ids' not in f for f in direct['content']['fragments'])
        replay=c.post('/sessions/'+sid+'/actions',headers=h,json={'schema_version':2,'request_id':'source','operation':'read_material','expected_version':before['business_seq'],'expected_workspace_revision':before['workspace_revision'],'payload':{'tool':'read_material','material':material}})
        assert replay.status_code==200,replay.text
        again=replay.json()
        assert again['replayed'] and again['result']['fragments']==expected
        observation=c.get('/sessions/'+sid+'/observation',headers=h).json()['result']
        assert all('fact_ids' not in f for f in observation['visible_sources'])
        # An identically named user field in an unrelated payload is untouched.
        from career_lab.api.public_materials import material_result
        own={'legacy':{'raw':{'fact_ids':['user-authored-label']}}}
        assert material_result('work_products.create',own)==own
    finally:app.state.store.close()


def test_reviews_are_discoverable_without_private_request_journals(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        product=send('work-products','note','work_products.create',{'kind':'text','purpose':'exploration','title':'Open question','content':'Investigate before deciding'})['result']['ref']
        review=send('reviews','review','reviews.create',{'subjects':[product],'purpose':'exploration','scope':['evidence'],'question':'What remains unknown?'})['result']['review']
        response=c.get('/sessions/'+sid+'/reviews',headers=h)
        assert response.status_code==200,response.text
        page=response.json()['result']['result']
        assert len(page['items'])==1 and page['items'][0]['id']==review['object_id']
        assert page['items'][0]['subjects']==[product]
        assert c.get('/sessions/'+sid+'/reviews/'+review['object_id'],headers=h).json()['result']['result']['items']==page['items']
        assert c.get('/sessions/'+sid+'/feedback/'+review['object_id'],headers=h).status_code==200
    finally:app.state.store.close()
