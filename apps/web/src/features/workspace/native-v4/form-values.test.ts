import {describe,it,expect} from 'vitest';
import {canonicalPurpose,taskPriority} from './form-values';
describe('original v4 control values',()=>{
  it('maps known Chinese purpose values but keeps free purpose text unchanged',()=>{
    expect(['探索笔记','测试计划','方案比较','试点决定','自由作品'].map(canonicalPurpose)).toEqual(['exploration','test_plan','option','commitment','freeform']);
    expect(canonicalPurpose('my unusual purpose')).toBe('my unusual purpose');expect(canonicalPurpose('commitment')).toBe('commitment');
  });
  it('maps the actual first/next/later radio choices and rejects unknown values',()=>{
    expect(['first','next','later'].map(taskPriority)).toEqual([0,1,2]);expect(taskPriority('2')).toBe(2);expect(()=>taskPriority('urgent')).toThrow();
  });
});

import {confirmedFormDraft,type FormDraft} from './form-slot';
it('does not clear newer form input when a lost-response request is recovered',()=>{
  const sent:FormDraft={schema:1,token:'sent',values:{title:'original'}};
  const newer:FormDraft={schema:1,token:'newer',values:{title:'new text'},requestId:'r',requestToken:'sent'};
  const result=confirmedFormDraft(newer,sent);expect(result.changed).toBe(true);expect(result.draft.values.title).toBe('new text');expect(result.draft.saved).not.toBe(true);expect(result.draft.requestId).toBeUndefined();
  expect(confirmedFormDraft(sent,sent).draft.saved).toBe(true);
});
