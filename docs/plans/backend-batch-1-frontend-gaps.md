# 第一批：补齐前端已在用的接口，并接入前端

**日期：** 2026-10-05

**目的：** 前端工作台（`apps/web`）的逻辑和呈现已经定了，后端只差一些字段、接口和缺陷修复。本批只做不需要产品讨论的小改动，共 8 项。每一项都包括两部分：

1. **后端：** 补接口或修缺陷。
2. **前端接入：** 用上新的接口，去掉对应的本地替代逻辑。

完整背景见[前端接口需求与未实现功能](../design/frontend-interface-requirements.md)。

**代码基线：**
- 前端：工作台 v4，在分支 `feat/web-workbench-v4` 上。
- 后端：从 `1ebd3a7` 起没有改动。下文的文件位置都按这个版本核对过。

---

## 0. 开工前必读

### 工作方式

- 从 `origin/feat/web-workbench-v4` 建独立的 git worktree 和新分支，例如 `feat/batch-1`。如果 v4 已经合进 `main`，就从 `origin/main` 建。
- 现有 checkout 里有别人未提交的文档改动。不要在那个 checkout 里切分支、stash、reset 或提交。
- 本机已有一套 API（8502）、worker 和前端预览（8510）在运行。不要停止或改动它们。验证时，自己用新端口和临时 SQLite 数据库起一套：

  ```sh
  uv run career-lab serve --host 127.0.0.1 --port <API 端口> --database-url sqlite:///<临时库> --provider local
  uv run career-lab worker --database-url sqlite:///<同一个临时库> --provider local
  ```

  前端预览这样起：在 `apps/web` 先 `npm run build`，再运行 `ROLECRAFT_API_TARGET=http://127.0.0.1:<API 端口> npm run preview -- --port <预览端口>`。
- 可以按项分步提交到自己的分支。推送和开 PR 要等用户确认。

### 后端硬约束

1. **只增不改。** 现有 16 个接口已有字段的名字、类型和含义保持不变。前端依赖的几处：
   - `state.pending_requests` 必须仍是字符串数组。前端用 `Array.isArray` 校验，并按 `capacity_approved` 这类字符串判断申请种类。
   - `state.material_versions.policy` 和 `state.indexed_versions.policy` 必须保留。
   - 错误响应里现有的 `error`（或 FastAPI 的 `detail`）字符串保持原文。旧前端靠这些原文翻译。
2. **不改场景包。** `scenarios/**` 的每个场景都有 `manifest.json` 哈希锁，改动后无法加载（`src/career_lab/scenarios/loader.py:147-150`）。本批不需要改资料。
3. **不改世界规则。** 不要新增经过 `apply_action` / `commit_action` 的动作。每个这样的动作都会让 `version` 和 `action_count` 加一，从而改变政策更新的触发时机（`scenarios/reducer.py:109-115`）。需要另外保存的记录，用 `SessionStore.save_derived`（`storage/sessions.py`）。
4. **数据库没有迁移机制。** `Database` 只用 `metadata.create_all`：它会建新表，但不会给已有表加列（`storage/database.py`）。所以新增数据放进新表。旧数据库必须能继续使用：旧记录查不到新字段时返回 `null`，不能报错。
5. **时间不要写进对象内容。** 测试记录、交付稿和配置会原样拼进评审证据包。证据包有 16,000 字节上限，时间写进去会占用上限，还会改变输入哈希（`evidence/assembler.py:40-71`）。
6. **不碰讨论中的部分：**
   - `local` 模式的回复格式（`runtime/model_adapter.py`）；
   - 同事提示词（`runtime/loop.py:31`）；
   - 政策触发规则；
   - 评审条目与证据的对应关系；
   - 外部 Agent。

### 前端约束

- 代码结构：

  | 文件 | 负责什么 |
  |---|---|
  | `src/api.ts` | 请求和 `ApiError` |
  | `src/store.ts` | 会话、写入、任务轮询、`serverText` 错误翻译 |
  | `src/workbench-live.ts` | 把服务端状态转成界面数据 |
  | `src/app/ui.js` | 页面和交互 |
  | `src/app/coach.js` | 前端规则 |

  新文案一律写成 `T('中文', 'English')`。
