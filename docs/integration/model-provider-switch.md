# 模型提供方切换与验证

标准启动入口已经验证过：知识助手、同事对话和语义 Judge 只需改变运行配置，就能接到 OpenAI-compatible 服务。验证用的是本地测试服务，中文、英文分别核验。助手的生成同时覆盖 openai 和 deepseek 两种装配；local 角色替身不会被当作生成模型。

尚未验证的部分：
- 没有调用过真实在线模型，也没有验证模型的语义质量。
- 受限 Agent 的派生授权仍待公共存储接入，见文末“接缝”一节。

## 配置位置

服务端与 worker 使用同一组配置，用 `--provider openai`、`--provider deepseek` 或 `--provider local` 选择适配器。

| 配置 | 含义 | 测试中的取值 |
|---|---|---|
| `CAREER_LAB_KEY_FILE` | 服务端可读的 key 文件路径；文件内容不进入业务请求 | 临时目录中的随机 key，不用于真实认证 |
| `CAREER_LAB_BASE_URL` | OpenAI-compatible 地址，适配器在后面追加 `/chat/completions` | 本机回环测试服务 `http://127.0.0.1:<端口>` |
| `CAREER_LAB_MODEL` | 固定的模型版本名 | `controlled-mechanism` |
| `--provider` | 正式入口选择的提供方 | `openai`／`deepseek`／`local` |

- 真实部署的 base URL 只用 HTTPS，不要在 URL 里放用户名、密码或 key 等凭据。上表的明文回环地址只用于本机测试。
- 非 local 装配调用 `OpenAICompatibleModel.from_key_file(..., retries=0)`。生成器也要求 `retries=0`，队列以不可自动重试的 handler 注册。
- 运输超时沿用适配器默认的 45 秒，超时后不重试。
- key 不会出现在提示词、请求正文、返回 JSON、数据库或生成记录中。不要把 key 值写进命令或共享文档。

真实 provider、模型名、key 交付方式和预算由负责方确定，本说明不授权真实付费调用。

## 启动与回退

在仓库根用 `uv run --locked` 运行。项目要求 Python ≥ 3.11（CI 使用 3.12）。API 与 worker 必须使用相同的数据库和环境变量。

```sh
uv run --locked python -m career_lab.cli serve --host 127.0.0.1 --port 8000 --database-url sqlite:///<数据库路径> --provider openai
uv run --locked python -m career_lab.cli worker --once --database-url sqlite:///<数据库路径> --provider openai
```

前提是已设置上面三个环境变量。`--once` 至多处理一个排队任务，适合验证。

回退时，停止自己启动的 API 和 worker，再用同一数据库以 local 重新启动：

```sh
uv run --locked python -m career_lab.cli serve --host 127.0.0.1 --port 8000 --database-url sqlite:///<数据库路径> --provider local
uv run --locked python -m career_lab.cli worker --once --database-url sqlite:///<数据库路径> --provider local
```

回退不会改写旧回复、旧测试或旧反馈。排队中的助手生成请求固定了 provider、模型、地址指纹、提示版本、语言和配置；重启后这些身份不同时返回 `assistant_model_changed`，不会调用新模型。需要新条件时，显式发起新测试。

## 选择生成模式

- `AssistantConfig.generator` 通过已注册的 `configuration.apply`（或 `actions` 的 `apply_config`）修改，学员和获得 act 授权的 Agent 走同一条路径。
- **部署未配置模型时**，切换到 `llm` 会被拒绝：返回 409 和 `generator_unavailable`，文案中英各一份，来自场景消息表，配置和会话状态都不变。
- **部署已配置模型时**，切换照常记录为一次配置变更，版本加一。
- 如果配置已经是 `llm`，而部署之后改回 local：
  - 测试结果保存为 `unavailable`，文案“未配置模型。等待模型接入；问题与配置已保留。”／“Model not configured. Awaiting model connection; question and configuration saved.”；
  - 其他设置仍可保存，也可随时改回 `extractive`。
- 学员在 v4 试点设置面板的“回答方式”里看到并修改这项设置；面板每次保存都带上可见的选择。

## 怎样核验切换

下列测试不需要真实 key，也不访问付费服务：

```sh
uv run --locked python -m pytest -q tests/expansion_v3/w02/test_generation_flow.py
uv run --locked python -m pytest -q tests/integration/test_provider_switch.py
uv run --locked python -m pytest -q tests/expansion_v3/w02/test_generation_display.py
uv run --locked python -m pytest -q tests/expansion_v3/w02/test_generation_mode_ui.py
```

