# RoleCraft

**RoleCraft 是面向 AI 产品经理（AIPM）的工作模拟与证据反馈项目。** 用户在有业务目标、约束和信息差的空间中自主组织工作，与经理、业务负责人、技术负责人三位同事协作，使用自己的 Agent，形成作品、试错，并依据结果调整判断。当前场景是企业知识助手的试点决策，界面与场景都支持中英文。

本文说明 `main` 上已合并源码的能力、运行方式和检查入口。接手开发先读 [交接说明](docs/HANDOVER.md)。本文命令是复现说明，新环境安装后仍需按「检查与门禁」实跑确认。

## 产品原则

- 用户决定问题、事项和优先级；阅读、对话、写作、测试、求助与修订可以交错，允许犯错、求助或暂时没有方向，不强制固定能力顺序。
- 过程允许多种作品。最终决定需要覆盖用户范围、知识范围、容量、更新政策、兜底方式、工作项、验收测试、成功指标与退出条件；这些业务语义不限定唯一表单或创作顺序。
- 三位同事有合作意愿，按各自职责、已知信息和权限帮助用户；对业务判断多用简短追问引导，不代替用户给出本案解法，也不因施压虚构事实、批准资源或透露隐藏内容。
- 预览与实际生效分开：系统可预览条件性的业务结果，但只有实际分享、申请、批准或执行才改变业务状态。保存、上传、预测、批准和生效分别记录。
- 自带外部 Agent 是通用协作入口：读取获授权的工作区、回传作品并得到反馈。回传、采用、执行、验证和业务批准分别记录；不开放任意代码执行。
- 评价看判断是否有依据，不评结论选择。先识别作品用途再定适用项；不给单一总分，只显示规则已定标部分的分数区间。模型输出一律是建议、不计分；Agent 产物或一次失误不能直接证明用户的独立能力。
- 分工：数据、标注、训练、调参与模型效果由技术负责方完成；本仓库负责产品与场景机制、接口、运行记录与授权导出、模型注册与消费接入、版本与失败状态、界面与验证。

## 现在能做什么

- **工作台 v4**（唯一用户界面，中英双语）：工作板、事项工作台、资料、测试台、作品（Markdown、测试作品、调查工作纸）、动态记录。细节见[前端说明](apps/web/README.md)。
- **场景**：知识助手试点主场景，以及两个审核过的补练变体（期限提前到第 5 天；容量收紧到 15 人）。新会话创建时固定工作语言与评价标准版本；评价标准切换前的旧会话只读保留。
- **三位同事**：按权限视图回复、合作式帮助与追问；资源申请、协商与审批按场景规则处理。
- **知识助手**：按试点配置检索材料并测试，记录来源与索引版本；源文档更新不会自动刷新旧索引。默认抽取式回答；配置 ASSISTANT 模型槽后可选生成式回答，界面标「模型生成 · 回答待核验」，生成答案不计为规则核实。
- **结果预览**：输入充分时在作品旁预览条件性业务结果、成立条件与操作入口，输入变化后标记过期。
- **提交与反馈**：四种决定（上线、缩小范围上线、附条件暂缓、不上线）均可提交；反馈按 rubric-v2 定稿 14 项给出依据、待核验与补练入口，首屏是规则已定标部分的分数区间与项数覆盖；支持异议补证与修订。
- **模型建议**：服务端配置已登记的模型后，「理由与证据的支持关系」（R2.support）按句给出关系建议与证据按钮，显示注册身份与训练数据身份；合成或未训练权重的登记整块标「合成机制演示」。建议不计分，任何失败只显示为该建议的失败状态，规则反馈照常。
- **外部 Agent**：委托凭据经 HTTP 或 stdio MCP（`python -m career_lab.mcp --config <0600 私有配置>`）读取获授权的工作区并回传作品。
- **工程师路径**：命令行 `career-lab-engineer`（任务包、基线复现、配置提交与复核），见 [W13 手册](docs/data/expansion-v3-w13.md)；没有专用页面。
- **数据与模型接收**：研究授权的会话导出；负责方回传的数据包、线性模型、编码器与融合的登记、复核和一次性 test 打开（见下文）。

没有用户账号、服务端练习列表或跨设备同步；会话凭据保存在浏览器，按域名和端口隔离。尚未公开部署。

## 快速开始

