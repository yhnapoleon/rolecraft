import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { request, sessionPath } from './api';
import { blankPilot, WorkspaceStore } from './store';
import type {
  Deliverable,
  LocalSession,
  Material,
  Pilot,
  RoleId,
  Scenario,
  TestRun,
} from './types';

const store = new WorkspaceStore(localStorage);
const scenarios: Record<Scenario, string> = {
  pm_pilot: '知识助手试点',
  pm_pilot_urgent: '提前演示的试点',
  pm_pilot_capacity15: '15 人容量的试点',
};
const roles: { id: RoleId; name: string; initials: string; duty: string; boundary: string }[] = [
  {
    id: 'supervisor',
    name: '经理',
    initials: 'M',
    duty: '目标、范围与资源安排',
    boundary: '可见任务、技术和业务材料。聊天不会批准资源；申请须由场景规则审核。',
  },
  {
    id: 'tech_lead',
    name: '技术负责人',
    initials: 'T',
    duty: '索引、容量与实施成本',
    boundary:
      '可见技术约束与技术内部材料，无法读取业务负责人专属材料；工具只允许列出和读取获授权材料。',
  },
  {
    id: 'business_lead',
    name: '业务负责人',
    initials: 'B',
    duty: '知识需求、政策与验收',
    boundary:
      '可见业务材料和政策，技术资源的私有事实不在其视图中；工具只允许列出和读取获授权材料。',
  },
];
const labels: Record<keyof Deliverable, string> = {
  goal: '业务目标与用户范围',
  owner: '负责人',
  metrics: '成功指标',
  observation_window: '观察窗口',
  exit_condition: '退出条件',
  rationale: '方案、依据与取舍',
};
const fieldKeys = Object.keys(labels) as (keyof Deliverable)[];
const criterionNames: Record<string, string> = {
  'R1.target': '目标与用户范围',
  'R1.metrics': '成功指标',
  'R2.support': '事实与证据',
  'R2.unknowns': '未证实的结论',
  'R3.capacity': '人数与批准上限',
  'R3.resources': '资源和期限',
  'R4.functional_tests': '实际功能测试',
  'R4.staleness_test': '动态知识测试',
  'R5.impact': '变化的影响',
  'R5.adjustment': '方案与配置调整',
  'R6.consistency': '方案和配置一致性',
  'R6.operations': '观察与退出安排',
};
const feedbackLabels: Record<string, string> = {
  MET: '已满足',
  PARTIAL: '部分满足',
  NOT_MET: '未满足',
  INSUFFICIENT: '证据不足',
  NOT_APPLICABLE: '不适用',
};
const eventNames: Record<string, string> = {
  read_material: '记录材料阅读',
  update_pilot: '保存试点配置',
  test_assistant: '运行助手测试',
  policy_updated: '政策源文档更新',
  save_artifact: '保存交付稿',
  submit_plan: '固定提交',
  request_capacity: '申请扩容',
  request_resources: '申请资源或延期',
  approve_request: '场景批准',
  refresh_index: '刷新索引',
  pause: '暂停会话',
  resume: '恢复会话',
  record_turn: '保存角色回复',
};
const nav = [
  ['brief', '项目委托', '◈'],
  ['materials', '项目资料', '▤'],
  ['lab', '助手实验室', '↗'],
  ['config', '试点配置', '⚙'],
  ['deliver', '交付审阅', '▧'],
  ['feedback', '反馈与复盘', '↺'],
  ['history', '过程与存档', '▦'],
];
const modeLabel = (model: string) =>
  model.startsWith('local-')
    ? '本地事实模式 · 非大模型'
    : model.startsWith('scripted-')
      ? '测试替身 · 非真实模型'
      : model || '尚无回复';
const time = (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false });
const json = (v: unknown) => JSON.stringify(v, null, 2);

function Button({
  children,
  onClick,
  disabled,
  primary = false,
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  primary?: boolean;
  [key: string]: unknown;
}) {
  return (
    <button
      className={'btn ' + (primary ? 'primary' : '')}
      onClick={onClick}
      disabled={disabled}
      {...rest}
    >
      {children}
    </button>
  );
}
function Note({ children, warning = false }: { children: ReactNode; warning?: boolean }) {
  return <div className={'rc-note ' + (warning ? 'warning' : '')}>{children}</div>;
}
function Field({
  label,
  value,
  onChange,
  disabled,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  rows?: number;
}) {
  return (
    <label className="rc-field">
      <span>{label}</span>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={rows}
      />
    </label>
  );
}
function Dialog({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    const el = ref.current;
    return () => el?.close();
  }, []);
  return (
    <dialog ref={ref} className="rc-dialog" onCancel={close}>
      <header>
        <h2>{title}</h2>
        <Button onClick={close}>关闭</Button>
      </header>
      <div>{children}</div>
    </dialog>
  );
}
function Title({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="rc-title">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children && <p className="rc-lede">{children}</p>}
    </header>
  );
}