- 只改接入需要的地方。不改布局和视觉，不改颜色约定（见接口需求 1.5）。
- 后端没有返回新字段时（旧会话、旧数据库），前端回到现在的行为，不能报错。
- 前端会识别同事回复开头的“本地事实模式：”并加标签。这项属于讨论中的部分，保留不动。

### 每完成一项要跑

- 仓库根：`uv run pytest -q`。现在是 80 通过、1 个 PostgreSQL 跳过，不能变少。
- `apps/web`：
  - `npm test`：现在 18 通过、4 跳过；
  - `npm run build`；
  - `ROLECRAFT_TEST_API=http://127.0.0.1:<API 端口> npm test`：现在 22 项全部通过。
- 浏览器走查：`apps/web/tests/walkthrough/` 里有两个脚本。
  - `walk.mjs`：完整经历。
  - `walk-flows.mjs`：申请审批、Agent 带回、新建事项。
  - 运行前设置三个环境变量：`CHROME_BIN`（Chrome 或 chrome-headless-shell 的路径）、`BASE`（前端预览地址）、`OUT`（截图目录）。
  - 用法见脚本开头。输出里出现 `FAIL`、控制台错误或横向溢出，都算没通过。
  - 至少跑这四组：`1440 900 zh`、`1440 900 en`、`390 844 zh`、`walk-flows.mjs zh`。
- 每项新功能都要补后端测试。前端行为变化写进 `src/workbench-live.test.ts` 或 `tests/workbench-state.cjs`。

---

## T1 任务查询返回类型和同事

- **后端**
  - **现状：** `GET /sessions/{id}/jobs/{job_id}` 只返回 `id, status, attempt, result, error`（`api/app.py:159-164`）。其实 `jobs` 表里已有 `kind`，同事回复任务的 `payload` 里也已有 `role_id`。
  - **要做：** 响应增加两个字段：
    - `kind`：`"turn"` 或 `"feedback"`；
    - `role_id`：同事回复任务填写；评审任务为 `null`。
- **前端接入：** `store.ts` 的 `poll()` 和“正在输入”优先用返回的 `kind` 和 `role_id`；没有这两个字段时，沿用现在从本地请求推断的做法。
- **验收：**
  - 同事回复任务返回 `kind: "turn"` 和对应的 `role_id`。
  - 评审任务返回 `kind: "feedback"`、`role_id: null`。
  - 刷新页面后，“正在输入”仍显示在正确的同事旁边。

## T2 时间戳和提问原文

- **后端**
  - **现状：** 所有接口都没有时间。同事回复记录里没有用户问的话（`runtime/loop.py:48-49` 的 `result` 只有回答）。
  - **要做：**
    - 从现在起，下列记录写入时记下 `created_at`，格式为 ISO 8601 UTC，例如 `2026-10-05T09:30:00Z`：
      - 事件（`events`）；
      - 对象：测试、交付稿、提交、同事回复、审批结果。
    - 任务另外记 `queued_at`、`started_at`、`finished_at`。`started_at` 取最近一次被领取的时间。
    - 存法：用新表，例如 `event_times(session_id, seq, created_at)`、`object_times(id, created_at)`、`job_times(id, queued_at, started_at, finished_at)`。和原记录在同一个事务里写入。
    - 同事回复的 `result` 增加 `question`（用户原话）。同事回复不进证据包，所以可以放在 `result` 里。
  - **在哪里返回：**
    - `GET …/timeline`：`events[].created_at`，以及 `turns[].created_at` 和 `turns[].question`。
    - `POST …/tests`、`POST …/artifacts`、`POST …/submissions` 的响应，以及 T3 的列表接口：`created_at`。
    - `GET …/jobs/{id}`：三个时间字段。
- **前端接入：**
  - 对话和动态里的时间，现在是浏览器看到它的时间（`ui.js` 的 `a.turnTimes`、`a.eventTimes`，在 `noticeArrivals()` 里记录）。改为优先用服务端时间。
  - 同事回复的提问原文，现在只存在本机（`store.ts` 的 `questions`）。改为优先用 `turns[].question`，这样换浏览器后对话也完整。
  - 没有服务端时间时，沿用现在的做法。
  - README 里“后端没有时间戳”那段说明要同步改掉。
