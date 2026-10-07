"""Acceptance prerequisites through the real frozen Gateway; controlled scenario only."""
import pytest
from career_lab.contracts.v2 import ObjectRef, ProtocolError
from test_formal_gateway import api, call, product_page


def test_equivalent_text_and_template_keep_all_content_and_private_exact_refs(api):
    app, client, sid = api
    store = app.state.v2_store
    owner = store.authenticate(sid, client.headers['Authorization'].removeprefix('Bearer '))
    before = store.view(owner).state
    task = call(api, '/work-items', 'work_items.create', {'title': '先测试，再决定', 'goal': '允许暂缓或求助'}).json()['result']['ref']
    content = '本轮先覆盖FAQ；政策变化后重测，再判断是否扩大范围。'
    refs = []
    for kind in ('text', 'plan'):
        payload = {'kind': kind, 'task': task, 'title': '同一结论的不同表达', 'purpose': 'exploration', 'content': content}
        if kind == 'plan':
            payload['structured_payload'] = {'type': 'plan', 'sections': {'decision': content}}
        response = call(api, '/work-products', 'work_products.create', payload)
        assert response.status_code == 200, response.text
        refs.append(ObjectRef.model_validate(response.json()['result']['ref']))
    assert refs[0] != refs[1]
    products = product_page(client, sid)['items']
    assert {p['kind'] for p in products} == {'text', 'plan'}
    assert all(p['content'] == content and p['task'] == task and p['visibility'] == 'private' for p in products)
    assert next(p for p in products if p['kind'] == 'plan')['structured_payload']['sections']['decision'] == content
    for ref in refs:
        assert store.read(owner, ref).content['content'] == content
        for role in ('supervisor', 'business_lead', 'tech_lead'):
            with pytest.raises(ProtocolError):
                store.read(store.role_reader(sid, role), ref)
    after = store.view(owner)
    assert after.state.business_seq == before.business_seq
    assert not any(o.ref.kind in {'submission', 'feedback', 'approval'} for o in after.objects)


def test_reordering_and_pausing_preserve_multiple_work_products(api):
    app, client, sid = api
    first = call(api, '/work-items', 'work_items.create', {'title': '先保留问题', 'order': 0}).json()['result']['object']
    second = call(api, '/work-items', 'work_items.create', {'title': '随后测试', 'order': 1}).json()['result']['object']
    task_ref = {'session_id': sid, 'kind': 'task', 'object_id': first['id'], 'version': first['revision']}
    saved = []
    for title in ('探索文字', '备选方案'):
        saved.append(call(api, '/work-products', 'work_products.create', {'kind': 'text', 'title': title, 'content': title, 'task': task_ref}).json()['result']['ref'])
    response = call(api, '/work-items/batch', 'work_items.batch', {'updates': [
        {'item_id': first['id'], 'expected_revision': first['revision'], 'order': 1, 'status': 'paused'},
        {'item_id': second['id'], 'expected_revision': second['revision'], 'order': 0},
    ]})
    assert response.status_code == 200, response.text
    tasks = client.get(f'/sessions/{sid}/work-items').json()['result']['result']['items']
    assert [t['id'] for t in tasks] == [second['id'], first['id']]
    assert tasks[1]['status'] == 'paused'
    products = product_page(client, sid)['items']
    assert len(products) == 2 and all(ObjectRef.model_validate(p['task']) == ObjectRef.model_validate(task_ref) and p['version'] == 1 for p in products)
    assert {p['product_id'] for p in products} == {r['object_id'] for r in saved}


def test_edit_and_split_form_can_use_one_exact_revision_batch(api):
    _, client, sid = api
    original = call(api, '/work-items', 'work_items.create', {'title': 'Original', 'priority': 1}).json()['result']['object']
    parent = {'session_id': sid, 'kind': 'task', 'object_id': original['id'], 'version': original['revision']}
    result = call(api, '/work-items/batch', 'work_items.batch', {
        'updates': [{'item_id': original['id'], 'expected_revision': original['revision'], 'title': 'Renamed', 'goal': 'Kept note', 'priority': 2}],
        'creates': [{'title': 'Split question', 'parent': parent, 'priority': 2}],
    })
    assert result.status_code == 200, result.text
    tasks = client.get(f'/sessions/{sid}/work-items').json()['result']['result']['items']
    assert len(tasks) == 2 and all(t['priority'] == 2 for t in tasks)
    renamed = next(t for t in tasks if t['id'] == original['id'])
    child = next(t for t in tasks if t['id'] != original['id'])
    assert renamed['title'] == 'Renamed' and renamed['goal'] == 'Kept note'
    assert ObjectRef.model_validate(child['parent']) == ObjectRef.model_validate(parent)
    stale = call(api, '/work-items/'+original['id'], 'work_items.update', {'item_id': original['id'], 'expected_revision': original['revision'], 'title': 'Must not overwrite'}, 'PATCH')
    assert stale.status_code == 409