正常入口的中英浏览器检查（先 `npm run build`，在 `apps/web` 下运行；端口默认 web 19930、api 19932，依次启动未配置模型和配置了回环测试替身的两套部署）：

```sh
CHROME_BIN=<chrome-headless-shell> OUT=<新目录> node tests/regression/assistant-mode.browser.mjs
```

- **生成模块**：
  - 走标准的 `tests.create → Worker → tests.list`，保留问题、请求配置与实际配置、索引、候选和引用；
  - 引用了候选外、未来或私有来源时，整条回答拒绝；
  - 模型运输只用受控替身；
  - 未配置模型时拒绝切换到 llm；已是 llm 的配置在 local 部署上保存为 `unavailable`，零调用。
- **正式提供方切换**：
  - 用 `create_runtime_app(provider="openai")` 和本机 HTTP 测试服务；
  - 每种语言下，助手、同事回复、单项 Judge 各调用一次，同事回复另有一次结构化帮助复核；助手另覆盖 deepseek；
  - 同事回复与 Judge 的 HTTP 错误、坏 JSON 分别验证；助手另验证提供方停滞：超时的尝试记为 `timeout`，结果保存为 `failed`／`assistant_generation_failed`，不重试；
  - 恢复读取不会再次调用；
  - 故障时反馈保留作品和待核验状态，不转成业务判错。
- **worker 中断**：在运输边界模拟进程终止，等真实队列过期后由另一个 worker 接管，第二个 worker 不再调用。原问题可以从 `requests.read` 回读。显式另发请求会产生新的尝试。
- **密钥检查**：测试随机生成 key，只在临时 key 文件和 Authorization 头中使用；扫描 SQLite 主文件和 WAL、响应、请求正文和日志，断言都不含该字符串。
- **组件显示**：用 Vite 实际加载 `test-set-view.js`，检查中英模式、引用版本、有效配置展开，以及原记录不变。
- **宿主与正常入口**：`test_generation_mode_ui.py` 经标准 HTTP 与 worker 核对 `workbench.read` 按单次记录给出模式、过期警告在生成答案前保留、生成答案在评价证据中标为 `model_generated`、提交后的反馈把生成的复测留在待核验、未配置部署上可改回 extractive；`test_evaluation_facts.py` 核对引用了正确政策片段的生成复测不进入通过列表，而同题抽取复测照常通过；浏览器检查在中英、桌面与 390px 下核对答案标签只出现一次、测试计划模式行与有效配置、设置面板的回答方式与重置，以及生成复测后提交的反馈中该项显示为等待核验。

合入前运行仓库回归门禁：`uv run --locked python -m scripts.regression.run --output <新目录>`，需要浏览器检查时加 `--browser`。

## 状态与历史记录

| 记录状态 | 含义 |
|---|---|
| `extractive` | 确定性原文抽取；旧配置省略 generator 时仍为此默认行为 |
| `llm` | 所配置的适配器实际返回，且引用全部通过候选校验；回答仍待核验 |
| `unavailable` | 部署没有可调用的模型；问题与配置已保存，调用次数为零 |
| `failed` | 生成或校验失败，包括运输超时（尝试记为 `timeout`）；没有候选时也保留具体规则原因，不会误标为“未配置模型” |

- 生成记录用独立的 `assistant_execution` 对象，与原 `TestResultV2` 在同一个 Mutation 中保存。
- 只有存在这类记录时，`tests.list` 才附加 `generations`。原测试 DTO、旧的抽取返回形状和已发布的场景包都不改写。

