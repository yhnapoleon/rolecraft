# 模型提供方切换与验证

当前标准启动入口已验证：知识助手、同事对话和语义 Judge 可以仅改变运行配置，接到本地 OpenAI-compatible 测试服务；中文、英文分别核验。助手同时覆盖 openai／deepseek，local 角色替身不会作为生成模型。本次没有调用真实在线模型，也没有验证模型语义质量。v4 单次元数据／异步恢复和受限 Agent 派生授权仍由宿主与公共存储负责人接入。

## 配置位置

服务端与 worker 使用同一组配置，并通过 `--provider openai` 或 `--provider local` 选择适配器。

| 配置 | 含义 | 本次验证值 |
|---|---|---|
| `CAREER_LAB_KEY_FILE` | 服务端可读的 key 文件路径；文件内容不进入业务请求 | 临时测试目录中的随机 key，不用于真实认证 |
| `CAREER_LAB_BASE_URL` | OpenAI-compatible 地址，适配器追加 `/chat/completions` | `http://127.0.0.1:<随机空闲端口>` |
| `CAREER_LAB_MODEL` | 固定模型版本名 | `controlled-mechanism` |
| `--provider` | 正式入口选择的提供方 | `openai`／`local` |

`openai` 装配调用 `OpenAICompatibleModel.from_key_file(..., retries=0)`。生成器也要求 `retries=0`；队列以不可自动重试的 handler 注册。key 不在提示词、请求正文、返回 JSON、数据库或生成记录中。不要把 key 值写进上述命令或共享文档。

真实 provider、模型名、key 交付方式和预算由负责方确定；本说明不授权真实付费调用。测试服务仅用于机制验证，已经停止，不能继续使用其临时地址。

## 已实跑的启动与回退

在仓库根、锁定的 Python 3.12 环境中运行。API 与 worker 必须使用相同数据库和环境变量。下列 CLI 参数已由 `runs/local/082/cli-smoke/check.py` 实际执行；该脚本建立临时 key 和本地假服务，保存实际 argv，并只停止自己启动的进程。

```sh
uv run --locked python -m career_lab.cli serve --host 127.0.0.1 --port 19822 --database-url sqlite:///runs/local/082/cli-smoke/runtime.db --provider openai
uv run --locked python -m career_lab.cli worker --once --database-url sqlite:///runs/local/082/cli-smoke/runtime.db --provider openai
```

这些命令的前提是已设置上述三个环境变量。`--once` 处理至多一个排队任务，适合验证；本次配置切换 CLI 冒烟只核对启动、健康检查和空队列退出，实际模型调用另由下节的正式 API 测试证明。

停止自己运行的 API／worker 后，以同一数据库重新启动 local；不要终止其他工作线的服务。

```sh
uv run --locked python -m career_lab.cli serve --host 127.0.0.1 --port 19822 --database-url sqlite:///runs/local/082/cli-smoke/runtime.db --provider local
uv run --locked python -m career_lab.cli worker --once --database-url sqlite:///runs/local/082/cli-smoke/runtime.db --provider local
```

回退不改写旧回复、旧测试或反馈。排队的助手生成请求固定 provider、模型、地址指纹、提示版本、语言和配置；重启后身份不同会返回 `assistant_model_changed`，不调用新模型。需要新条件时显式发起新测试。

## 怎样核验切换

以下命令均已执行。它们不需要真实 key，不访问付费服务。

```sh
uv run --locked pytest -q tests/expansion_v3/w02/test_generation_flow.py --basetemp=.pytest_cache/tmp-082
uv run --locked pytest -q tests/integration/test_provider_switch.py --basetemp=.pytest_cache/tmp-082-provider
uv run --locked pytest -q tests/expansion_v3/w02/test_generation_display.py --basetemp=.pytest_cache/tmp-082-display
```

- 生成模块：标准 `tests.create → Worker → tests.list`，保留问题、请求／实际配置、索引、候选和引用；候选外、未来、私有引用整条拒绝。模型运输仅为受控替身。正式工厂已透传模型；local 模式返回 `assistant_model_unavailable`，零调用。
- 正式提供方切换：使用 `create_runtime_app(provider="openai")` 和临时 HTTP 服务；每种语言，助手、同事回复、单项 Judge 各调用一次；助手另覆盖 deepseek。HTTP 错误／坏 JSON 分别验证两条路径，恢复读取不再调用。故障时反馈保留作品和待核验状态，不转成业务判错。
- worker 中断：在运输边界模拟进程终止，再让真实队列过期并接管；第二个 worker 不再调用。原问题可从 `requests.read` 回读。显式另发请求产生新尝试。
- 密钥检查：测试随机产生 key，仅在临时 key 文件与 Authorization 头使用；扫描 SQLite 主文件／WAL、响应、请求正文和日志，断言没有该字符串。测试 key 不参与 fixture 对象的 repr。
- 组件显示：Vite 实际加载 `test-set-view.js`，检查中英模式、引用版本、有效配置展开及原记录不变。此证据不代表宿主元数据或正常浏览器生成链已接通。

