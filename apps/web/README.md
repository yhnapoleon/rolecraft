# RoleCraft 工作区前端

2026-10-05：高仿真 HTML 工作台现已连接现有 RoleCraft API。页面沿用岗位选择、事项、作品、测试和侧栏的布局；会话、材料、三位同事、配置、审批、测试、固定交付、反馈与证据由后端提供。断线不会切换为模拟答案。

自由事项、笔记、优先级、作品版本和 Agent 文件导入仍是本地工作记录。正式交付时，可将已采用的作品合并到后端六字段成果中的方案与依据；草稿编辑不自动提交。后端尚无开放作品同步、跨回合角色记忆、提交后关联修订或 MCP 接口。

## 启动

需要 Node.js >= 22.12、npm，以及按仓库 `uv.lock` 安装的 Python 环境。在仓库根目录完成 `uv sync --locked`，分别启动 API 与 worker；两个进程必须使用同一数据库：

```sh
uv run career-lab serve --host 127.0.0.1 --port 8502 --database-url sqlite:////tmp/rolecraft-web-preview.db --provider local
```

```sh
uv run career-lab worker --database-url sqlite:////tmp/rolecraft-web-preview.db --provider local
```

启动前端：

```sh
cd apps/web
npm ci
npm run build
npm run preview -- --port 8510
```

打开 <http://127.0.0.1:8510/>。开发使用 `npm run dev`，地址为 <http://127.0.0.1:5173/>。Vite 开发与预览将 `/api/*` 转发至 `http://127.0.0.1:8502/*`，可用 `ROLECRAFT_API_TARGET` 指定其他 API 地址。正式托管仍需配置同源 `/api` 转发。

`local` 是后端抽取模式，不调用外部大模型。API 与 worker 的 provider、数据库配置需一致；前端不接收模型密钥。真实模型按仓库已有 CLI 配置，本轮没有新增外部模型调用。

## 三个入口与存档

| 地址 | 当前用途 | 状态来源 |
|---|---|---|
| `/` | 高仿真界面的真实连接版，产品主入口 | `rolecraft.live.workspace.v1` 保存会话凭据与请求日志；`rolecraft.open-work.ui.v1` 保存事项与笔记 |
| `/connected/` | 保留的原 React API 连接页 | 与新主入口使用同一 API 会话存档，可读取相同服务端状态 |
| `/demo/` | 明确标记的离线规则演示 | `practice.open-work.v2`，与连接版隔离，不作为网络失败时的后备结果 |

旧高仿真演示的浏览器存档保留在 `/demo/`，不会自动转换成服务端记录。存档按域名、端口隔离；不同地址的记录不会自动迁移。没有账户登录、跨设备同步或服务端会话列表。不要分享 `rolecraft.live.workspace.v1`：其中包含 bearer token。任务包和本地笔记导出均不包含会话 token。

## 接口覆盖

以下涵盖现有后端全部 16 个 HTTP 操作：15 个核心操作已在本机成功调用；可选辅助判断验证了未配置时的 503 分支。页面里的场景条件来自现有后端，提前上线变体为第 **5** 天；离线原型保留自己的第 3 天设定。

| 操作 | 新界面入口与适配 | 本轮证据 |
|---|---|---|
| `GET /health` | 顶部连接状态、运行模式、刷新 | 浏览器与真实 HTTP |
| `POST /sessions` | 选岗后接手工作；主场景、提前上线、15 人容量 | 三个场景创建成功；存储异常时阻止创建 |
| `GET /sessions/{id}` | 恢复会话、刷新、每次业务动作后的权威状态 | 刷新恢复、冲突后同步 |
| `GET .../materials` | 资料页、测试来源、按 `as_of_seq` 查看历史 | 当前与历史材料、角色私有资料隔离 |
| `POST .../actions` | 阅读、试点设置、扩容/资源申请、索引刷新、暂停/恢复 | 七种动作均覆盖；同一个原请求重试不重复生效 |
| `POST .../approvals/resolve` | 申请面板的明确审核动作 | 扩容至 60 人；资源至 6 人日和第 10 天；申请本身不批准 |
| `POST .../tests` | 助手测试、同题重测 | 旧索引答案 500，刷新后 400；保留配置、源与索引版本 |
| `POST .../turns` | 同事侧栏；优先级入口改为向经理提问 | 三角色真实 worker 回复、实际 `model_revision` |
| `GET .../jobs/{id}` | 排队状态、轮询、刷新恢复 | worker 停止时保持 queued，重启后完成原任务 |
| `POST .../artifacts` | 交付面板保存六字段成果；作品合并到 `rationale` | 最新编辑内容、字段映射、成果版本 |
| `POST .../submissions` | 保存之后固定提交 | 文字/配置变化需重新保存；提交后权威状态只读 |
| `POST .../feedback` | 固定提交后创建反馈任务 | 真实 worker 生成 `rules-v2` 反馈 |
| `GET .../feedback/{submission}` | 读取已保存反馈、恢复旧练习 | 与 worker 返回结果一致 |
| `GET .../timeline` | 反馈页的后端过程记录 | 只读取历史，不重新调用模型 |
| `GET .../evidence/{submission}/{criterion}/{evidence}` | 每条反馈中的证据按钮 | 集成测试遍历所有返回证据，时点不晚于提交 |
| `POST .../relation-checks` | 辅助证据判断（实验） | 当前未配置冻结实验，503 明确显示且不阻塞其他工作；成功推断未验证 |