- **验收：**
  - 新会话里，上述记录全部带时间。
  - 用本批之前创建的数据库启动，旧记录返回 `null`，接口不报错。
  - 重放同一个 `request_id`，返回第一次的时间，不生成新时间。
  - 清空浏览器存储后重新打开同一会话，对话里能看到提问原文和真实时间。

## T3 列表接口

- **后端**
  - **现状：** 测试、交付稿和提交只在创建时返回一次。
  - **要做：** 新增三个只读接口，鉴权方式和其他会话接口一样：
    - `GET /sessions/{id}/tests`
    - `GET /sessions/{id}/artifacts`
    - `GET /sessions/{id}/submissions`
  - **返回格式：**
    - 每条记录和对应 `POST` 的响应结构相同，另带 T2 的 `created_at`。
    - 按 `as_of_seq` 排序；`as_of_seq` 相同的，再按 `created_at` 排。
    - 数据来自 `SessionStore.list_objects`。
- **前端接入：**
  - 恢复会话时，本地缺失的测试记录从 `GET …/tests` 补齐，包括测试台、事项目录、反馈规则里用到的测试。
  - 测试属于哪件事只存在本机。从服务端补回的测试没有事项归属时，只出现在“全部测试”里。
- **验收：**
  - 做 2 次测试、保存 2 版交付稿、提交 1 次后，三个接口分别返回 2、2、1 条，内容与创建时一致。
  - 用错误的 token 访问，返回 401。
  - 清空浏览器存储后重新打开会话，测试台能看到之前的测试。

## T4 审批结果

- **后端**
  - **现状：**
    - 批准成功时，只返回决定，不含新状态（`api/approvals.py:45-50`）。
    - 不批准时，5 种原因都只返回英文 422（`approvals.py:25-44`），也不留记录。
  - **要做：**
    - **成功：** 在现有字段之外增加 `state`，即审批后的会话状态（按 T7 过滤）。
    - **失败：** 保持 422 和原来的 `error` 字符串，另加 `code` 和 `details`：

      | 位置 | `code` | `details` |
      |---|---|---|
      | `approvals.py:25` | `approval_no_pending_request` | — |
      | `approvals.py:27` | `approval_needs_config` | — |
      | `approvals.py:33` | `approval_plan_incomplete` | `missing`：缺的必要工作项、是否缺人工兜底、人数是否低于下限 |
      | `approvals.py:42` | `approval_unsupported_rule` | — |
      | `approvals.py:44` | `approval_not_needed_or_over_limit` | 申请值、当前值、允许的上限 |

    - **记录：** 不批准时，用 `save_derived` 存一条 `kind: "approval_denied"`，内容为 `{rule_id, request_id, code, details}`。同一请求重复提交，只保留一条。
    - **对外返回：** `GET …/timeline` 增加 `approval_denials` 列表，每条带 T2 的 `created_at`。
- **前端接入：**
  - 资源与审批面板（`ui.js` 的 `sheetResources()`）显示没批准的具体原因，例如“缺人工兜底”。现在只能说“没有批准”。
  - 动态里加入驳回记录。
  - 批准成功后，直接用返回的 `state` 更新条件。
- **验收：**
  - 申请扩容、但配置里没有人工兜底：
    - 接口返回 422，`code` 为 `approval_plan_incomplete`，`details.missing` 写明缺人工兜底；
    - `version` 和 `action_count` 都不变；
    - timeline 里多一条驳回记录；
    - 界面显示缺什么。
  - 批准成功：响应里的 `state.resources.capacity` 是新值。

## T5 错误码

