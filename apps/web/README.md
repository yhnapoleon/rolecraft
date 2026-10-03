# RoleCraft 工作区前端

React + TypeScript + Vite，连接仓库现有 FastAPI 接口。此目录独立安装和构建；没有修改根依赖、后端、场景、模型、数据或原有测试。

## 本地启动

需要 Node.js >= 22.12、npm，以及按仓库 `uv.lock` 安装的 Python 环境。在仓库根目录运行 `uv sync --locked` 后，分别启动 API 和 worker（两个终端，必须使用同一数据库）：

```sh
uv run career-lab serve --host 127.0.0.1 --port 8502 --database-url sqlite:////tmp/rolecraft-web-preview.db --provider local
```

```sh
uv run career-lab worker --database-url sqlite:////tmp/rolecraft-web-preview.db --provider local
```

第三个终端：

```sh
cd apps/web
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>。前端通过 Vite 将 `/api/*` 转发到 `http://127.0.0.1:8502/*`，无需修改后端 CORS 或注册静态路由。可用 `ROLECRAFT_API_TARGET` 指定另一已有 API 地址；不要把凭据放入该地址或任何前端环境变量。

`npm run build` 生成 `dist/`；`npm run preview` 在端口 4173 预览，使用相同代理。生产静态托管需要另行配置同源 `/api` 转发；本次没有部署或修改任何托管配置。

`local` 是后端自带的抽取模式，**不是外部大模型**。如管理员已有获授权的模型配置，沿用原 CLI 的 provider/key-file 配置，并让 API 与 worker 使用一致配置。前端不接收模型密钥；角色卡以每次返回的 `model_revision` 说明实际执行模式。

## 两个入口

- `/`：真实连接版。新会话、角色、材料、测试、配置、提交、反馈均调用现有 API，断线不会切换成演示回答。
- `/demo/`：原高保真原型的 11 个运行文件与图片原样副本，保留原有演示标记。其脚本只在该入口执行；它不是后端联调证据。

两者使用不同浏览器存储键。连接版的会话 token、问题、草稿、测试记录与待处理请求保存在本机浏览器的 `rolecraft.live.workspace.v1`；不要分享、导出或提交该存储内容。没有登录账户、跨设备同步或服务端会话列表。清理浏览器存储会丢失恢复凭据；后端 timeline 也不能重建所有原始问题、草稿和测试结果。

## 已接入的接口与边界

| 工作区动作 | 现有接口 | 保留的行为 |
|---|---|---|
| 新建、恢复、暂停 | `POST /sessions`，`GET /sessions/{id}`，`POST .../actions` | 支持现有三个场景；暂停可恢复，提交不可解锁 |
| 材料与阅读记录 | `GET .../materials`，`read_material` action | 仅展示学习者可见材料；历史材料按后端 `as_of_seq` 读取 |
| 三个同事 | `POST .../turns`，`GET .../jobs/{id}`，`GET .../timeline` | 独立 worker 异步执行；不会以本地预设文本冒充结果 |
| 配置与资源 | `update_pilot`、`refresh_index`、资源申请 actions，`POST .../approvals/resolve` | 配置与索引分开；批准由现有场景规则决定，聊天不批准资源 |
| 助手测试 | `POST .../tests` | 保存真实答案、引用、配置/源/索引版本；同题可按新配置再次提交，不覆盖历史 |
| 交付与固定提交 | `POST .../artifacts`、`POST .../submissions` | 使用后端六字段；文字或配置改变后必须先重新保存交付稿；提交锁住会话 |
| 反馈、回放、证据 | `POST/GET .../feedback`，`GET .../timeline`、`GET .../evidence/{submission}/{criterion}/{evidence}` | 分数区间不是最终分数；待核验项保留；证据由鉴权接口按提交时点返回 |

后端三角色均有独立的信息投影：经理、技术负责人和业务负责人不能互相读取所有材料；技术角色有其私有材料。模型可调用的工具只有列材料和读材料。角色支持连续发起独立回合及单回合内的工具循环，**现有运行器不传递跨回合聊天历史**；界面显示此限制，不将页面上的对话记录称为模型记忆。

助手测试当前使用后端 BM25/抽取实现，角色配置外部模型也不会自动把测试改成生成式 RAG。原型九字段不伪装成已存在的九字段接口：连接版使用 `goal`、`owner`、`metrics`、`observation_window`、`exit_condition`、`rationale` 六个交付字段，并独立维护试点配置。日期提醒、提交后修订/关联补练、外部 Agent 接入及完整语义评价尚无可用闭环。

写操作在发出前持久化原请求；网络不确定时只重发相同请求 ID 和内容。409 会刷新状态并要求用户重新检查，不自动修改版本重发。新建会话没有幂等键，失败后不自动重复创建。角色失败可由用户发起新回合；反馈任务终态失败则明确停住，因为现有接口会返回同一个失败任务。worker 停止时显示排队并保留 job ID，刷新不重复发起。

## 验证

从 `apps/web` 运行：

```sh
npm test
npm run build
```

从仓库根目录运行原回归和新增接口契约测试：

```sh
uv run pytest -q
uv run pytest apps/web/tests/test_existing_backend.py -q
```

2026-10-03，基于后端 `1ebd3a7d74a172cd3a3196bd0ec24662db55d409` 的本机结果：原测试 80 通过、1 跳过；新增后端契约测试 5 通过；前端状态与恢复测试 11 通过；TypeScript/Vite 构建通过。Python 测试有一项既有 Starlette/AnyIO 弃用警告；PostgreSQL 未配置，相关测试跳过。本次使用独立临时 SQLite 数据库，没有远程模型密钥，不代表 PostgreSQL、外部模型或真人试用已验证。

Mac 支持的内置浏览器实际走通：建会话 → 三角色真实本地模式回复 → 配置 → 政策源更新后旧索引回答 500 → 刷新索引同题回答 400 → 政策转人工 → 读取/引用材料 → 六字段交付 → 固定提交 → 规则反馈 → 证据查询。另实测停止 API 后原请求重试、停止 worker 后排队刷新恢复、提交后只读、反馈刷新恢复。390 px 窄屏导航可用且无横向溢出；最终页面控制台无错误。

[桌面反馈截图](tests/screenshots/feedback-desktop.jpg) · [窄屏截图](tests/screenshots/feedback-mobile.jpg)。截图来自合成联调样例，不是用户能力评估或真人实验结果。

原型运行文件均原样复制；仓库原有 195 个受管理文件与上述基线的 SHA-256 全部一致。审阅时可用以下命令确认变更只新增本目录：

```sh
git diff --name-status 1ebd3a7d74a172cd3a3196bd0ec24662db55d409...HEAD
git diff --exit-code 1ebd3a7d74a172cd3a3196bd0ec24662db55d409 HEAD -- . ':!apps/web'
```