依赖以 `uv.lock` 和 `apps/web/package-lock.json` 为准：Python 3.11 及以上、[uv](https://docs.astral.sh/uv/)、Node.js 22.12 及以上与 npm。默认 `local` 模式不调用外部模型，不需要 API key、GPU 或 Docker。

```sh
git clone https://github.com/yhnapoleon/rolecraft.git
cd rolecraft
uv sync --locked
mkdir -p runs/local/dev
```

`runs/` 由 Git 忽略。每个 checkout 用自己的 `.venv`、`apps/web/node_modules` 与数据库，不复制其他 worktree 的环境、密钥或数据库；终端若设置过指向旧 checkout 的 `PYTHONPATH`，先 `unset PYTHONPATH`。

### 启动工作台

1. 生成双语场景目录（中英主场景与补练变体；不设它时服务只提供中文主场景），并在本机生成一次凭据密钥：

   ```sh
   uv run --locked python -c "import sys; from pathlib import Path; from scripts.regression.published import write_catalog; write_catalog(Path(sys.argv[1]))" runs/local/dev/catalog.json
   (umask 077; python3 -c 'import secrets; print("export CAREER_LAB_CREDENTIAL_KEY=" + secrets.token_urlsafe(32))' > runs/local/dev/credential.env)
   ```

2. API 与 worker 各开一个终端，先载入同一组变量：

   ```sh
   export CAREER_LAB_SCENARIO_CATALOG="$PWD/runs/local/dev/catalog.json"
   export CAREER_LAB_SCENARIO_ARCHIVE="$PWD/runs/local/dev/archive"
   export CAREER_LAB_CREDENTIAL_KEY_ID=local-dev-v1
   . runs/local/dev/credential.env
   ```

   ```sh
   # 终端 1：API（等它完成初始化再启动 worker，避免首次建库争用）
   uv run --locked career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/local/dev/rolecraft.db --provider local
   # 终端 2：worker
   uv run --locked career-lab worker --database-url sqlite:///runs/local/dev/rolecraft.db --provider local
   ```

3. 第三个终端启动前端：

   ```sh
   cd apps/web
   npm ci
   npm run build
   ROLECRAFT_API_TARGET=http://127.0.0.1:18562 npm run preview -- --port 18560
   ```

打开 <http://127.0.0.1:18560/>；Swagger 在 <http://127.0.0.1:18562/docs>。开发模式把最后一行换成 `npm run dev -- --port 18560`（同样设置 `ROLECRAFT_API_TARGET`）。API 与 worker 必须使用同一数据库、同一场景目录、同一凭据与模型配置；改配置后两个都重启。worker 启动时在 stderr 打印每个模型槽的 provider、model 和指纹。

无前端的后端演示（v1 场景，跑完材料、角色回合、政策与索引变化、提交、反馈和回放）：

```sh
uv run --locked career-lab demo --database-url sqlite:///runs/local/demo.db --output runs/local/demo.json
```

## 配置

### 数据库

`--database-url` 或 `CAREER_LAB_DATABASE_URL`，支持 SQLite 与 PostgreSQL。本机 PostgreSQL 用 `docker compose up -d --wait` 启动（端口 55439，账号仅供本地开发），连接串为 `postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab`。`docker compose stop` 停库并保留数据卷。

### 凭据密钥

| 变量 | 要求 | 用途 |
|---|---|---|
| `CAREER_LAB_CREDENTIAL_KEY_ID` | 1–64 位字母、数字、`_` 或 `-` | 密钥标识，记入派生凭据 |
| `CAREER_LAB_CREDENTIAL_KEY` | 至少 32 字节 | HMAC 派生密钥 |

签发或恢复外部 Agent 委托、参考 Agent 凭据、快照恢复与补练新会话时使用；缺少或不合规时这些操作返回 503 `credential_derivation_unavailable`。serve、worker 与 CLI 使用同一组值，更换后已派生的凭据不能再恢复。生产没有默认值；密钥不写入命令正文、源码、数据库、日志或回执。测试与门禁注入的是不可用于部署的测试值。

### 四个模型槽

| 槽 | 用途 |
|---|---|
| ROLES | 三位同事 |
| JUDGE | 语义 Judge |
| SUPPORT | 支持核验（未设 provider 时整体沿用 JUDGE） |
| ASSISTANT | 知识助手生成 |

- 每槽变量：`CAREER_LAB_<SLOT>_PROVIDER`（local、deepseek、openai、openai_compatible）、`_KEY_FILE`、`_BASE_URL`、`_MODEL`、`_MAX_TOKENS`（缺省 512）、`_TIMEOUT`（缺省 45 秒）；JUDGE 与 SUPPORT 另有 `_INPUT_BYTES`（缺省 64000）。
- 身份只来自一层：槽设了自己的 `_PROVIDER`，就只用本槽的 key 文件、base URL、model，未设项取该 provider 自带缺省（DeepSeek 为 `ds.txt`／`https://api.deepseek.com`／`deepseek-chat`，OpenAI 为 `openai.txt`／`https://api.openai.com/v1`／`gpt-4.1-mini`）；没设 provider 的槽整体沿用共用的 `--provider`、`CAREER_LAB_KEY_FILE`、`CAREER_LAB_BASE_URL`、`CAREER_LAB_MODEL`。共用 key 文件不会带到设了自己 provider 的槽；没设 provider 却设了身份变量时拒绝启动。预算变量可按槽单独设置。
- 本地服务（vLLM、llama.cpp server 等）以 `openai_compatible` 接入；回环地址可以不配 key，此时请求不带 Authorization 头，服务在别的主机上则必须配本槽 key 文件。
- key 文件：任意位置出现独立的 `sk-…` 令牌就用它，否则取第一个非空、不以 `#` 开头的行（至少 8 个字符、不含空白）。key 不入库、不入日志、不进 provenance；`ds.txt`、`openai.txt` 已被 Git 忽略。
- 回退：删掉槽变量后重启 serve 与 worker，即回到共用配置。适配器零自动重试。

```sh
CAREER_LAB_JUDGE_PROVIDER=openai_compatible
CAREER_LAB_JUDGE_BASE_URL=http://127.0.0.1:8000/v1
CAREER_LAB_JUDGE_MODEL=<含 adapter 版本的模型名>
CAREER_LAB_JUDGE_MAX_TOKENS=256
```

### 已登记模型

| 变量 | 用途 |
|---|---|
| `CAREER_LAB_MODEL_REGISTRY` | 注册目录 |
| `CAREER_LAB_MODEL_REGISTRATION` | 关系模型注册的 FileRef JSON（登记命令返回的 `registration` 对象） |
| `CAREER_LAB_MODEL_REGISTRATIONS` | `{"relation": FileRef, "criterion": FileRef}`，与上一项二选一，同时设置拒绝启动；criterion 目前只校验格式、不加载 |
| `CAREER_LAB_MODEL_JOURNAL` | 建议调用记录目录（缺省 `<registry>/journal`） |

注册引用在启动时固定，切换或关闭须重启两个进程；旧反馈保留原身份与内容，读取不重新推理。

## 模型接收与数据交接

负责方按[回传格式 v3 补充包](docs/data/return-v3/README.md)交回产物（fixture v2 冻结包不变），我方登记、复核后由服务端配置消费：

- **登记与描述**：`python -m career_lab.models.v3.registry_cli register`（线性回传、编码器回传按外层清单分派，`--scope synthetic_fixture|external_candidate`）、`register-fusion`（两个已登记分量加 dev 选择记录）、`describe`（打印公开身份）。注册按内容命名、不可覆盖，身份锁定 `src/career_lab/models/**` 等推理闭包与依赖版本，变化后须重新登记。
- **复核**：`python -m career_lab.models.v3.registry_cli verify-return`：dev 逐语言重算指标、按概率容差重载比对（线性 1e-6、编码器 1e-4）、`--fusion-selection` 复算选点；封存 test 只能在批准后一次性打开。
- **数据包与导出**：`python -m career_lab.datasets.v3 validate-handoff` 核验负责方数据包（含封存 test 时只核字节与结构、不解析标签）；`python -m career_lab.datasets.v3 export --live … --relation-units` 在研究授权下导出会话，`--relation-units` 另按产品同一切句规则导出作品单句关系记录。
- **编码器**：登记与加载需 `encoder` extra（torch 2.8.0、transformers 4.57.1、safetensors 0.6.2），建议放在独立环境：`UV_PROJECT_ENVIRONMENT=<另一目录> uv sync --locked --extra encoder`，默认环境不装 torch。

完整命令与拒绝码：[W07 数据导出与回传核验](docs/data/expansion-v3-w07.md)、[W08 模型与实验管线](docs/data/expansion-v3-w08.md)、[回传格式 v3](docs/data/return-v3/README.md)。登记与复核只确认文件、身份和可复现性，不证明训练真实发生或模型质量；正式计分仍需独立人工校准与采用记录。

## 检查与门禁

| 层 | 命令 | 用时 |
|---|---|---|
| 快速检查 | `.venv/bin/python -m scripts.check_fast`（lint ＋ `tests/unit` ＋ `tests/contracts`，不需要浏览器与锁） | 约 1.5 分钟 |
| 定向＋逐 ID | 改动相关的测试文件或测试 ID；`pytest --collect-only -q` 收集全部测试 ID，与基点比较缺失须为 0 | 视范围 |
| 完整门禁 | `CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.run --output <新目录> --browser`，再跑 `python -m scripts.regression.browser --suite model-flows --output <新目录>`；可选 encoder 检查 | 约半小时以上 |

完整门禁包括 lint 增量、后端全部测试、前端 Vitest、72 项状态回归、构建、对 `tests/regression/test-baseline.json` 的逐 ID 比较、发布字节保护、MCP 双语与中英浏览器流程。同一台机器一次只跑一套，输出目录必须是新的。锁、端口、基线追加与可选检查见[交接说明](docs/HANDOVER.md#检查与门禁)。CI 在每个 PR 与 push main 时跑核心门禁（不含浏览器），结果不拦合并；正式合并证据是本机完整门禁。PostgreSQL 集成测试需设 `CAREER_LAB_TEST_PG`。

## 课程实验 v2（受控合成数据，历史记录）

10/3 冻结的受控实验 v2：1,152 条中文 G0 样本（6 类能力、24 个作者定义的逻辑结构，train/dev/test 576/288/288），关系三分类与证据选择。

| 候选 | dev Macro-F1 | test Macro-F1 |
|---|---:|---:|
| TF-IDF＋逻辑回归 | 0.5455 | 0.4275 |
| 字符特征＋MLP | 0.3692 | 0.3587 |
| 概率融合 | 0.5455 | 0.4275 |
| 有限规则＋模型 | 0.7076 | 0.6496 |

融合权重在 dev 上选为 0，没有增益；混合模型 test 误扣分率 33.3%，未达自动评分门槛。这些是程序可验证的合成结果，24 个逻辑模板不代表 24 个独立真实场景。完整指标与复现见[结果报告](docs/reports/controlled-v2-results.md)与[复现手册](docs/data/experiments-v2-runbook.md)；生成器拒绝覆盖已有目录，已看过的 test 不能再作未见选型集。真实标注数据与训练由技术负责方交付。

## 项目结构

```text
apps/web/         工作台 v4（唯一用户界面）
src/career_lab/
  contracts/      场景、动作、证据、评价与公开契约（v2）
  scenarios/      场景包加载、状态转换、权限投影与重绑
  storage/        事务、事件、快照、凭据与对象存储
  runtime/        角色回合、模型槽与适配器
  jobs/           后台任务、租约与 worker
  assistant/      检索、测试与提交
  evidence/       固定时点证据组装与输入隔离
  rubrics/        规则反馈、rubric-v2、分数区间与 Judge
  models/         模型注册、回传复核、按句建议与融合
  datasets/       授权导出、负责方数据包核验与历史受控数据
  delegations/    外部 Agent 委托；mcp/ 为 stdio MCP
  engineer/       工程师路径命令行
  api/            FastAPI 接口与装配
scenarios/        场景包、补练变体、审核记录与安装包
scripts/          门禁、冒烟、实验与复现入口
tests/            单元、契约、集成、回归与可选 encoder 检查
docs/             设计、契约、数据手册、计划与报告
```

## 文档入口

- [交接说明](docs/HANDOVER.md)：起服务、检查与门禁、契约重导出、生成文件、后续清单。
- [前端说明](apps/web/README.md)、[前端风格](docs/design/frontend-style.md)、[接口需求](docs/design/frontend-interface-requirements.md)。
- [技术设计](docs/design/career-training-technical-design.md)、[实施计划](docs/plans/career-training-implementation-plan.md)、[用户试用方案](docs/user-study/protocol.md)。
- 公开契约：`docs/contracts/expansion-v3/`（schema、OpenAPI、错误码）与 `docs/contracts/engineer-review-v1/`。

本仓库包含源码、场景、配置、复现脚本与报告；本地密钥、数据库、环境、原始数据、个人标注记录与课程原始资料不上传。