- **后端**
  - **现状：** 错误只有文字（`api/app.py:96-103`）：
    - `ValueError` 及其子类返回 `{"error": "..."}`；
    - `KeyError` 返回 `{"error": "not found"}`；
    - `HTTPException` 返回 `{"detail": "..."}`。
  - **要做：** 所有错误响应在原有字段之外加一个 `code`（snake_case，不再变动）。至少覆盖：

    | 原文（开头部分） | `code` |
    |---|---|
    | `expected N; current M`、`approval state changed` | `version_conflict` |
    | `session is paused` / `session is submitted` | `session_paused` / `session_submitted` |
    | `config version is not current` | `config_not_current` |
    | `artifact/config version mismatch` | `artifact_config_mismatch` |
    | `material unavailable` | `material_unavailable` |
    | `invalid pause/resume` | `invalid_pause_resume` |
    | `configure pilot before submission` | `config_required` |
    | `learner request requires a reason` | `reason_required` |
    | `request unavailable` | `request_unavailable` |
    | `unknown domain or work item` | `unknown_domain_or_work_item` |
    | `request_id reused …`、`idempotency key reused …`、`approval request ID reused …` | `request_id_reused` |
    | `query length must be 1..4000` | `query_length` |
    | `unknown scenario` | `unknown_scenario` |
    | `unknown role`（T7 新增） | `unknown_role` |
    | `session token required` / `invalid session token` | `token_required` / `token_invalid` |
    | `frozen relation study is not configured` | `relation_not_configured` |
    | `not found` | `not_found` |
    | 其他 | `invalid_request` |

  - **实现建议：** 让异常类自带 `code`，不要按文字匹配。审批相关的 code 见 T4。
- **前端接入：**
  - `api.ts` 的 `ApiError` 增加 `code`。
  - `store.ts` 的 `serverText()` 先按 code 翻译，没有 code 时再按原文匹配。
  - 现有翻译都要保留对应的 code。
- **验收：**
  - 每个 code 至少有一个后端测试。
  - 前端在中英文下对这些错误显示的文字，与改动前一致或更具体。

## T6 评审理由与超长

- **后端**
  - **现状：** 有三条理由与事实不符；证据超长时，理由会显示成“材料或日志不完整”。
  - **要做：**
    - **`R3.resources`**（`rubrics/checks.py:28`）：理由现在固定以“必要依赖已核验”结尾。改为：
      - 满足时保留这句；
      - 不满足时，写清哪一项不满足：缺哪个必要工作项、成本超出人日、上线日超出期限，还是兜底不是人工。
    - **`R4.functional_tests`**（`checks.py:30-32`）：如果当前配置版本下没有测试、其他版本下有，写“有 N 次测试，都不在提交时的配置版本 vX 下”。只有完全没有测试时，才写“完整日志中没有实际测试”。
    - **`R4.staleness_test`**（`checks.py:35-41`）：如果政策更新后没有新测试、更新前有，写“政策更新后没有新的测试（更新前有 N 次）”。
    - **超长**（`checks.py:18-19`）：
      - 当 `item.completeness == "overflow"` 时，理由写“证据超过长度上限，本项未评”。
      - `CriterionResult` 增加 `completeness` 字段，默认 `"complete"`，随 `items[]` 返回。
      - 评审结果顶层增加 `overflow: true/false`。
      - 上限和截断方式都不改。
    - **规则版本：** 输出变了，所以把 `RULES_REVISION` 从 `"rules-v2"` 改为 `"rules-v3"`（`checks.py:4`）。
      - 影响：旧的 `rules-v2` 提交如果还没生成过评审，以后会生成失败（`rubrics/feedback.py:10`）；已经生成的评审照常可读。
      - 前端显示的是接口返回的版本号，没有写死。
- **前端接入：** 评审页 `overflow: true` 时，在“上线检查”顶部说明“证据超过长度上限，部分条目未评”，并指向交付面板里的作品选择。条目照常按结论分组显示。
- **验收：**
  - 三种理由的各个分支都有测试覆盖：满足、不满足、测试在另一配置版本、只有政策更新前的测试。
  - 用 `token_budget` 很小的证据包测试超长：`completeness` 和 `overflow` 都正确，理由是新文字，界面显示超长说明。

## T7 接口缺陷与可见性

- **同事回复入队前校验**
  - **现状：** `POST …/turns` 直接入队（`api/app.py:154-157`）。同事 ID 无效、或会话已暂停或已提交时，worker 要失败 3 次才结束。
  - **要做：** 入队前检查两项，任一不满足就直接返回 422 和 T5 的 code：
    - `role_id` 必须是场景里的角色；
    - 会话状态必须是 `active`。