export function App() {
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const s = store.active();
  const readPane = () => location.hash.replace(/^#/, '') || 'hall';
  const [pane, setPane] = useState(readPane);
  const [menu, setMenu] = useState(false);
  const [selectedMaterial, setSelectedMaterial] = useState('brief');
  const [dialog, setDialog] = useState<{ title: string; content: ReactNode }>();
  const [scenario, setScenario] = useState<Scenario>('pm_pilot');
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const live = s && pane !== 'hall';
  const editable = store.canWrite(s);
  useEffect(() => {
    const listener = () => {
      setPane(readPane());
      setMenu(false);
    };
    addEventListener('hashchange', listener);
    void store.health();
    const poller = setInterval(() => {
      if (!document.hidden) void store.poll();
    }, 2000);
    return () => {
      removeEventListener('hashchange', listener);
      clearInterval(poller);
    };
  }, []);
  useEffect(() => {
    if (s) void store.sync(s.id);
  }, [s?.id]);
  useEffect(() => {
    document.body.dataset.screen = live ? 'workspace' : 'hall';
  }, [live]);
  function go(where: string) {
    location.hash = where;
    setPane(where);
    setMenu(false);
  }
  async function enter() {
    if (s) go('brief');
    else if (await store.create(scenario)) go('brief');
  }
  function patchInputs(patch: Partial<LocalSession['inputs']>) {
    if (s) store.update(s.id, { inputs: { ...s.inputs, ...patch } });
  }
  function modal(title: string, content: ReactNode) {
    setDialog({ title, content });
  }
  async function inspectEvidence(criterion: string, eid: string) {
    if (!s) return;
    setEvidenceBusy(true);
    try {
      const result = await request(
        sessionPath(
          s,
          '/evidence/' +
            store.submissionId(s) +
            '/' +
            encodeURIComponent(criterion) +
            '/' +
            encodeURIComponent(eid),
        ),
        undefined,
        s,
      );
      modal(
        '提交时的证据 · ' + eid,
        <pre className="rc-pre">
          {typeof result.content === 'string' ? result.content : json(result)}
        </pre>,
      );
    } catch (e) {
      modal('证据未能读取', <Note warning>{String(e)}</Note>);
    } finally {
      setEvidenceBusy(false);
    }
  }
  async function viewCitedMaterial(run: TestRun, materialId: string) {
    if (!s) return;
    try {
      const materials = (await request(
        sessionPath(s, '/materials?as_of_seq=' + run.as_of_seq),
        undefined,
        s,
      )) as Material[];
      const citation = run.citations.find((c) => c.material_id === materialId);
      const found = materials.find((m) => m.id === materialId && m.version === citation?.version);
      modal(
        '测试引用 · ' + materialId + ' v' + citation?.version,
        found ? (
          <pre className="rc-pre">{found.content}</pre>
        ) : (
          <Note warning>
            测试使用了旧索引版本。现有材料接口只返回该时点的有效源版本，不能取回这个旧索引片段；请保留测试原始回答和版本记录。
          </Note>
        ),
      );
    } catch (e) {
      modal('材料未能读取', <Note warning>{String(e)}</Note>);
    }
  }
  const status = (
    <span className={'rc-connection ' + (snap.connected ? 'ok' : '')}>
      {snap.connected ? 'API 已连接' : 'API 未连接'}
    </span>
  );
  const messages = (
    <>
      {snap.error && (
        <div role="alert" className="rc-message error">
          {snap.error}
          <button aria-label="关闭提示" onClick={() => store.clearMessage()}>
            ×
          </button>
        </div>
      )}
      {snap.notice && !snap.error && (
        <div role="status" className="rc-message">
          {snap.notice}
          <button aria-label="关闭提示" onClick={() => store.clearMessage()}>
            ×
          </button>
        </div>
      )}
    </>
  );

  if (!live)
    return (
      <div className="app is-hall rc-app">
        <div className="role-field" aria-hidden="true" />
        <main id="view">
          <div className="hall">
            <header className="hall-nav">
              <a href="#hall" className="hall-brand">
                PRACTICE<span> / AI WORK LAB</span>
              </a>
              <div className="hall-utility">
                {status}
                <a href="/demo/" className="rc-demo-link">
                  DEMO 原型 ↗
                </a>
              </div>
            </header>
            {messages}
            <section className="hall-hero">
              <img className="hall-image" src="/demo/assets/studio-entry.png" alt="" />
              <div className="hall-image-shade" />
              <div className="hall-copy">
                <p className="eyebrow">AI 职业任务训练场</p>
                <h1>
                  进入角色。
                  <br />
                  交出<span>你的判断。</span>
                </h1>
                <p className="hall-lede">
                  自由调查，亲手测试知识助手。
                  <br />
                  用实际记录，支持你的试点决定。
                </p>
              </div>
              <aside className="hall-brief">
                <span className="hall-brief-label">你的第一个项目 · 合成业务情境</span>
                <h2>
                  RoleCraft
                  <br />
                  <span>知识助手试点</span>
                </h2>
                <p>
                  经理希望开放第一批试点。
                  <br />
                  你来决定范围、证据和退出条件。
                </p>
                <div className="hall-team">
                  {roles.map((r) => (
                    <span key={r.id} className="mini-avatar">
                      {r.initials}
                    </span>
                  ))}
                  <span>三位同事 · 不同的信息边界</span>
                </div>
              </aside>
            </section>
            <section className="career-section">
              <div className="section-caption">
                <h2>选择你的职业</h2>
                <span>从调查，到可执行的交付</span>
              </div>
              <div className="career-grid">
                <article className="career-card live">
                  <div className="career-meta">
                    <span className="career-number">PRODUCT</span>
                    <span className="available">连接现有后端</span>
                  </div>
                  <h3>AI 产品经理</h3>
                  <p>
                    向同事求证，自己写测试与方案。
                    <br />
                    实际运行和反馈均来自 RoleCraft API。
                  </p>
                  <div className="career-detail">
                    <span>
                      {snap.model ? 'API 配置：' + modeLabel(snap.model) : '请先启动 API 与 worker'}
                    </span>
                  </div>
                  <div className="career-actions">
                    <button
                      className="career-enter"
                      onClick={() => void enter()}
                      disabled={snap.busy}
                    >
                      {s ? '继续工作台' : '进入工作台'}
                      <span>↗</span>
                    </button>
                    {!s && (
                      <label className="rc-hall-select">
                        任务情境
                        <select
                          aria-label="任务情境"
                          value={scenario}
                          onChange={(e) => setScenario(e.target.value as Scenario)}
                        >
                          {Object.entries(scenarios).map(([id, name]) => (
                            <option key={id} value={id}>
                              {name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {s && (
                      <button className="career-context" onClick={() => go('history')}>
                        查看已有练习 →
                      </button>
                    )}
                  </div>
                </article>
                <article className="career-card soon">
                  <div className="career-meta">
                    <span className="career-number">ENGINEERING</span>
                    <span className="coming">后续路径</span>
                  </div>
                  <h3>AI 应用工程师</h3>
                  <p>
                    工程实操与外部 Agent 接入尚未实现。
                    <br />
                    当前先完成产品经理的任务闭环。
                  </p>
                  <button disabled>尚未开放</button>
                </article>
              </div>
            </section>
            <section className="hall-practice">
              <div>
                <p className="eyebrow">这次，由你亲手完成</p>
                <h2>
                  先看见证据，
                  <br />
                  再作出决定。
                </h2>
                <p>保留你的提问、配置、测试和提交。</p>
              </div>
              <ol>
                <li>
                  <b>01</b>
                  <div>
                    <strong>调查与核对</strong>
                    <p>阅读后端材料，向角色提问，留意事件变化。</p>
                  </div>
                </li>
                <li>
                  <b>02</b>
                  <div>
                    <strong>配置与测试</strong>
                    <p>保存配置，自己写问题，比较真实返回及来源版本。</p>
                  </div>
                </li>
                <li>
                  <b>03</b>
                  <div>
                    <strong>提交与复盘</strong>
                    <p>固定作品，查看规则反馈和待核验项。</p>
                  </div>
                </li>
              </ol>
            </section>
            <footer className="hall-footer">
              <p>
                <b>连接版工作区</b> 模型能力按实际回复标记；当前不支持跨回合记忆及提交后修订。DEMO
                为独立演示数据。
              </p>
              <button className="career-context" onClick={() => void store.health()}>
                重新检查连接
              </button>
            </footer>
          </div>
        </main>
      </div>
    );

  const title = pane.startsWith('role:')
    ? '团队沟通'
    : nav.find((n) => n[0] === pane)?.[1] || '项目委托';
  const pending = s.pending;
  const world = s.world;
  const pilot = s.configDraft ||
    world.configs.pilot || { ...blankPilot(), launch_day: world.resources.deadline_day };
  const localDraftChanged =
    s.artifact && JSON.stringify(s.artifact.content) !== JSON.stringify(s.draft);
  const submissionId = store.submissionId(s);
  const currentMaterial = s.materials.find((m) => m.id === selectedMaterial) || s.materials[0];
  const role = roles.find((r) => pane === 'role:' + r.id);
  const updatePilot = (patch: Partial<Pilot>) =>
    store.update(s.id, { configDraft: { ...pilot, ...patch } });
  const saveConfig = () => void store.action('update_pilot', { plan: pilot });
  const quote = (text: string) => {
    store.update(s.id, {
      draft: { ...s.draft, rationale: s.draft.rationale + (s.draft.rationale ? '\n' : '') + text },
    });
    go('deliver');
  };
  const pendingStrip = pending && (
    <div className="rc-job" role="status">
      <div>
        <strong>{pending.label}</strong>
        <span>
          {pending.jobId
            ? (pending.job?.status === 'running' ? '执行中' : '等待 worker') +
              ' · 尝试 ' +
              (pending.job?.attempt || 0) +
              '/3'
            : '写入结果待确认'}
        </span>
        <small>
          {pending.jobId
            ? '恢复页面后继续查询同一任务；等待时暂不追加业务操作。'
            : '原请求及幂等键已保留，不会自动另发一份。'}
        </small>
      </div>
      <Button disabled={snap.busy} onClick={() => void store.execute()}>
        {pending.jobId ? '检查任务状态' : '重试原请求'}
      </Button>
    </div>
  );
  return (
    <div className={'app studio rc-app ' + (menu ? 'rc-menu-open' : '')}>
      <aside className="studio-rail" aria-label="项目导航">
        <button className="studio-logo" onClick={() => go('hall')}>
          P
          <span>
            PRACTICE<small>WORKSPACE</small>
          </span>
        </button>
        <div className="project-id">
          <span className="project-monogram">R</span>
          <span>
            RoleCraft<small>{scenarios[s.scenario]}</small>
          </span>
        </div>
        <nav className="rail-main">
          {nav.slice(0, 2).map(([key, name, icon]) => (
            <button
              className={'rail-link ' + (pane === key ? 'selected' : '')}
              key={key}
              onClick={() => go(key)}
            >
              <span className="rail-glyph">{icon}</span>
              {name}
            </button>
          ))}
          <div className="rail-section">
            <h4>团队沟通</h4>
            {roles.map((r) => (
              <button
                className={'rail-link ' + (role?.id === r.id ? 'selected' : '')}
                key={r.id}
                onClick={() => go('role:' + r.id)}
              >
                <span className="mini-avatar">{r.initials}</span>
                {r.name}
              </button>
            ))}
          </div>
          <div className="rail-divider" />
          {nav.slice(2).map(([key, name, icon]) => (
            <button
              className={'rail-link ' + (pane === key ? 'selected' : '')}
              key={key}
              onClick={() => go(key)}
            >
              <span className="rail-glyph">{icon}</span>
              {name}
            </button>
          ))}
        </nav>
        <div className="rail-footer">
          <span className="your-avatar">YOU</span>
          <span>
            你的岗位<small>AI 产品经理</small>
          </span>
        </div>
      </aside>
      <header className="studio-top">
        <div className="studio-breadcrumb">
          <button
            className="mobile-menu btn"
            aria-label="切换项目导航"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            ☰
          </button>
          <span>RoleCraft</span>
          <i>/</i>
          <strong>{title}</strong>
        </div>
        <div className="studio-status">
          {status}
          <button
            className="rc-text-button"
            disabled={snap.busy}
            onClick={() => {
              void store.health();
              void store.sync();
            }}
          >
            刷新
          </button>
        </div>
      </header>
      <div className="studio-boundary">
        <span>
          连接版 · 数据来自后端 · 会话{' '}
          {world.status === 'submitted'
            ? '已提交'
            : world.status === 'paused'
              ? '已暂停'
              : '进行中'}{' '}
          · 状态 v{world.version}
        </span>
        <a href="/demo/">DEMO 原型 ↗</a>
      </div>
      <main className="view rc-view" id="view">
        {messages}
        {pendingStrip}
        {world.status === 'submitted' && (
          <Note>
            作品已固定。现有后端不支持提交后修订；可回看证据，或新建独立练习。新练习不会被标记为原作品的修订。
          </Note>
        )}
        {world.status === 'paused' && (
          <Note warning>
            会话已暂停。
            <Button
              disabled={snap.busy || !!pending}
              onClick={() => void store.action('resume', {})}
            >
              恢复会话
            </Button>
          </Note>
        )}
        {pane === 'brief' && (
          <div className="rc-page">
            <Title eyebrow="你的岗位 · AI 产品经理" title="把试点，变成有依据的决定。">
              调查业务需求与技术约束，测试助手，再说明你愿意承诺什么。
            </Title>
            <div className="rc-split">
              <section>
                <div className="rc-commission">
                  <span className="mini-avatar">M</span>
                  <div>
                    <small>经理的委托 · 后端当前材料</small>
                    <pre>
                      {s.materials.find((m) => m.id === 'brief')?.content ||
                        '材料尚未读取，请刷新连接。'}
                    </pre>
                  </div>
                </div>
                <div className="rc-actions">
                  <Button primary onClick={() => go('materials')}>
                    打开项目资料 ↗
                  </Button>
                  <Button onClick={() => go('role:supervisor')}>向经理提问</Button>
                </div>
                <Note>由你决定调查顺序、测试问题和方案。系统不会替你填写正确答案。</Note>
              </section>
              <aside className="rc-dossier">
                <p className="eyebrow">任务状态</p>
                <h2>{scenarios[s.scenario]}</h2>
                <dl>
                  <div>
                    <dt>当前容量</dt>
                    <dd>{world.resources.capacity} 人</dd>
                  </div>
                  <div>
                    <dt>开发资源</dt>
                    <dd>{world.resources.dev_days} 人日</dd>
                  </div>
                  <div>
                    <dt>期限</dt>
                    <dd>第 {world.resources.deadline_day} 天</dd>
                  </div>
                  <div>
                    <dt>已保存配置</dt>
                    <dd>{world.config_version ? 'v' + world.config_version : '尚未配置'}</dd>
                  </div>
                </dl>
                <p>这些是当前后端场景状态。申请或聊天承诺不会自动改变额度。</p>
              </aside>
            </div>
            <div className="rc-paths">
              {[
                ['lab', '自己测试', '写一个问题，检查实际返回。'],
                ['deliver', '整理交付', '配置与六段文字分别保存。'],
                ['history', '查看过程', '查看已保存事件与浏览器草稿。'],
              ].map(([key, name, desc]) => (
                <button key={key} onClick={() => go(key)}>
                  <strong>{name} ↗</strong>
                  <span>{desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {pane === 'materials' && (
          <div className="rc-page">
            <Title eyebrow="调查 · 原始材料" title="先读事实，再问问题。">
              材料由后端按学员权限返回。技术角色的私有材料不会出现在这里。
            </Title>
            <div className="rc-materials">
              <nav aria-label="材料列表">
                {s.materials.map((m) => (
                  <button
                    key={m.id}
                    className={currentMaterial?.id === m.id ? 'active' : ''}
                    onClick={() => setSelectedMaterial(m.id)}
                  >
                    <span>{m.title}</span>
                    <small>
                      {m.id} · v{m.version}
                    </small>
                  </button>
                ))}
              </nav>
              {currentMaterial && (
                <article className="rc-document">
                  <header>
                    <h2>{currentMaterial.title}</h2>
                    <span>
                      {currentMaterial.id} · 源 v{currentMaterial.version} / 索引 v
                      {world.indexed_versions[currentMaterial.id]}
                    </span>
                  </header>
                  <pre>{currentMaterial.content}</pre>
                  <div className="rc-actions">
                    <Button
                      disabled={!editable}
                      onClick={() =>
                        void store.action('read_material', { material_id: currentMaterial.id })
                      }
                    >
                      记录本次阅读
                    </Button>
                    <Button
                      disabled={!editable}
                      onClick={() =>
                        quote('材料引用：' + currentMaterial.id + ' v' + currentMaterial.version)
                      }
                    >
                      引用到方案依据
                    </Button>
                  </div>
                  <small>
                    查看列表不会推进场景；“记录本次阅读”是后端业务动作，可能触发场景事件。
                  </small>
                </article>
              )}
            </div>
          </div>
        )}
        {role && (
          <div className="rc-page rc-conversation">
            <Title eyebrow="团队沟通" title={role.name}>
              {role.duty}
            </Title>
            <Note>{role.boundary}</Note>
            <p className="rc-muted">
              每个回合独立读取当前可见事实；后端尚未把历史对话加入下一轮上下文。追问时请自己补充背景。回复下方标注实际使用的模式。
            </p>
            <div className="rc-thread" aria-live="polite">
              {s.timeline.turns
                .filter((t) => t.role_id === role.id)
                .map((t) => (
                  <article key={t.trace_id}>
                    <div className="rc-user-message">
                      <small>你的提问</small>
                      <p>
                        {s.questions[t.trace_id] ||
                          '该回合提问未保存在此浏览器，现有回放接口仅返回角色结果。'}
                      </p>
                    </div>
                    <div className="rc-colleague-message">
                      <span className="mini-avatar">{role.initials}</span>
                      <div>
                        <small>
                          {role.name} · {modeLabel(t.model_revision)} · 状态 v{t.as_of_seq}
                        </small>
                        <p>{t.text}</p>
                        {t.status !== 'completed' && (
                          <Note warning>回合状态：{t.status}。未完成的操作不能视为已执行。</Note>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              {!s.timeline.turns.some((t) => t.role_id === role.id) && (
                <div className="rc-empty">
                  <h2>从你需要确认的事开始。</h2>
                  <p>自由提问。模型回复不能代替材料、批准记录或你的判断。</p>
                </div>
              )}
            </div>
            <form
              className="rc-composer"
              onSubmit={(e) => {
                e.preventDefault();
                const text = s.inputs.messages[role.id]?.trim();
                if (text) void store.sendTurn(role.id, text);
              }}
            >
              <label>
                <span>向{role.name}提问</span>
                <textarea
                  aria-label={'向' + role.name + '提问'}
                  maxLength={4000}
                  value={s.inputs.messages[role.id] || ''}
                  onChange={(e) =>
                    patchInputs({ messages: { ...s.inputs.messages, [role.id]: e.target.value } })
                  }
                  disabled={world.status !== 'active'}
                  rows={4}
                />
              </label>
              <div>
                <small>API 配置：{modeLabel(snap.model)}；以每次 worker 回复的标记为准。</small>
                <button
                  className="btn primary"
                  disabled={!editable || !s.inputs.messages[role.id]?.trim()}
                >
                  发送问题 ↗
                </button>
              </div>
            </form>
            {s.failedTurn?.body.role_id === role.id && (
              <Note warning>
                上次任务已终态失败，原问题仍保留。
                <Button
                  disabled={!editable}
                  onClick={() => void store.sendTurn(role.id, String(s.failedTurn!.body.text))}
                >
                  以原问题新建回合
                </Button>
              </Note>
            )}
          </div>
        )}
        {pane === 'config' && (
          <div className="rc-page">
            <Title eyebrow="试点配置" title="明确你愿意开放的边界。">
              草稿不会影响测试。保存为新版本后，后续测试才使用该配置。
            </Title>
            <Note>
              后端支持两类知识域、三种更新策略和两种兜底。原型的“日期提醒”开关没有对应接口，本页不模拟它已生效。
            </Note>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                saveConfig();
              }}
            >
              <fieldset disabled={!editable} className="rc-config">
                <section>
                  <div>
                    <h2>人群与时间</h2>
                    <p>可以保存不可行的方案，再依据运行和规则反馈判断；填写不是批准。</p>
                  </div>
                  <div className="rc-field-grid">
                    <label className="rc-field">
                      <span>试点人数</span>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        required
                        value={pilot.participants}
                        onChange={(e) => updatePilot({ participants: Number(e.target.value) })}
                      />
                    </label>
                    <label className="rc-field">
                      <span>上线日（第几天）</span>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        required
                        value={pilot.launch_day}
                        onChange={(e) => updatePilot({ launch_day: Number(e.target.value) })}
                      />
                    </label>
                  </div>
                </section>
                <section>
                  <div>
                    <h2>知识范围</h2>
                    <p>这些选项配置被测试的应用，不是答题选项。</p>
                  </div>
                  <div>
                    {[
                      ['stable_faq', '稳定办公 FAQ'],
                      ['policy', '差旅政策'],
                    ].map(([id, name]) => (
                      <label className="rc-check" key={id}>
                        <input
                          type="checkbox"
                          checked={pilot.knowledge_domains.includes(id)}
                          onChange={(e) =>
                            updatePilot({
                              knowledge_domains: toggle(
                                pilot.knowledge_domains,
                                id,
                                e.target.checked,
                              ),
                            })
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </div>
                </section>
                <section>
                  <div>
                    <h2>更新与兜底</h2>
                    <p>源版本和索引版本独立。选择实时同步并不自动获得资源。</p>
                  </div>
                  <div className="rc-field-grid">
                    <label className="rc-field">
                      <span>更新策略</span>
                      <select
                        value={pilot.update_strategy}
                        onChange={(e) =>
                          updatePilot({
                            update_strategy: e.target.value as Pilot['update_strategy'],
                          })
                        }
                      >
                        <option value="daily">每日索引</option>
                        <option value="realtime">实时同步</option>
                        <option value="manual_policy">政策转人工</option>
                      </select>
                    </label>
                    <label className="rc-field">
                      <span>兜底安排</span>
                      <select
                        value={pilot.fallback}
                        onChange={(e) =>
                          updatePilot({ fallback: e.target.value as Pilot['fallback'] })
                        }
                      >
                        <option value="none">未安排人工</option>
                        <option value="human">人工兜底</option>
                      </select>
                    </label>
                  </div>
                </section>
                <section>
                  <div>
                    <h2>实施工作项</h2>
                    <p>资源成本按现有场景规则核对。</p>
                  </div>
                  <div>
                    {[
                      ['scope_filter', '范围过滤 · 1 人日'],
                      ['human_fallback', '人工入口 · 1 人日'],
                      ['realtime_sync', '实时同步 · 5 人日'],
                    ].map(([id, name]) => (
                      <label className="rc-check" key={id}>
                        <input
                          type="checkbox"
                          checked={pilot.work_items.includes(id)}
                          onChange={(e) =>
                            updatePilot({
                              work_items: toggle(pilot.work_items, id, e.target.checked),
                            })
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </div>
                </section>
                <footer className="rc-actions">
                  <button className="btn primary">保存为新配置版本</button>
                  <span>
                    {s.configDraft
                      ? '有未应用的本地草稿'
                      : world.config_version
                        ? '当前配置 v' + world.config_version
                        : '尚未保存配置'}
                  </span>
                </footer>
              </fieldset>
            </form>
            <div className="rc-section">
              <h2>索引与资源申请</h2>
              <p className="rc-muted">
                刷新索引会实际改变当前索引版本；请求资源后仍须按场景规则审核。AI 聊天不能代替批准。
              </p>
              <Button disabled={!editable} onClick={() => void store.action('refresh_index', {})}>
                刷新当前索引
              </Button>
              <div className="rc-field-grid">
                {[
                  ['capacityReason', 'request_capacity', 'capacity_approved', '扩容申请理由'],
                  [
                    'resourceReason',
                    'request_resources',
                    'resources_approved',
                    '资源或延期申请理由',
                  ],
                ].map(([field, tool, rule, label]) => (
                  <section key={tool}>
                    <Field
                      label={label}
                      value={s.inputs[field as 'capacityReason' | 'resourceReason']}
                      onChange={(value) => patchInputs({ [field]: value })}
                      disabled={world.status !== 'active'}
                    />
                    <div className="rc-actions">
                      <Button
                        disabled={
                          !editable ||
                          !s.inputs[field as 'capacityReason' | 'resourceReason'].trim() ||
                          world.applied_rules.includes(rule)
                        }
                        onClick={() =>
                          void store.action(tool, {
                            reason: s.inputs[field as 'capacityReason' | 'resourceReason'],
                          })
                        }
                      >
                        提交申请
                      </Button>
                      {world.pending_requests.includes(rule) && (
                        <Button disabled={!editable} onClick={() => void store.approval(rule)}>
                          按场景规则审核
                        </Button>
                      )}
                    </div>
                    {world.applied_rules.includes(rule) && (
                      <p className="rc-muted">该项已由场景规则批准。</p>
                    )}
                  </section>
                ))}
              </div>
            </div>
          </div>
        )}
        {pane === 'lab' && (
          <div className="rc-page">
            <Title eyebrow="助手实验室" title="让实际回答，检验你的预期。">
              自由写问题，查看检索来源、索引版本与兜底。预期和诊断是你的本地笔记，不会冒充后端评分。
            </Title>
            <div className="rc-lab-status">
              <span>配置 {world.config_version ? 'v' + world.config_version : '未设置'}</span>
              <span>
                政策源 v{world.material_versions.policy} / 索引 v{world.indexed_versions.policy}
              </span>
              <button onClick={() => go('config')}>查看配置 ↗</button>
            </div>
            {s.configDraft && (
              <Note warning>配置草稿尚未应用。此处测试使用已保存的 v{world.config_version}。</Note>
            )}
            <form
              className="rc-test-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (s.inputs.question.trim()) void store.test(s.inputs.question.trim());
              }}
            >
              <Field
                label="你想测试的问题"
                value={s.inputs.question}
                onChange={(question) => patchInputs({ question })}
                disabled={world.status !== 'active'}
              />
              <Field
                label="你的预期（可选，不妨碍自由探索）"
                value={s.inputs.expected}
                onChange={(expected) => patchInputs({ expected })}
                disabled={world.status !== 'active'}
                rows={2}
              />
              <div className="rc-actions">
                <button
                  className="btn primary"
                  disabled={
                    !editable ||
                    !world.config_version ||
                    !s.inputs.question.trim() ||
                    s.inputs.question.length > 4000
                  }
                >
                  运行测试 ↗
                </button>
                {!world.config_version && (
                  <Button onClick={() => go('config')}>先保存试点配置</Button>
                )}
              </div>
            </form>
            <Note>
              当前后端助手采用 BM25 检索后提取原文。角色 LLM
              的配置不会自动让这个助手变成生成式模型；页面呈现原始结果。
            </Note>
            <div className="rc-results">
              {[...s.tests].reverse().map((r, index) => {
                const previous = s.tests
                  .filter((t) => t.query === r.query && t.id !== r.id && t.as_of_seq < r.as_of_seq)
                  .at(-1);
                const notes = s.testNotes[r.id] || { expected: '', diagnosis: '' };
                return (
                  <article className="rc-run" key={r.id}>
                    <header>
                      <span>
                        RUN {s.tests.length - index} · cfg v{r.config_version} · 状态 v{r.as_of_seq}
                      </span>
                      <b>{r.fallback ? '转人工' : r.stale ? '使用旧索引' : '返回检索内容'}</b>
                    </header>
                    <h3>{r.query}</h3>
                    {notes.expected && <p className="rc-muted">我的预期：{notes.expected}</p>}
                    <p className="rc-answer">{r.answer}</p>
                    <div className="rc-citations">
                      {r.citations.map((c) => (
                        <button
                          key={c.material_id}
                          onClick={() => void viewCitedMaterial(r, c.material_id)}
                        >
                          {c.material_id} · v{c.version} ↗
                        </button>
                      ))}
                      <small>{r.mode}</small>
                    </div>
                    <details>
                      <summary>原始运行与版本记录</summary>
                      <pre className="rc-pre">{json(r)}</pre>
                    </details>
                    {previous && (
                      <details>
                        <summary>
                          比较上一次同题 · cfg v{previous.config_version} → v{r.config_version}
                        </summary>
                        <div className="rc-comparison">
                          <div>
                            <small>上一次</small>
                            <p>{previous.answer}</p>
                            <span>
                              源 {json(previous.source_versions)} / 索引{' '}
                              {json(previous.indexed_versions)}
                            </span>
                          </div>
                          <div>
                            <small>本次</small>
                            <p>{r.answer}</p>
                            <span>
                              源 {json(r.source_versions)} / 索引 {json(r.indexed_versions)}
                            </span>
                          </div>
                        </div>
                      </details>
                    )}
                    <Field
                      label="我的诊断与后续判断（本地笔记）"
                      value={notes.diagnosis}
                      onChange={(diagnosis) =>
                        store.update(s.id, {
                          testNotes: { ...s.testNotes, [r.id]: { ...notes, diagnosis } },
                        })
                      }
                      disabled={world.status !== 'active'}
                      rows={2}
                    />
                    <div className="rc-actions">
                      <Button
                        disabled={!editable || !world.config_version}
                        onClick={() => {
                          patchInputs({ question: r.query, expected: notes.expected });
                          void store.test(r.query);
                        }}
                      >
                        用当前配置重测此题
                      </Button>
                      <Button
                        disabled={!editable}
                        onClick={() =>
                          quote(
                            '测试引用：' +
                              r.id +
                              '，配置 v' +
                              r.config_version +
                              '，问题：' +
                              r.query,
                          )
                        }
                      >
                        引用到方案依据
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
            {!s.tests.length && (
              <div className="rc-empty">
                <h2>测试由你提出。</h2>
                <p>这里会保留后端实际返回的结果。不会生成模拟的通过标记。</p>
              </div>
            )}
          </div>
        )}
        {pane === 'deliver' && (
          <div className="rc-page">
            <Title eyebrow="交付审阅" title="把你的决定，写清楚。">
              当前接口保存试点配置和六段交付文字。原型九字段没有逐项对应的评分接口，引用文字也不等于已证明成立。
            </Title>
            <div className="rc-delivery-context">
              <strong>
                提交配置：{world.config_version ? 'v' + world.config_version : '尚未配置'}
              </strong>
              {world.configs.pilot && (
                <div className="rc-config-summary">
                  <p>
                    {world.configs.pilot.participants} 人 · 第 {world.configs.pilot.launch_day}{' '}
                    天上线 ·{' '}
                    {world.configs.pilot.knowledge_domains
                      .map((d) => (d === 'stable_faq' ? '稳定 FAQ' : '差旅政策'))
                      .join('、') || '未选知识范围'}
                  </p>
                  <p>
                    更新：
                    {
                      { daily: '每日索引', realtime: '实时同步', manual_policy: '政策转人工' }[
                        world.configs.pilot.update_strategy
                      ]
                    }{' '}
                    · 兜底：{world.configs.pilot.fallback === 'human' ? '人工' : '未安排人工'}
                  </p>
                  <details>
                    <summary>展开后端配置原文</summary>
                    <pre>{json(world.configs.pilot)}</pre>
                  </details>
                </div>
              )}
              <Button onClick={() => go('config')}>核对配置</Button>
            </div>
            {s.configDraft && <Note warning>有未应用的配置草稿；提交采用上方已保存版本。</Note>}
            <div className="rc-draft">
              {fieldKeys.map((key) => (
                <Field
                  key={key}
                  label={labels[key]}
                  value={s.draft[key]}
                  onChange={(value) => store.update(s.id, { draft: { ...s.draft, [key]: value } })}
                  disabled={!editable}
                  rows={key === 'rationale' ? 7 : 3}
                />
              ))}
            </div>
            <div className="rc-actions">
              <Button
                primary
                disabled={!editable || !world.config_version}
                onClick={() => void store.saveArtifact()}
              >
                保存交付稿到后端
              </Button>
              <Button
                disabled={
                  !editable ||
                  !s.artifact ||
                  !!localDraftChanged ||
                  s.artifact.config_version !== world.config_version
                }
                onClick={() => setConfirmSubmit(true)}
              >
                审阅并提交
              </Button>
            </div>
            <p className="rc-muted">
              {s.artifact
                ? '已保存作品 v' +
                  s.artifact.version +
                  ' · 配置 v' +
                  s.artifact.config_version +
                  (localDraftChanged ? ' · 当前文字尚未重新保存' : '')
                : '尚无后端作品。编辑内容先保存在此浏览器。'}{' '}
              空字段按后端规则允许提交，可能得到缺失内容反馈。
            </p>
          </div>
        )}
        {pane === 'feedback' && (
          <div className="rc-page">
            <Title eyebrow="反馈与复盘" title="对照证据，理解这次交付。">
              当前是规则反馈。语义判断未完成的项目保留待核验，不推断你的广泛职业能力。
            </Title>
            {!submissionId ? (
              <div className="rc-empty">
                <h2>还没有固定提交。</h2>
                <Button onClick={() => go('deliver')}>打开交付稿</Button>
              </div>
            ) : !s.feedback ? (
              <div className="rc-empty">
                <h2>提交已保存，反馈单独生成。</h2>
                <p>需要独立 worker 执行任务；排队不代表已得到评价。</p>
                <Button
                  primary
                  disabled={snap.busy || !!pending || !!s.feedbackFailure}
                  onClick={() => void store.feedback()}
                >
                  请求后端反馈
                </Button>
                {s.feedbackFailure && (
                  <Note warning>
                    反馈任务已终态失败（{s.feedbackFailure.error}
                    ）。现有接口不支持重置该任务；提交仍保留，需要后端维护者处理。
                  </Note>
                )}
              </div>
            ) : (
              <>
                <div className="rc-feedback-summary">
                  <div>
                    <small>当前可确定的分数区间</small>
                    <strong>
                      {s.feedback.summary.lower === null
                        ? '待核验'
                        : Math.round(s.feedback.summary.lower * 100) +
                          '–' +
                          Math.round((s.feedback.summary.upper || 0) * 100)}
                    </strong>
                    <span>区间不是最终评分</span>
                  </div>
                  <p>
                    规则版本 {s.feedback.model_revision}
                    <br />
                    确定项覆盖 {Math.round(s.feedback.summary.coverage * 100)}%<br />
                    提交证据时点 v{s.feedback.as_of_seq}
                    <br />
                    状态：
                    {{ pending_review: '待核验', scored: '规则已汇总', unscorable: '暂不可评分' }[
                      s.feedback.summary.status
                    ] || s.feedback.summary.status}
                  </p>
                </div>
                {s.feedback.items.map((item) => (
                  <article className="rc-feedback-item" key={item.criterion_id}>
                    <header>
                      <h2>{criterionNames[item.criterion_id] || item.criterion_id}</h2>
                      <span className={'rc-label ' + (item.label === 'NOT_MET' ? 'warning' : '')}>
                        {feedbackLabels[item.label] || item.label}
                        {item.review_required ? ' · 待核验' : ''}
                      </span>
                    </header>
                    <p>{item.reason}</p>
                    <details>
                      <summary>查看 {item.evidence_ids.length} 项证据</summary>
                      <div className="rc-citations">
                        {item.evidence_ids.map((eid) => (
                          <button
                            disabled={evidenceBusy}
                            key={eid}
                            onClick={() => void inspectEvidence(item.criterion_id, eid)}
                          >
                            证据 {eid} ↗
                          </button>
                        ))}
                      </div>
                    </details>
                  </article>
                ))}
                {s.feedback.practice.length > 0 && (
                  <section className="rc-section">
                    <h2>后端给出的补练方向</h2>
                    <ul>
                      {s.feedback.practice.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                    <p>这些是规则建议，目前没有自动建立关联补练或修订的接口。</p>
                    <Button onClick={() => go('history')}>新建独立练习</Button>
                  </section>
                )}
              </>
            )}
          </div>
        )}
        {pane === 'history' && (
          <div className="rc-page">
            <Title eyebrow="过程与存档" title="每一步，都有来处。">
              状态、角色结果和事件从后端恢复。测试详情、提问原文与未保存草稿还依赖此浏览器；现有 API
              没有完整存档列表接口。
            </Title>
            <div className="rc-section">
              <h2>本浏览器中的练习</h2>
              {snap.workspace.sessions.map((item) => (
                <button
                  className={'rc-session ' + (s.id === item.id ? 'active' : '')}
                  key={item.id}
                  disabled={snap.busy}
                  onClick={() => {
                    store.select(item.id);
                    go('brief');
                  }}
                >
                  <span>
                    <strong>{scenarios[item.scenario]}</strong>
                    <small>
                      {time(item.created)} · {item.id.slice(0, 12)}
                    </small>
                  </span>
                  <span>{item.world.status}</span>
                </button>
              ))}
              <div className="rc-actions">
                <label className="rc-field">
                  <span>新练习情境</span>
                  <select
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value as Scenario)}
                  >
                    {Object.entries(scenarios).map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  disabled={snap.busy || !!pending}
                  onClick={async () => {
                    if (await store.create(scenario)) go('brief');
                  }}
                >
                  新建独立练习
                </Button>
              </div>
            </div>
            <div className="rc-section">
              <h2>当前会话</h2>
              <p className="rc-muted rc-break">
                {s.id} · 状态 v{world.version} ·{' '}
                {snap.storageError ? '浏览器保存失败' : '浏览器草稿已保存'}
              </p>
              <div className="rc-actions">
                <Button disabled={!editable} onClick={() => void store.action('pause', {})}>
                  暂停会话
                </Button>
                <Button
                  onClick={() =>
                    modal(
                      '当前恢复边界',
                      <Note>
                        此浏览器保存会话
                        token、提问、草稿及返回的测试详情。后端保存权威状态和作品；目前没有账号、会话列表和完整作品读取接口。清理浏览器数据会丢失这些恢复入口。请勿把
                        token 发给他人。
                      </Note>,
                    )
                  }
                >
                  了解恢复边界
                </Button>
              </div>
            </div>
            <section className="rc-section">
              <h2>已保存的事件</h2>
              <p className="rc-muted">回放只读，不重新调用模型，不追加业务操作。</p>
              <ol className="rc-timeline">
                {[...s.timeline.events].reverse().map((e) => (
                  <li key={e.seq}>
                    <span className="rc-seq">v{e.seq}</span>
                    <div>
                      <strong>{eventNames[e.event_type] || e.event_type}</strong>
                      <small>{e.actor_id}</small>
                      <details>
                        <summary>查看事件内容</summary>
                        <pre className="rc-pre">{json(e.payload)}</pre>
                      </details>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </div>
        )}
      </main>
      {dialog && (
        <Dialog title={dialog.title} close={() => setDialog(undefined)}>
          {dialog.content}
        </Dialog>
      )}
      {confirmSubmit && (
        <Dialog title="固定提交这份作品" close={() => setConfirmSubmit(false)}>
          <Note warning>
            提交后，现有后端将锁定本会话，不能继续对话、测试或修订。反馈仍可生成并回看。
          </Note>
          <p>
            作品 v{s.artifact?.version} · 配置 v{world.config_version}。请确认这是你准备交付的版本。
          </p>
          <div className="rc-actions">
            <Button
              primary
              disabled={!editable}
              onClick={() => {
                setConfirmSubmit(false);
                void store.submit();
                go('feedback');
              }}
            >
              确认固定提交
            </Button>
            <Button onClick={() => setConfirmSubmit(false)}>返回检查</Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
function toggle(items: string[], id: string, checked: boolean) {
  return checked ? [...new Set([...items, id])] : items.filter((x) => x !== id);
}
