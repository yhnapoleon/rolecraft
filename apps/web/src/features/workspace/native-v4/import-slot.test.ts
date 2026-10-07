import {describe,it,expect} from 'vitest';
import {readLegacyAttempts,readImportPreview} from './import-slot';
import {buildBrowserImport} from '../import-browser';

describe('W03 native import selection',()=>{
  it('reads the actual v4 exported-state shape and excludes credentials from selected input',async()=>{
    const raw={version:4,attempts:[{id:'old-session',token:'DO-NOT-UPLOAD',tasks:[{id:'t',title:'Keep task',api_key:'PRIVATE-KEY'}],artifacts:[{id:'yes',kind:'text',body:'Retain this text',sessionToken:'PRIVATE-TOKEN'},{id:'no',kind:'text',body:'UNSELECTED PRIVATE CONTENT'}],events:[]}]};
    const original=JSON.stringify(raw),attempt=readLegacyAttempts(raw)[0];
    const input=await buildBrowserImport(attempt,{taskIds:['t'],productIds:['yes']});
    const serialized=JSON.stringify(input);for(const secret of ['DO-NOT-UPLOAD','PRIVATE-KEY','PRIVATE-TOKEN','UNSELECTED PRIVATE CONTENT'])expect(serialized).not.toContain(secret);
    expect(input.items.map(i=>i.original_id)).toEqual(['t','yes']);expect(serialized).toContain('Retain this text');expect(JSON.stringify(raw)).toBe(original);
  });
  it('requires a preview for the matching package and preserves unresolved mappings',async()=>{
    const input=await buildBrowserImport({id:'old',tasks:[],artifacts:[{id:'p',kind:'text',body:'body'}]},{taskIds:[],productIds:['p']});
    const preview={schema_version:2,mode:'preview',package_id:input.package_id,applied:false,as_of:{business_seq:0,workspace_revision:1,storage_revision:3},id_map:{},unresolved:[{original_id:'old-test',original_session_id:'old',status:'foreign_session'}],version_map:[]};
    expect(readImportPreview({schema_version:2,result:preview},input).unresolved).toEqual(preview.unresolved);
    expect(()=>readImportPreview({...preview,package_id:'other'},input)).toThrow('invalid_import_preview');
    expect(()=>readImportPreview({...preview,mode:'apply'},input)).toThrow('invalid_import_preview');
  });
});