- **评审失败后可以重新生成**
  - **现状：** `POST …/feedback` 用固定的请求键入队（`app.py:166-170`）。失败后再请求，拿回的还是那个失败的任务。
  - **要做：** 请求体增加可选的 `retry: true`。只有原任务状态为 `failed` 时，才把它重新排队：状态改为 `queued`，`attempt` 归 0，清空 `error`。其他情况行为不变。
  - **前端接入：** 评审生成失败时，显示“重新生成”按钮，带 `retry: true` 调用。README 里“反馈失败重跑受现有后端接口限制”这句同步改掉。
- **隐藏学员看不到的资料**
  - **现状：** 会话状态里带着 `tech_private` 的版本号，学员能看到这份私有资料存在。
  - **要做：** 下列响应里的 `material_versions` 和 `indexed_versions`，只保留 `visible_to` 含 `learner` 的资料：
    - `POST /sessions`；
    - `GET /sessions/{id}`；
    - `POST …/actions` 返回的 `state` 和 `snapshots`；
    - T4 新增的 `state`。

    可见性的判断与 `scenarios/visibility.py` 一致，其他字段不变。
- **验收：**
  - 用无效的 `role_id`、或在暂停中的会话里发同事消息，都直接返回 422，不产生任务。
  - 评审任务失败后带 `retry` 能重新完成，界面上的“重新生成”可用。
  - 上述响应里看不到 `tech_private`。

## T8 对话上下文

- **后端**
  - **现状：** 同事回复请求只有 `role_id, text, request_id`。
  - **要做：**
    - `TurnRequest` 增加三个可选字段：
      - `task_id`、`work_id`：前端生成的任意字符串，最长 200；
      - `attachments`：`[{type: "work" | "test", id, version?}]`，最多 10 个。
    - 这些字段随任务 `payload` 传给 `run_turn`，存进同事回复的 `result.context`，在 `timeline.turns[]` 里返回。
    - 本批只保存，不放进提示词，也不改变回答。
    - 不带这些字段时，指纹和行为与现在完全相同。带了就计入指纹：同一个 `request_id` 换了上下文，按重复使用处理。
- **前端接入：**
  - 发消息时，带上当前事项（`ui.chatTask`）、打开的作品，以及用“附上作品 / 附上测试”附上的对象。
  - 对话里的事项标注（`ui.js` 的 `a.turnTask`）和“这件事”筛选，优先用服务端返回的 `context.task_id`。
  - 附上的作品或测试，仍按现在的方式写进消息正文，因为同事的回答暂时还读不到附件。
- **验收：**
  - 在一件事里发一条消息，`timeline.turns` 原样返回上下文。
  - 清空浏览器存储后重新打开会话，消息仍标在原来那件事下。
  - 同一个 `request_id` 换了 `task_id` 重发，返回 `request_id_reused`。
  - 不带上下文的旧调用，结果不变。

---

## 收尾

- 更新[前端接口需求](../design/frontend-interface-requirements.md)：
  - 第 2.1 节里本批已修的问题；
  - 第 5 节里对应的项，标为已完成。
- 更新 `apps/web/README.md`：接口覆盖、数据边界和验证结果。

## 不在本批

下面这些需要先讨论，本批不要做：

- 会话语言和英文资料（P0-1）
- 同事回复质量与 `local` 模式（P0-2）
- 资料清理（P0-4）
- 证据对应到条目、超长怎么截断（P0-5 的另一半）
- 政策触发口径（P0-6）
- 事项和作品存到后端（P1-1、P1-2）
- 同事主动发言、排序建议、过程反馈（P1-5、P1-8、P1-9）
- 外部 Agent（P1-11）
- 建会话的防重复提交：会话凭据只存哈希，重放时拿不回原 token，需要先定方案

## 完成后报告

逐项写清：

- 后端和前端是否都完成；
- 改了哪些文件；
- 新增了哪些测试；
- 后端测试、前端测试和走查的结果；
- 与本说明不一致的地方，以及原因。

推送和开 PR 要等用户确认。
