import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { WorkspaceClient, draftOf, type Transport } from './client';
import { WorkspacePanel, ImportPreview } from './WorkspacePanel';
import { buildBrowserImport, canonical, hash } from './import-browser';
import type { WorkProductVersion, ImportResult } from './contract-types';
import { memoryClient } from './test-support';
import { purposeText, recipientText } from './native-slots';
import { setPreference } from '../../app/i18n';

function memory() {
  const values = new Map<string, string>();
  return {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
  };
}
function work(): WorkProductVersion {
  return {
    product_id: 'p1',
    session_id: 's',
    version: 1,
    cycle: { session_id: 's', kind: 'cycle', object_id: 'c', version: 1 },
    kind: 'text',
    title: '原作品',
    purpose: 'freeform',
    content: '初稿',
    content_hash: '0'.repeat(64),
    author: { id: 'person', kind: 'human' },
    executor: { id: 'person', kind: 'human' },
    created_at: '2026-10-06T13:00:00Z',
    adoption: { status: 'unadopted' },
    removed_at: null,
  };
}
function fixture() {
  const storage = memory();
  const server = {
    products: [work()],
    tasks: [],
    as_of: { business_seq: 7, workspace_revision: 1, storage_revision: 11 },
  };
  const controls = { lost: false, conflict: false, hook: () => {} };
  const saved = new Map<string, any>();
  const transport = vi.fn<Transport>(async (path, body: any) => {
    if (!body)
      return {
        items: structuredClone(path.includes('work-items') ? server.tasks : server.products),
        as_of: { ...server.as_of },
        next_cursor: null,
      };
    controls.hook();
    if (controls.conflict) throw Object.assign(Error('version conflict'), { status: 409 });
    if (saved.has(body.request_id)) return saved.get(body.request_id);
    const product = {
      ...server.products[0],
      ...body.payload,
      version: server.products[0].version + 1,
    };
    server.products = [product];
    server.as_of.workspace_revision++;
    server.as_of.storage_revision++;
    const result = { object: structuredClone(product), as_of: { ...server.as_of } };
    saved.set(body.request_id, result);
    if (controls.lost) {
      controls.lost = false;
      throw Error('response lost');
    }
    return result;
  });
  const client = memoryClient('s', storage, transport, () => 'request-1');
  return { client, storage, transport, server, controls };
}