所有会话接口携带 `Authorization: Bearer`。读取已暂停或已提交会话的材料不会尝试追加业务阅读事件；新操作仍由后端权限与状态约束控制。后端现有 rubric 的不足和待人工核验结果原样呈现，不能把抽取回复或规则反馈称为完整情境化 Judge。

## 恢复与数据边界

- 写入前先持久化原请求。超时、断线、5xx 留下待确认请求，恢复时重发相同 ID 与内容；不因刷新或点击自动另造请求。
- 409 明确拒绝后刷新权威状态，保留草稿，要求重新检查；不偷偷改变 `expected_version` 再发。
- 会话创建没有幂等键，失败时不自动重复；先验证浏览器可保存，避免在已知存储故障下创建无法恢复的会话。
- 角色与反馈使用独立 worker。排队时保留 job ID，刷新只查询；终态失败如实显示。反馈失败重跑受现有后端接口限制。
- 配置保存与审批分开。可保存超过当前资源的申请方案，但保存不代表已经获批；原型的自动批准、定时假回复和本地政策触发在连接版被禁止。
- 自由作品仍保存在本地。正式交付先核对六字段并保存，再固定提交；刚编辑就交付时会同步保存最新正文。已固定版本不可由页面“修订”解锁。
- Agent 任务包只导出实际可见且已打开的后端材料和选择的本地作品/测试；引用正文取实际结果，不能由回传作品伪造。

## 代码位置

- `src/workbench-entry.ts`：主入口加载真实适配器与原 HTML 渲染器。
- `src/workbench-live.ts`：岗位/角色/配置映射、服务端状态投影、实际证据与本地作品的边界。
- `src/store.ts`、`src/api.ts`：原 API 请求、凭据、幂等日志与 job 恢复逻辑，两种连接页共用。
- `public/workbench.js`、`public/workbench.css`：高仿真界面与明确的连接版分支；由 Vite 原样复制进构建。
- `public/workbench-engine.js`：保留的离线规则引擎；连接版仅复用本地事项/作品等编辑逻辑，服务端行为均禁止模拟。
- `src/App.tsx`、`connected/index.html`：原连接页，保留供对照。

工作区原型目录保持原样；实际接口改动在本仓库继续维护，不自动回写离线原型。构建不依赖仓库外文件。

## 验证与复现

在 `apps/web` 运行普通回归与生产构建：

```sh
npm test
npm run build
```

启动 API、worker 和前端预览后，可执行真实 HTTP 集成测试。使用专门的验证数据库；测试创建新会话，不清空已有记录：

```sh
ROLECRAFT_TEST_API=http://127.0.0.1:8510/api npm test
```

`src/workbench-live.test.ts` 的 4 项真实 HTTP 集成测试在没有 `ROLECRAFT_TEST_API` 时跳过。其余测试随普通命令执行。仓库根的后端检查：

```sh
uv run pytest -q
uv run pytest apps/web/tests/test_existing_backend.py -q
```

2026-10-05 本机最终结果：

| 检查 | 结果与边界 |
|---|---|
| 原后端回归 | 80 通过、1 PostgreSQL 跳过；一项既有 Starlette/AnyIO 弃用警告 |
| 既有前端 API 契约 | 5 通过，含鉴权/角色可见性、历史、幂等、提交锁定、失败任务 |
| 前端状态与真实适配器 | 22 通过：11 既有、7 适配边界、4 真实 HTTP/worker 集成 |
| 离线规则与本地记录 | 37 通过；此组不当作真实后端验证 |
| 构建与差异 | TypeScript、Vite、`git diff --check` 通过 |
| 浏览器 | 建会话、配置、助手测试、真实角色回复、作品到交付、修改后重存保护、固定提交、反馈、证据、历史练习恢复通过 |
| 故障注入 | 实际停止 API 后保存请求→刷新→重启→重试恢复；停止 worker 后 queued→刷新→重启完成；真实请求成功后丢失响应不重复写；409 不覆盖草稿 |
| 响应式 | 1440px 和 390px 页面无横向溢出；修复新增会话按钮导致的窄屏标题遮挡，侧栏按钮可点击 |
| 保护检查 | 前端目录外 195 个受管理文件相对本轮开始指纹一致，包括此前已有的三份工程文档修改 |

[真实反馈桌面截图](tests/screenshots/api-feedback-desktop.jpg) · [390px 同事侧栏](tests/screenshots/api-mobile.jpg)。截图和数据库内容均为合成验收样例，不是正式用户实验。正常流程未见脚本异常；停服测试的 HTTP 错误属于故意制造的故障。

本轮未配置或验证 PostgreSQL、外部 LLM、辅助关系判断成功推断、云端部署与真人效果。后端代码未改；提交与合并状态以 [PR #1](https://github.com/yhnapoleon/rolecraft/pull/1) 为准。