- `workbench.read` 的 `semantic.assistant` 反映部署是否接入模型（`model`／`waiting_model`），时间线中每个 test 另带 `assistant`：该次答案保存时的模式、provider、模型版本和配置版本。模式来自单次 `assistant_execution` 记录；llm 配置下因规则守卫没有调用模型的答案仍是抽取路径的原答案，记为 `extractive`。
- 测试台与测试计划只按单次记录显示一个模式标签：未接入模型时抽取答案显示“等待模型接入（当前为原文检索结果）”，接入后显示“原文抽取”；生成答案显示“模型生成 · 回答待核验”；另有“未配置模型”“生成失败”。答案正文不再加前缀，当前部署状态不会改写历史答案的标签。调查工作纸的“查看这次实际回答”和“这次回答用的来源”弹窗显示同一个标签；生成答案被写进作品依据或引给同事时，正文前带“（模型生成 · 待核验）”。测试计划的模式行显示 provider／模型版本和“本次有效配置 · v<n>”。
- 来源过期且 `freshness_guard=warn` 时，生成答案前保留与抽取答案相同的过期警告句，引用仍是原版本，界面照常标“引用了旧版本”。
- 评价证据读取把成功生成的回答标为 `model_generated`，并在问题与回答之间加“模型生成回答（待核验）”标记，不当作规则核实的原文片段。规则事实也不把生成答案计为复测通过：相关复测由模型生成时 `passing_dynamic_test_ids` 保持未知，反馈中“实际调整与复测”一项为待核验，并写明“最新相关复测的回答为模型生成，待核验”；规则仍可核对它实际使用的材料版本。
- 试点设置面板显示回答方式。未接入模型时“模型生成”不可选并说明原因；已保存为 llm 的配置仍显示且可随时改回原文抽取。保存时总是发送面板上可见的选择。
- llm 测试由 worker 生成：界面先显示“等待模型生成”，之后按原请求读取结果并归入原事项、测试计划行或调查重测；失败时提示并停止等待，不会再发起模型调用。生成失败时保留原问题、旧结果和具体错误；读取页面不会触发新的模型调用。

## 公共冻结与装配

`AssistantConfig.generator` 是唯一新增的契约字段：类型为 `extractive|llm`，可选，默认 extractive，默认值不进入序列化。

| 契约 | 新 revision | 变化 |
|---|---|---|
| expansion-v3 | `expansion-v3-90a362db7068f8b9707406a9633cf25f3da6c8be38df18c24da3edadf069326b`（previous 为 `expansion-v3-f9edfe270e6bb39ef3661061ca37be65827bb99cae96a1ca4abadea736e53952`） | 9 个含 AssistantConfig 的 schema（ActionInput、AssistantConfig、BusinessBasis、BusinessRequest、EffectiveConfig、ReviewInput、ReviewRequest、ScenarioBundle、TestResultV2）和 openapi 增加该可选字段 |
| engineer-review-v1 | `engineer-review-v1-5dd7f7efbeffd3c3bdf2192b6407157d0f7c54a3757c0aea860a75c2921ed5f5` | 内嵌 AssistantConfig。除绑定的上游 manifest hash 外，EngineerProbeResult、EngineerRegressionReport、EngineerReviewInput 三个 schema、openapi 和 types.ts 也带上同一可选字段 |

- 发布历史只在 `manifest_history.py` 末尾追加一条记录：changes_since_draft 增加该字段说明，integration_changes 新增 `assistant-generator`。
- 导出沿用现有的 `without_provenance` 兼容方式；examples 与 errors 字节不变，原 documents 和 review_fixes 保全。
- 宿主随后按单次记录投影助手模式（`api/vertical_reads.py` 是契约实现输入），发布历史末尾追加 `assistant-mode-projection` 一条，两套导出重新生成：expansion-v3 现为 `expansion-v3-8b84c0a227a9493b5637adca4b01cf9a77dd8e4ad7fab9f5d70698165e705b34`（previous 为 `expansion-v3-90a362db…`），engineer-review-v1 现为 `engineer-review-v1-4423ad399ede720d2ca65d1a8c76d9476609728e38f0dad8183838af946a65ef`。只有 manifest、revision 和 `contracts-v2.ts` 头注释变化，schema、examples、errors 不变。
- 发布身份用 `scripts/regression/release_identity.py --refresh` 按当前字节重算：受保护清单中重新生成的 12 项更新，无新增，`commit` 不变。历史冻结、场景包和所有旧实例保留。
- 装配方面，`build_registry` 只用三行构造参数透传已配置的模型，`LocalRoleModel` 映射为 None。
- main 若在合入前前进，须在历史末尾追加记录、指向 main 当时的 revision，并重新生成导出。

## 留给公共存储的接缝

| 责任接点 | 最小改动与原因 |
|---|---|
| 公共存储的派生对象授权 | 承认 `assistant_execution` 与已授权 test 之间不可变的派生关系，并在窄授权读取中复核全部候选依赖。在此之前，`allowed_objects` 受限的 llm 测试在调用前返回 `assistant_scoped_generation_unavailable` |

这一处目前没有接通。真实语义质量也不能用回环服务的验证来代替。
