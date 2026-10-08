import json
from career_lab.runtime.roles_v2 import LocalRoleModel

def test_local_reference_uses_authorized_original_text_without_json_or_private_draft():
    context={'work_language':'zh','responsibilities':['解释工程约束'],'omissions':{'learner_scope':0},'sources':[
      {'display_name':'经理委托 · v1','text':'公开委托','channel':'material'},
      {'display_name':'技术说明 · v1','text':'索引滞后24小时','channel':'material'},
      {'display_name':'技术说明 · v1','text':'另一段技术内容','channel':'material'},
      {'display_name':'共享作品 · v1','text':json.dumps({'title':'政策测试','content':'旧索引500，刷新后400','purpose':'exploration','structured_payload':None},ensure_ascii=False),'channel':'received_share'}]}
    result=LocalRoleModel().complete([{'role':'system','content':'test\nCONTEXT\n'+json.dumps(context,ensure_ascii=False)},{'role':'user','content':'索引测试有什么记录？'}],[])
    assert '索引滞后24小时' in result.text and '政策测试\n旧索引500，刷新后400' in result.text
    assert 'structured_payload' not in result.text and '"content"' not in result.text
    assert '等待模型接入' in result.text and result.text.count('[技术说明 · v1]')==1
