import {describe,expect,it} from 'vitest';
import {workFolderMarkup,workFolderTrayMarkup} from './work-folder.js';
const work=(id,extra={})=>({id,title:`作品 ${id}`,purpose:'探索笔记',source:'user',body:`# ${id}\n\n这是实际作品的正文。`,revision:2,...extra});
const record=html=>JSON.parse(html.match(/<script[^>]+data-folder-record>([\s\S]*?)<\/script>/)[1]);
describe('readable real-work folder tray',()=>{
  it('leaves zero and one current work on the original card path',()=>{
    expect(workFolderMarkup({taskId:'task',works:[]})).toBe('');
    expect(workFolderMarkup({taskId:'task',works:[work('one')]})).toBe('');
    expect(workFolderMarkup({taskId:'task',works:[work('one'),work('removed',{removedAt:'2026-10-05'})]})).toBe('');
  });
  it('retains every current work without removed work or empty placeholders',()=>{
    const html=workFolderMarkup({taskId:'task',title:'事项标题',works:[work('old'),work('second'),work('third'),work('latest'),work('removed',{removedAt:'now'})]});
    const data=record(html);expect(data.works.map(w=>w.id)).toEqual(['latest','third','second','old']);expect(data.title).toBe('事项标题');
    expect(workFolderTrayMarkup(data).match(/data-folder-card=/g)).toHaveLength(4);expect(html).not.toContain('data-folder-list-toggle');
    expect(workFolderMarkup({taskId:'two',works:[work('one'),work('two')]}).match(/data-folder-thumb=/g)).toHaveLength(2);
  });
  it('shows real version, pending state and body excerpt without mutating work',()=>{
    const works=[work('one'),work('pending',{source:'agent',adopted:false,revision:7})],snapshot=structuredClone(works);
    const data=record(workFolderMarkup({taskId:'task',works})),html=workFolderTrayMarkup(data);
    expect(data.works[0]).toMatchObject({pending:true,version:7,summary:'pending 这是实际作品的正文。'});
    expect(html).toContain('待检查');expect(html).toContain('v7');expect(works).toEqual(snapshot);
  });
  it('keeps full long titles and escapes source and Agent content',()=>{
    const long='很长的完整作品标题'.repeat(30);
    const html=workFolderMarkup({taskId:'task" onclick="bad',works:[work('id"bad',{title:'<img src=x onerror=bad>',body:'</script><img src=x onerror=bad>'}),work('long',{title:long})]});
    expect(html).not.toContain('<img');const tray=workFolderTrayMarkup(record(html));expect(tray).toContain(long);expect(tray).not.toContain('<img');
    expect(tray).toContain('&lt;img src=x onerror=bad&gt;');expect(tray).toContain('data-work-flight-title');expect(tray).toContain('data-work-flight-icon');
  });
  it('preserves stable focus IDs when titles or ordering change',()=>{
    const before=record(workFolderMarkup({taskId:'task/one',works:[work('a'),work('b')]})),after=record(workFolderMarkup({taskId:'task/one',works:[work('b',{title:'changed draft'}),work('a')]}));
    const ids=html=>[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
    expect(ids(workFolderTrayMarkup(before)).sort()).toEqual(ids(workFolderTrayMarkup(after)).sort());
    expect(new Set(ids(workFolderTrayMarkup(before))).size).toBe(ids(workFolderTrayMarkup(before)).length);
    expect(workFolderTrayMarkup(before)).toContain('id="work-folder-task%2Fone-paper-a"');
  });
});