describe('W03 independent workspace feature (explicit transport double)', () => {
  it('journals before sending and restores exactly the original command after response loss', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.client.snapshot().products[0];
    f.client.keepDraft(p.product_id, { ...draftOf(p), content: '本机修改' });
    f.controls.lost = true;
    f.controls.hook = () =>
      expect(JSON.parse(f.storage.getItem(f.client.key)!).pending.command.request_id).toBe(
        'request-1',
      );
    await expect(f.client.save(p)).rejects.toThrow('response lost');
    const original = structuredClone(f.client.snapshot().journal.pending!.command);
    const restored = memoryClient('s', f.storage, f.transport);
    await restored.retry();
    expect(f.transport.mock.calls.filter(([, b]) => !!b).map(([, b]) => b)).toEqual([
      original,
      original,
    ]);
    expect(f.server.products[0].version).toBe(2);
    expect(restored.snapshot().journal.pending).toBeUndefined();
  });
  it('retains in-flight edits instead of replacing them with a saved older version', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.server.products[0];
    f.client.keepDraft('p1', { ...draftOf(p), content: '准备发出' });
    f.controls.hook = () => f.client.keepDraft('p1', { ...draftOf(p), content: '发送后继续写' });
    await f.client.save(p);
    expect(f.client.snapshot().journal.drafts.p1.content).toBe('发送后继续写');
    expect(f.server.products[0].content).toBe('准备发出');
  });
  it('keeps local and server content on 409, without silently retrying', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.server.products[0];
    f.client.keepDraft('p1', { ...draftOf(p), content: '我的文字' });
    f.server.products = [{ ...p, content: '另一客户端', version: 2 }];
    f.controls.conflict = true;
    await expect(f.client.save(p)).rejects.toThrow('version conflict');
    expect(f.client.snapshot().journal.conflicts.p1.local.content).toBe('我的文字');
    expect(f.client.snapshot().journal.conflicts.p1.server?.content).toBe('另一客户端');
    expect(f.transport.mock.calls.filter(([, b]) => !!b)).toHaveLength(1);
  });
  it('does not send if journaling fails, and keeps typed text in memory', async () => {
    const f = fixture();
    await f.client.refresh();
    f.storage.setItem = () => {
      throw Error('quota');
    };
    f.client.keepDraft('p1', { ...draftOf(f.server.products[0]), content: '保留输入' });
    await expect(f.client.save(f.server.products[0])).rejects.toThrow();
    expect(f.client.snapshot().journal.drafts.p1.content).toBe('保留输入');
    expect(f.transport.mock.calls.filter(([, b]) => !!b)).toHaveLength(0);
  });
  it('keeps the pre-send pending operation when response persistence fails', async () => {
    const f = fixture();
    await f.client.refresh();
    const setter = f.storage.setItem;
    f.client.keepDraft('p1', { ...draftOf(f.server.products[0]), content: '输入' });
    f.controls.hook = () => {
      f.storage.setItem = () => {
        throw Error('quota');
      };
    };
    await expect(f.client.save(f.server.products[0])).rejects.toThrow('确认未保存');
    f.storage.setItem = setter;
    f.controls.hook = () => {};
    const restored = memoryClient('s', f.storage, f.transport);
    expect(restored.snapshot().journal.pending).toBeDefined();
    await restored.retry();
    expect(f.server.products[0].version).toBe(2);
  });
  it('does not overwrite unreadable storage', () => {
    const storage = memory();
    storage.setItem('rolecraft.workspace.feature.v2.s', '{broken');
    const client = memoryClient('s', storage, async () => {});
    expect(client.snapshot().storageError).toBe(true);
    client.keepDraft('x', { kind: 'text', content: 'new' });
    expect(storage.getItem('rolecraft.workspace.feature.v2.s')).toBe('{broken');
    expect(storage.getItem(client.key)).toBeNull();
  });
  it('keeps a pending save when a response refers to another product', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.server.products[0];
    f.client.keepDraft('p1', { ...draftOf(p), content: '不能丢' });
    f.transport.mockImplementationOnce(async () => ({
      object: { ...p, product_id: 'foreign', version: 2 },
      as_of: f.server.as_of,
    }));
    await expect(f.client.save(p)).rejects.toThrow('原请求');
    expect(f.client.snapshot().journal.pending).toBeDefined();
    expect(f.client.snapshot().journal.drafts.p1.content).toBe('不能丢');
  });
  it('renders a compact directory with escaped user titles, sync status and named controls', async () => {
    const f = fixture();
    f.server.products[0].title = '<script>private()</script>';
    await f.client.refresh();
    const html = renderToStaticMarkup(<WorkspacePanel client={f.client} locale="en" />);
    expect(html).toContain('Tasks and work');
    expect(html).toContain('Work directory');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>private()');
    expect(html).toContain('Start writing');
  });
  it('rejects malformed share responses before exposing them to the component', async () => {
    const f = fixture();
    await f.client.refresh();
    await expect(f.client.loadShares('p1')).rejects.toThrow('Invalid share response');
    expect(f.client.snapshot().shares).toEqual({});
  });
  it('sends formal schema-version and dedicated adoption payload without copying work content', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.server.products[0];
    await f.client.adopt(p);
    const command = f.transport.mock.calls.find(([, body]) => !!body)![1] as any;
    expect(command.schema_version).toBe(2);
    expect(command.operation).toBe('work_products.adopt');
    expect(command.payload).toEqual({
      product_id: 'p1',
      product_version: 1,
      expected_head: 1,
      status: 'adopted',
    });
    expect(command.payload.content).toBeUndefined();
  });
  it('uses the formal POST share-change route while retaining exact versions', async () => {
    const f = fixture();
    await f.client.refresh();
    await f.client.updateShare({
      product_id: 'p1',
      share_id: 'share1',
      expected_revision: 2,
      operation: 'revoke',
    });
    const call = f.transport.mock.calls.find(([, body]) => !!body)!;
    expect(call[0]).toBe('/sessions/s/work-products/p1/shares/share1');
    expect(call[2]).toBe('POST');
    expect((call[1] as any).operation).toBe('work_products.shares.change');
  });
  it('requires explicit token-bound draft discard before removing work', async () => {
    const f = fixture();
    await f.client.refresh();
    const p = f.server.products[0];
    await f.client.keepDraft('p1', { ...draftOf(p), content: 'retain until explicit choice' });
    await expect(f.client.remove(p)).rejects.toThrow('草稿');
    await expect(f.client.discardDraft('p1', 'stale-token')).rejects.toThrow('新输入');
    expect(f.client.snapshot().journal.drafts.p1.content).toBe('retain until explicit choice');
    await f.client.discardDraft('p1', f.client.snapshot().journal.draftTokens.p1);
    expect(f.client.snapshot().journal.drafts.p1).toBeUndefined();
    expect(f.server.products[0].content).toBe('初稿');
  });
  it('retries one coherent read when independent list calls straddle a transaction', async () => {
    const f = fixture();
    let reads = 0;
    f.transport.mockImplementation(async (path, body: any) => {
      if (body) throw Error('not a write test');
      reads++;
      return {
        items: path.includes('work-items') ? [] : f.server.products,
        next_cursor: null,
        as_of: {
          business_seq: 7,
          workspace_revision: reads === 1 ? 1 : 2,
          storage_revision: reads === 1 ? 11 : 12,
        },
      };
    });
    await f.client.refresh();
    expect(reads).toBe(4);
    expect(f.client.snapshot().asOf?.workspace_revision).toBe(2);
  });
  it('uses existing v4 T() labels in native slot helpers', () => {
    setPreference('en');
    expect(purposeText('freeform')).toBe('Freeform work');
    expect(recipientText('tech_lead')).toBe('Technical lead');
    setPreference('zh');
    expect(purposeText('freeform')).toBe('自由作品');
    expect(recipientText('tech_lead')).toBe('技术负责人');
  });
});