## 状态与历史记录

| 记录状态 | 含义 |
|---|---|
| `extractive` | 确定性原文抽取；旧配置省略 generator 时仍为此默认行为 |
| `llm` | 所配置适配器实际返回且引用全部通过候选校验；回答仍待核验 |
| `unavailable` | 助手没有安装可调用模型，问题与配置已保存，调用数为零 |
| `failed` | 生成或校验失败；没有候选时也保留具体规则原因，不能误标“未配置模型” |

生成记录使用独立 `assistant_execution` 对象，和原 `TestResultV2` 在同一 Mutation 中保存；`tests.list` 仅在有这类记录时附加 `generations`。原测试 DTO、旧抽取返回形状与既有发布包不改写。`AssistantConfig.generator` 是唯一共享契约增量，默认值在序列化时省略，旧对象字节与 hash 保持。

测试台只展示单次记录提供的实际模式和有效配置。当前宿主未透传这些字段时显示“模式信息暂不可用／本次有效配置暂不可用”；缺少界面数据不代表服务端没有保存，不能用当前全局模型设置推断历史执行。生成失败保留原问题、旧结果与具体错误；页面读取不触发新模型调用。

## 公共冻结与装配

`AssistantConfig.generator` 是唯一新增的契约字段，类型为 `extractive|llm`，可选、默认 extractive；默认值仍省略于序列化。新公共 revision 为 `expansion-v3-a2fb5d317ece34100c29840fb603b93b67ccdcbe16b40e23e931abb3e3ad4590`，previous 链接原 `expansion-v3-7f64f17784ad7756fefc53682954b1318bddb58eecdc5dbe645f3187cbc321ed`。标准导出后沿现有 `without_provenance` 兼容方式保留 schema，旧 examples 字节不变；原 documents／review_fixes 保全。依赖该公共 manifest 的工程师契约由标准导出器在新目录生成后同步。错误码目录补收既有代码中已有的代码，未新增这些业务行为。

`build_registry` 仅用三行构造参数透传已配置模型；`LocalRoleModel` 映射为 None。当前两类冻结测试已通过，包括 v1 场景、契约和旧研究冻结原字节检查。当前契约保护清单只重钉此次获准替换的11项产物；历史冻结、场景包和所有旧实例保留，原公共及工程师冻结目录另有原件归档。

080允许各线在自己的分支重生成冻结，最终合并结果由080再次重生成；本分支 revision 不替代最终组合身份。

## 留给宿主与公共存储的接缝

| 责任接点 | 最小改动与原因 |
|---|---|
| 092：v4 数据宿主／`api/vertical_reads.py::timeline` | 将单次 `assistant_execution` 关联到 test，并传出 `run.generation` 与测试结果内的 `config.effective`；抽取按该次配置识别。同时承接异步 `tests.create` 原请求恢复、队列结果和模式选择。 |
| 093：公共存储的派生对象授权 | 承认 `assistant_execution` 和已授权 test 的不可变派生关系，并在窄授权读取中复核全部候选依赖。当前 unknown kind 不能用于 scoped derivative；本线对 `allowed_objects` 有限制的 llm 测试继续在调用前返回 `assistant_scoped_generation_unavailable`。 |

这两处按080续行裁定保持未接通，不由本线越界实现。真实语义质量也不能由回环服务验证代替。

## 验证证据的范围

续行定向覆盖生成27项、provider14项、renderer1项、公共freeze2项及工程师契约28项。完整门禁必须取得 `/private/tmp/claude-501/gate.lock` 后执行；最终结果、逐ID对照及任何负载型超时的三次重跑记录见续行回执 `runs/local/082/finish/receipt.json`。

此前无锁轮次按080指示中止，其旧失败／部分进度不作为续行完整门禁通过证据；历史日志仍保留。此前固定反馈／原语义18项、正常v4英文八步及中英390px组件检查通过，中文曾在反馈等待阶段超时。宿主未接通的生成界面仍不据这些结果称完成。