describe('W03 selected legacy import', () => {
  const attempt = {
    id: 'old',
    token: 'DO-NOT-UPLOAD',
    tasks: [{ id: 't', title: '先试用', priority: 'first' }],
    artifacts: [
      {
        id: 'p',
        taskId: 't',
        title: '我的作品',
        kind: 'text',
        revision: 2,
        purpose: '自由作品',
        body: '正文',
        removedAt: 'yesterday',
        draft: { body: '未保存草稿' },
        authorization: 'secret',
      },
      { id: 'unselected', title: '不分享的私人作品', body: 'PRIVATE' },
    ],
    events: [
      {
        type: 'artifact_saved',
        detail: { artifactId: 'p', previous: { revision: 1, body: '旧正文' } },
      },
    ],
    pending: { path: '/actions' },
  };
  it('exports only explicit objects, preserving drafts/history/removal and stripping credentials', async () => {
    const before = structuredClone(attempt);
    const packet = await buildBrowserImport(
      attempt,
      { taskIds: ['t'], productIds: ['p'] },
      'package',
    );
    const text = JSON.stringify(packet);
    expect(text).not.toMatch(/DO-NOT-UPLOAD|secret|PRIVATE|\/actions/);
    expect(text).toContain('未保存草稿');
    expect(text).toContain('旧正文');
    expect(text).toContain('yesterday');
    expect(packet.package_hash).toBe(await hash(packet.items));
    expect(attempt).toEqual(before);
  });
  it('rejects missing selections, keeps schema hash deterministic and does not normalize away text', async () => {
    await expect(
      buildBrowserImport(attempt, { taskIds: [], productIds: [] }, 'p'),
    ).rejects.toThrow();
    await expect(
      buildBrowserImport(attempt, { taskIds: [], productIds: ['missing'] }, 'p'),
    ).rejects.toThrow();
    expect(canonical({ b: 1, a: '草稿' })).toBe('{"a":"草稿","b":1}');
    expect(await hash({ b: 1, a: 2 })).toBe(await hash({ a: 2, b: 1 }));
  });
  it('uses a stable package identity across repeated previews of the same selection', async () => {
    const one = await buildBrowserImport(attempt, {
      taskIds: ['t'],
      productIds: ['p', 'unselected'],
    });
    const two = await buildBrowserImport(attempt, {
      taskIds: ['t'],
      productIds: ['unselected', 'p'],
    });
    expect(one.package_id).toBe(two.package_id);
    expect(one.items).toEqual(two.items);
  });
  it('renders unresolved refs without claiming old tests ran in the current session', async () => {
    const input = await buildBrowserImport(attempt, { taskIds: [], productIds: ['p'] }, 'package');
    const preview: ImportResult = {
      package_id: 'package',
      mode: 'preview',
      id_map: {},
      as_of: { business_seq: 7, workspace_revision: 1, storage_revision: 11 },
      applied: false,
      unresolved: [
        { original_id: 'old-test', original_session_id: 'old', status: 'foreign_session' },
      ],
    };
    const apply = vi.fn();
    const html = renderToStaticMarkup(
      <ImportPreview input={input} preview={preview} onApply={apply} locale="en" />,
    );
    expect(html).toContain('old tests will not become runs');
    expect(html).toContain('old-test');
    expect(html).toContain('original browser copy stays intact');
    expect(apply).not.toHaveBeenCalled();
  });
  it('shows formal history gaps and blocks application of conflicting content', async () => {
    const input = await buildBrowserImport(attempt, { taskIds: [], productIds: ['p'] }, 'package');
    const preview: ImportResult = {
      package_id: 'package',
      mode: 'preview',
      id_map: {},
      as_of: { business_seq: 7, workspace_revision: 1, storage_revision: 11 },
      applied: false,
      unresolved: [],
      conflicts: [
        { original_id: 'p', reason: 'content_conflict' },
        { original_id: 'p', original_version: 2, reason: 'missing_history' },
      ],
      version_map: [
        {
          original_id: 'p',
          original_session_id: 'old',
          original_version: 2,
          target: null,
          status: 'unresolved',
        },
      ],
    };
    const html = renderToStaticMarkup(
      <ImportPreview input={input} preview={preview} onApply={() => {}} locale="en" />,
    );
    expect(html).toContain('Content conflict');
    expect(html).toContain('Historical version missing');
    expect(html).toContain('Missing; not reconstructed');
    expect(html).toMatch(/button[^>]*disabled/);
  });
});
