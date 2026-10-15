# 交接说明

写给第一次打开本仓库的 Agent 与开发者：怎样起服务、学员的 Agent 怎样连接、怎样用继续码找回练习、怎样检查、契约怎样重导出、哪些文件不能手改、模型回传包在哪、后续还有什么。项目介绍见 [README](../README.md)；凭据密钥见 [W07 · 研究授权与真实会话导出](data/expansion-v3-w07.md#研究授权与真实会话导出)，模型槽与已登记模型的配置变量见 [W08 · 模型槽配置](data/expansion-v3-w08.md#模型槽配置)与 [W08 · 服务消费与回退边界](data/expansion-v3-w08.md#服务消费与回退边界)。

## 起服务

- 一个 checkout 一套环境：`uv sync --locked` 建 `.venv`，`apps/web` 里 `npm ci`。需要编码器时另建环境：`UV_PROJECT_ENVIRONMENT=<另一目录> uv sync --locked --extra encoder`，默认 `.venv` 不装 torch。
- 三个进程：API（`career-lab serve`，下文用端口 18562；不加 `--port` 时是 8000）、worker（`career-lab worker`）、前端（`npm run preview` 或 `npm run dev`，下文用端口 18560，`ROLECRAFT_API_TARGET` 指向 API）。完整命令见下面的[启动工作台](#启动工作台)。
- API 与 worker 共用同一数据库、`CAREER_LAB_SCENARIO_CATALOG`（不设只有中文主场景）、`CAREER_LAB_SCENARIO_ARCHIVE`、凭据密钥（`CAREER_LAB_CREDENTIAL_KEY_ID`、`CAREER_LAB_CREDENTIAL_KEY`）与模型配置。改任何一项两个都重启。
- 凭据密钥没有缺省值：`CAREER_LAB_CREDENTIAL_KEY_ID`（1–64 位字母、数字、`_` 或 `-`）与 `CAREER_LAB_CREDENTIAL_KEY`（至少 32 字节）缺一或不合格时，服务照常启动、能新建练习，但创建 Agent 授权、开始补练、生成和使用继续码都返回 503 `credential_derivation_unavailable`。继续码的校验值用这把密钥计算，换密钥或密钥 ID 会让全部继续码失效（见[找回练习](#找回练习继续码)）。
- 新 SQLite 库先启动 API，初始化完成后再启动 worker。验收用新数据库与新端口；并行的几条工作线各用自己的端口。
- 更新代码后（例如合入新的 PR）先 `npm run build` 再起 `npm run preview`：preview 只发 `dist/`，不重建仍是旧界面。`apps/web/public/workbench-engine.js` 不经打包、按原文件名发出，靠 `index.html` 里的 `?v=` 参数（现为 `20261014`）让浏览器换掉缓存；改这个文件时同时改这个参数。
- 默认 `--provider local` 不调用外部模型、不需要 key。真实 provider 与费用须另获授权。

### 启动工作台

`runs/` 由 Git 忽略。终端若设置过指向旧 checkout 的 `PYTHONPATH`，先 `unset PYTHONPATH`。

1. 生成双语场景目录（中英主场景与补练变体；不设它时服务只提供中文主场景），并在本机生成一次凭据密钥：

   ```sh
   mkdir -p runs/local/dev
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

打开 <http://127.0.0.1:18560/>；Swagger 在 <http://127.0.0.1:18562/docs>。开发模式把最后一行换成 `npm run dev -- --port 18560`（同样设置 `ROLECRAFT_API_TARGET`）。worker 启动时在 stderr 打印每个模型槽的 provider、model 和指纹。PostgreSQL 用 `docker compose up -d --wait`（端口 55439，账号仅供本地开发），连接串 `postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab`，经 `--database-url` 或 `CAREER_LAB_DATABASE_URL` 传入。

## 学员的 Agent 怎样连接（MCP）

学员在 Agent 面板创建授权后，连接卡给出端点和 Claude Code、Codex 各一条命令，不需要安装本项目的 Python 包。令牌不在页面上明文显示（命令里是 `••••••`），只在这一页的内存里，复制或下载时才取出；点“完成”、离开练习（含切换到别的练习、关闭或刷新页面）、到期或撤销后清除，在别处撤销的，下次读取授权记录时清除。

- **端点**：`POST <前端>/api/sessions/<session_id>/mcp`（经前端代理，连接卡用这个），或直连 `<API>/sessions/<session_id>/mcp`。实现在 `src/career_lab/mcp/streamable_http.py`，由 `mount_delegations` 挂载，不进公开 OpenAPI 契约。
- **协议**：MCP 2026-07-28（每个请求带 `_meta` 版本，HTTP 头 `MCP-Protocol-Version`、`Mcp-Method` 与 `tools/call` 的 `Mcp-Name` 须与请求体一致）和 2025-11-25（先 `initialize`，之后每个请求带 `MCP-Protocol-Version: 2025-11-25`）。只回 JSON，不发会话号、不开 SSE；GET、DELETE 回 405。
- **认证**：令牌只走 `Authorization: Bearer`，带查询串的请求回 400。只接受委托给外部 Agent 的令牌，学员自己的会话令牌也回 401。令牌无效、过期、撤销都回 401，`error.data.code` 写明是哪一种。每次工具调用都在进程内走与 stdio 相同的公开路由和权限检查；`session_id` 可以省略，缺省为授权所属会话，给出时必须一致。
- **只在本机**：带 `Origin` 的请求（浏览器来源，含同源）和 Host 不是 127.0.0.1、localhost、[::1] 的请求一律 403。对外部署前必须改：Host 校验换成真实域名，全程 HTTPS，并重新评估令牌怎样交到 Agent 手里（见[对外部署前必做](#对外部署前必做)）。
- **限流**：同文件的 `HttpLimits` 集中定义。同时受理 16 个请求，再多回 429；同时执行 4 个，其余排队等候；每个授权突发 30 次、持续每秒 10 次，超出回 429；两种 429 都带 `Retry-After`。请求体上限 1 MiB，超出回 413。计数在 API 进程内，多进程部署时各进程分别计数。
- **日志**：沿用请求日志白名单，只记路由模板、状态和安全码（如 `mcp_unauthorized`、`mcp_browser_refused`），不记请求头、请求体和令牌。
- **连接卡生成的命令**：
  - Claude Code：`claude mcp remove rolecraft -s local >/dev/null 2>&1; claude mcp add -s local --transport http rolecraft '<端点>' --header 'Authorization: Bearer <令牌>'`。local 范围：写进 `~/.claude.json` 里运行命令时所在项目目录的条目，令牌明文保存，只在该目录启动的 Claude Code 生效；不写仓库里的 `.mcp.json`。授权撤销或到期后旧条目还在，Claude Code 每次启动都会报这个服务器连接失败，要用 `claude mcp remove rolecraft -s local` 删掉（重新授权后再运行整条命令，会替换旧条目）；它提示的 OAuth 方式对本服务不适用。
  - Claude Code 不改配置的用法：把 `{"mcpServers":{"rolecraft":{"type":"http","url":"<端点>","headers":{"Authorization":"Bearer <令牌>"}}}}` 存成只有本人可读的 JSON 文件（`chmod 600`），用 `claude --mcp-config <文件>` 启动（只用这一个服务器时再加 `--strict-mcp-config`），用完删掉文件。不写 `~/.claude.json`；真实客户端测试用的就是这种方式。连接卡目前不生成这份 JSON，卡上“下载配置文件”是给下面本机 Python 方式的格式（`api_url`、`session_id`、`token`），Claude Code 不能直接用。
  - Codex：`ROLECRAFT_MCP_TOKEN='<令牌>' codex -c 'mcp_servers.rolecraft={ url = "<端点>", bearer_token_env_var = "ROLECRAFT_MCP_TOKEN" }'`（在这个终端启动已连好的 Codex，不写配置文件）。
  - Codex 桌面版和其他客户端：在 `~/.codex/config.toml` 的 `[mcp_servers.rolecraft]` 写 `url` 与 `http_headers = { Authorization = "Bearer <令牌>" }`；其他支持 Streamable HTTP 的客户端同样填端点和这个请求头。
  - 本机 Python 方式仍可用：下载的配置文件先 `chmod 600`，再 `python -m career_lab.mcp --config <文件>`。加载器只接受本人所有、组和其他用户没有任何权限的普通文件，否则退出并在 stderr 打印 `mcp_configuration_or_transport_unavailable`；浏览器保存的下载文件一般是 644，所以这一步不能省。
- **测试**：`tests/integration/test_mcp_streamable_http.py`（协议两代、认证、跨会话、浏览器来源、头体校验、限流、日志）、`tests/e2e/test_mcp_http_live.py`（真实 `career-lab serve` 进程，中英）、`scripts/regression/mcp.py` 的 `exercise_http`（完整门禁经前端代理跑中英）、`apps/web/tests/regression/mcp-connection.mjs`（连接卡到回传作品、撤销）。这些都用脚本化 HTTP 客户端，不运行真实的 Claude Code 或 Codex。真实客户端只手工测过：2026-10-15 用 Claude Code 2.1.296（`claude -p` 加 `--mcp-config`）中英各走一轮，列工具、读委托与资料、回传作品都通过；新运行时协商 2026-07-28，设 `MCP_SDK_GENERATION=v1` 走 2025-11-25，也通过；含点号的工具名在客户端显示为下划线（如 `mcp__rolecraft__work_products_create`），调用时换回原名；撤销后在连接阶段报 `AUTH_HEADER_REJECTED`，带 `credential_revoked_or_invalid`。Codex 与其他客户端没有实测。经过见回执「164 真实 Claude Code MCP 往返」（项目本地，见[依据文档](#依据文档)）。
- **结果体积**：`observation` 与 `tools` 两个工具的结果目前各 12 万字符以上，超过 Claude Code 单次 5 万字符的上限，会被转存成本地文件，Agent 要有读文件或本机命令权限才看得到（见[后续清单](#mcp-结果过大)）。

## 没有负责方产物时怎样演示模型建议

仓库里没有负责方回传，fixture v2 也不在仓库里。要在正常入口看到「理由与证据的支持关系」下的「合成机制演示」，先用 model-flows 的构造器登记一份合成线性回传（关键词构造的权重，从未训练，scope 为 `synthetic_fixture`），把三个环境变量写进一个文件：

```sh
OUT=runs/local/demo-model   # 新目录，不能已存在
OUT=$OUT uv run --locked python -c '
import os, shlex
from pathlib import Path
from scripts.regression.model_flows import build
out = Path(os.environ["OUT"]).resolve()
phase = build("linear", out)
for key, value in phase.environment(out / "journal").items():
    print("export " + key + "=" + shlex.quote(value))
' > $OUT.env
```

然后在 API 与 worker 两个终端都先 `. runs/local/demo-model.env`，再按上面的[启动工作台](#启动工作台)起服务；worker 启动时 stderr 打印四个槽。新建练习、写一份含「有据可查」或「豁免」的作品并提交，反馈页就有逐句建议、证据按钮与「合成机制演示」。把 `"linear"` 换成 `"fusion"` 得到线性×线性融合（alpha 0.75）。这只演示接收与显示的机制，标签不是模型判断。

## 找回练习（继续码）

没有账号体系时，换浏览器、换设备或清了缓存的人用继续码回到原练习：在练习右上角「⋯ → 继续码…」生成，在另一台设备的「AI 产品经理」页「用继续码找回练习」输入（首页「有继续码？」直达）。服务端为这台浏览器另签一份本人凭据，作品、测试、对话和反馈从服务端读回。

- **依赖凭据密钥**：校验值用 `CAREER_LAB_CREDENTIAL_KEY` 计算并记下密钥 ID，库里只有校验值。缺密钥时生成与找回都返回 503 `credential_derivation_unavailable`；更换密钥或密钥 ID 后所有继续码失效（找回回 404，和错码相同），需在还能打开练习的浏览器里换新码。
- **依赖场景**：找回时先按会话绑定在运行中的场景里找，再到本部署 `CAREER_LAB_SCENARIO_ARCHIVE` 里的归档包找；都找不到返回 409 `continue_code_scenario_unavailable`，不签发凭据。只在归档里找到的练习能找回，但只读。换部署时保留 archive 目录。
- **安全约定**：码为 20 位 Crockford Base32（100 位熵），只在生成时显示一次，不进地址、日志和浏览器存储。找回每个来源 15 分钟内最多 10 次（成功也计）；来源是直连的对端：`career-lab serve` 启动 uvicorn 时固定 `proxy_headers=False`（`src/career_lab/cli.py`），不认 `X-Forwarded-For` 等转发头，目前没有开关。经本机 Vite 代理时所有请求共用一个计数，所以本机反复验证要隔 15 分钟或换新库。放到反向代理后对外部署前，须改成只信任该代理地址的转发头（见[对外部署前必做](#对外部署前必做)），否则所有人共用代理那一个计数。
- **换码只作废码**：已经打开过的浏览器和它们排队中的任务照常（任务按排队时的凭据执行，收回会让它们失败且无法重试）。目前没有“让其他设备退出”，对外部署前需补（见[对外部署前必做](#对外部署前必做)）。
- **存储**：`v4_continue_codes`（每个练习一行：校验值、密钥 ID、代数、签发者凭据、生成时间）与 `v4_continue_code_attempts`（来源地址的 HMAC、窗口起点与次数）两张独立表，不改 v2 冻结表；服务启动时自动建表，旧库也会补上，不需要迁移。两张表不进研究导出（导出只读会话快照，见 [W07 · 导出产物](data/expansion-v3-w07.md#导出产物)）。路由、DTO 与错误码见契约 `module-interfaces.md`「继续码找回练习」。
- **找不回的**：只存在原浏览器里的未保存草稿、待确认请求记录、测试的事项归属与预期和诊断笔记、Agent 授权显示名、补练来源说明，以及依据选择器里“读过的资料段落”（在新浏览器里重新打开资料后才列出；测试运行与作品版本从服务端读，不受影响）。界面在找回后用一句话提示。
- **测试**：`tests/regression/test_continue_codes.py`、`tests/unit/test_continue_codes.py`、`apps/web/src/features/practice-recovery/*.test.ts`；浏览器门禁在 published-flows 之后多跑一轮 `apps/web/tests/regression/practice-recovery.mjs`（中文减少动效、英文默认动效，每轮用 4 次找回）。

## 检查与门禁

| 层 | 什么时候 | 命令 |
|---|---|---|
| check-fast | 每次提交前 | `.venv/bin/python -m scripts.check_fast` |
| 定向＋逐 ID | 每次交付 | 改动相关的测试文件或 `::ID`；再做逐 ID 比对（见下），须 `Regression gate: 0 problems` |
| 持锁完整门禁 | 合并候选 | 见下 |

**check-fast**：依次跑 `python -m scripts.regression.lint`（前端 biome 新增项、相对基点改动的 Python 文件做 ruff check 与 format check）与 `pytest tests/unit tests/contracts`。去掉调用方的 `CAREER_LAB_*` 与 `PYTHONPATH`，pytest basetemp 用私有临时目录，不与同一 checkout 里的其他运行共用；不需要浏览器与锁。每步打印结果与耗时，任何一步失败退出码为 1。2026-10-12 本机（Apple Silicon，负载约 3.5）实测：lint 23 秒、测试 58 秒（1554 项通过），合计约 1.5–2 分钟（82 秒；负载约 10 时约 97 秒）。完整门禁里的 `test_rule_identity` 依赖 PATH 上的 `ruff`，所以完整门禁用 `uv run --locked …` 或先激活 `.venv`。

**逐 ID 比对**：把前端 Vitest 的 JSON 报告和后端 junit 一起交给 `scripts.regression.compare`。它对照 `tests/regression/test-baseline.json` 报出缺失、失败和新增跳过，遇到重名的测试 ID（例如 `it.each` 标题用 `%o` 打印对象，几个用例同名）直接报错，并核对受保护的发布文件字节。只拿 `pytest --collect-only` 比集合不算：它不含前端 ID，也看不出重名。后端 junit 要来自全部后端测试，并且用门禁的环境（凭据密钥、`W02_W05_R10_ARCHIVE` 等），否则会多报缺失或新增跳过，所以直接不带 `--browser` 跑一遍 `run`（输出目录必须不存在；本机后端全量约半小时），它的最后一步就是这项比对：

```sh
uv run --locked python -m scripts.regression.run --output runs/local/ids-$(git rev-parse --short HEAD)
```

前端可以先单独比（十秒左右）：

```sh
OUT=runs/local/ids-frontend-$(git rev-parse --short HEAD); mkdir -p "$OUT"
(cd apps/web && node_modules/.bin/vitest run --reporter=json --outputFile="../../$OUT/frontend.json")
uv run --locked python -m scripts.regression.compare --frontend "$OUT/frontend.json"
```

**完整门禁**（输出目录必须不存在；同一台机器同一时间只跑一套）：

```sh
OUT=runs/local/gate-$(git rev-parse --short HEAD)
CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.run --output "$OUT" --browser
CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.browser --suite model-flows --web-port 19770 --api-port 19772 --output "$OUT/model-flows"
```

- `run` 依次跑 lint、后端全部测试（junit）、前端 Vitest、72 项状态回归、构建、逐 ID 比较（含发布字节保护），`--browser` 再跑 MCP 双语（stdio 与 Streamable HTTP）与中英 published-flows（固定用缺省端口 19660／19662）。下面说的输出目录指浏览器这一步的目录：`run --browser` 时是 `$OUT/browser/`，单独调用 `scripts.regression.browser` 时是它的 `--output`。published-flows 全程模拟「减少动效」，之后同一套服务再跑一轮默认动效的 `default-motion`（中英：打开委托、返回、打开资料、返回、再打开另一份资料，每步限时求值并核对标题），结果在输出目录的 `default-motion.json`。单独调用 `scripts.regression.browser` 时可用 `--web-port`／`--api-port` 换端口；model-flows 紧跟在 `run --browser` 之后，所以换用 19770／19772，刚释放的 19660／19662 可能还没回收，启动前的端口检查会报 `Address already in use`。机器设了系统 HTTP 代理时，先设 `NO_PROXY=127.0.0.1,localhost`，否则就绪检查会把回环请求交给代理。
- model-flows 默认三段：`linear`、`fusion`、`slots`（回环 JUDGE 与 ASSISTANT 槽）。可选段需 encoder 环境：`UV_PROJECT_ENVIRONMENT=<encoder 环境> uv run --locked --extra encoder python -m scripts.regression.browser --suite model-flows --phases encoder hetero --output <新目录>`；`xlmr` 段另需 `ROLECRAFT_XLMR_DIR` 指向本机下载的 XLM-R base（权重放仓库与云盘之外，登记只能是合成机制）。
- published-flows 套件在启动服务前先跑交付前预演卡的真实 DOM 组件检查（`apps/web/src/features/feedback-native/presubmit.vitest.config.ts`：受控页，自起开发服务，任选空闲端口），在 published-flows 之后用同一套服务再跑一轮 `presubmit-flows`（中英，减少动效：新练习直接交付后，反馈页只在规则已定论的未满足项下出"交付时"行；预演卡的位置、计数、措辞、直达、按配置版本的措辞、重开记忆，以及与正式反馈一致），结果与截图在输出目录的 `presubmit-flows/`。最后再跑一轮 `practice-recovery`（中文减少动效、英文默认动效，不点资料卡）：⋯ 生成继续码，另一浏览器档案先遇错码提示再找回同一工作板、不把带来的回复当新消息，换码后旧码被拒，原浏览器输入自己的码只切换过去；结果在输出目录的 `practice-recovery.json` 与 `practice-recovery/`。
- 不在 `run --browser` 里的浏览器检查，改到相关界面时自己跑：
  - `qa-polish`：PR #50 那批界面打磨的逐项检查（检查名是 QA 走查的问题编号 F03–F31），自起自停服务：`CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.browser --suite qa-polish --web-port <端口> --api-port <端口> --output <新目录>`。`QA_CHECKS=F03,F04` 只跑指定项，`QA_MOTION=default` 改用默认动效。
  - 配置与审批（`apps/web/src/features/roles-native/config-approval.browser.mjs`）和依据选择器（`apps/web/tests/regression/evidence-picker.browser.mjs`）不自起服务：先按[启动工作台](#启动工作台)用新库、新端口起一套，再在 `apps/web` 里运行 `CHROME_BIN=<chrome-headless-shell> node src/features/roles-native/config-approval.browser.mjs <前端地址> <新目录> <zh|en> [default]`（中英各跑一次；第四个参数 `default` 改用默认动效，只走设置、申请与交付后的反馈），以及 `CHROME_BIN=<chrome-headless-shell> BASE=<前端地址> OUT=<新目录> node tests/regression/evidence-picker.browser.mjs`（缺省跑中英 × 减少／默认动效 × 主流程与调查工作纸；`LANGS`、`MOTION`、`FLOWS`、`WIDTH` 可缩小范围）。
- 可选 encoder 检查：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 <encoder 环境>/bin/python -m pytest -q tests/optional_encoder/check_encoder_v3.py tests/optional_encoder/check_local_encoder.py tests/optional_encoder/check_fusion_registration.py tests/optional_encoder/check_return_v3_plugin.py tests/optional_encoder/check_xlmr_smoke.py`（最后一个需要 `ROLECRAFT_XLMR_DIR` 指向下载的 XLM-R 目录，共 34 项；`check_return_v3_plugin.py` 的 11 项按负责方的用法跑 v3 补充包的编码器参考脚本：`predict` 行经 `verify-return` 重载一致、弃权与我方加载器相同、`seal` 的 `artifact_roles` 过 validate-handoff、序列分类模型的保存配方）；XLM-R 冒烟为 `<encoder 环境>/bin/python -m scripts.smoke.xlmr_base --model-dir <目录> --revision <40 位> --out <新目录>`。这些只证明加载与机制，不是质量证据。
- **锁**：门禁对 CPU 负载与端口敏感。本机约定先对机器上登记的同一个锁文件取 `fcntl.flock` 独占锁再跑（macOS 没有 `flock` 命令），例如 `python3 -c 'import fcntl, subprocess, sys; f = open(sys.argv[1], "a"); fcntl.flock(f, fcntl.LOCK_EX); sys.exit(subprocess.call(sys.argv[2:]))' "$GATE_LOCK" sh -c '<上面三行>'`。排队时不另起第二套。
- **基线**：`tests/regression/test-baseline.json` 是逐 ID 基线，只追加、不删改；新测试 ID 在全部合入后由收口线一次追加，并在提交说明里列来源与数量。平台差异只写进 `test-baseline-overrides.json`，每条带原因。
- CI 在 PR 与 push main 时跑核心门禁（不含浏览器），不拦合并；合并证据以本机完整门禁为准，合入树须与门禁跑过的树相同。

## 契约重导出与重签

公开契约是 `docs/contracts/expansion-v3/`，`revision.txt` 为 `expansion-v3-` 加 `manifest.json` 的 SHA-256。manifest 记录的源码指纹（`export.py` 的 `_implementation_files`）覆盖：

- `src/career_lab/contracts/` 下全部 `.py`；
- `cli.py`；`api/` 的 `app.py`、`v4_extensions.py`、`continue_codes.py`、`vertical_runtime.py`、`vertical_reads.py`、`v4_config.py`、`public_materials.py`、`lifecycle_integration.py`、`evaluation_runtime.py`、`business_record.py`、`registered_models.py`、`reviews_v2.py`、`workspace_integration.py`、`feedback_integration.py`、`role_snapshot.py`、`private_roles.py`、`modules.py`、`v2_routes.py`；
- `runtime/` 的 `model_slots.py`、`model_adapter.py`、`role_snapshot.py`；`jobs/worker.py`、`jobs/repository.py`；`rubrics/registry.py`；`evidence/v2/citation.py`；
- `storage/` 的 `v2_tables.py`、`v2_store.py`、`v2_jobs.py`、`v2_snapshot.py`、`v2_lifecycle.py`、`v2_remap.py`、`object_plans.py`、`reference_graph.py`、`record_invariants.py`；
- 手写文档 `docs/contracts/expansion-v3/` 的 `compatibility.md`、`module-interfaces.md`、`consumer-request-resolution.json`（以文档指纹记录）。

改这些文件就要重导出，只由获准改契约的线做，其他线不碰；同一波有几条获准的线时依次合入，每条在自己的分支里重导出。步骤：

1. 在 `src/career_lab/contracts/v2/manifest_history.py` 的 `MANIFEST_HISTORY` 末尾追加一条：`previous_contract_revision` 写当前 `revision.txt` 的值，`integration_changes` 用新键写清变化。旧记录一字不改。
2. 指纹范围新增文件时，`export.py` 的 `_implementation_files` 与 `tests/contracts/expansion_v3/test_export_reproducible.py` 的 `IMPLEMENTATION_INPUTS` 同步加入。
3. 新增公共模型时（导出的 `schemas/`、`examples/` 多出名字），在 `tests/contracts/expansion_v3/examples-added/` 加一份 JSON，文件名用本次 `integration_changes` 的键（如 `submission-rule-check.json`）：`examples` 写每个新模型名到它首次导出的 example 文件的 SHA-256，另写一句 `source`。`test_model_assembly_contracts.py` 的 DTO-01 据此核对公开模型集合，并要求已发布的 example 字节不变。
4. 生成并核对（`OUT` 为新目录）：

```sh
PY=.venv/bin/python
OUT=runs/local/regen-<标签>
$PY -m career_lab.contracts.v2.export --output "$OUT/a"
$PY -m career_lab.contracts.v2.export --output "$OUT/b"
diff -r "$OUT/a" "$OUT/b"                                   # 必须无差异
$PY -m career_lab.contracts.v2.export --output docs/contracts/expansion-v3
diff -r "$OUT/a" docs/contracts/expansion-v3                # 只应剩 Only in：drafts/ 与三份手写文档
$PY -m career_lab.contracts.v2.engineer_export --output "$OUT/eng-a"
$PY -m career_lab.contracts.v2.engineer_export --output "$OUT/eng-b"
diff -r "$OUT/eng-a" "$OUT/eng-b"
rm -rf docs/contracts/engineer-review-v1                    # 同目录重导出只接受逐字节相同
$PY -m career_lab.contracts.v2.engineer_export --output docs/contracts/engineer-review-v1
cd apps/web
../../$PY src/features/workspace/generate_types.py ../../docs/contracts/expansion-v3/manifest.json --host --output "../../$OUT/ts-raw.ts"
node_modules/.bin/biome format --stdin-file-path=src/contracts-v2.ts < "../../$OUT/ts-raw.ts" > src/contracts-v2.ts
cd ../..
$PY -m scripts.regression.release_identity --check            # 变化应只在 docs/contracts/expansion-v3/ 内
$PY -m scripts.regression.release_identity --refresh
$PY -m scripts.regression.release_identity --check            # 0 problems
```

`--refresh` 按当前字节重算全部受保护文件，会把意外改动一并签进去，所以先 `--check` 看清变化。`tests/contracts/expansion_v3/test_freeze.py` 核对 schema、examples、OpenAPI 与冻结一致，`test_export_reproducible.py` 核对导出确定、发布历史保留与受保护字节不变。随后跑 check-fast 与完整门禁。`main` 在合入前前进时（例如同一波另一条契约线先合入），先合入 `main`，把本线那条还没进 `main` 的历史记录的 `previous_contract_revision` 改为 `main` 当时的 `revision.txt`，再重导出；已进 `main` 的记录一字不改。

## 生成文件，不手改

| 文件 | 由谁生成 |
|---|---|
| `docs/contracts/expansion-v3/` 的 `schemas/`、`examples/`、`openapi.json`、`errors.json`、`manifest.json`、`revision.txt` | `career_lab.contracts.v2.export`；`drafts/` 是历史冻结稿 |
| `docs/contracts/engineer-review-v1/**` | `career_lab.contracts.v2.engineer_export` |
| `apps/web/src/contracts-v2.ts` | `generate_types.py --host` 加 biome 格式化（头注释记 manifest SHA-256） |
| `tests/regression/release-identity.json` | `scripts.regression.release_identity --refresh`；`commit`、`scenarios`、`scope` 不变 |
| `tests/regression/test-baseline.json` | 只追加（见上） |
| `scenarios/` 下场景包、补练变体与安装包 | 场景工具生成，按 hash 受 release-identity 保护；内容改动走场景发布，重绑只用 `python -m career_lab.scenarios.v2.rebind` |
| `docs/data/return-v3/SHA256SUMS` | 包内任何文件改动后重算（`shasum -a 256` 格式，列全包、不列自身），再跑 `python3 -I docs/data/return-v3/check_package.py docs/data/return-v3` |

## 模型回传 v3 包

`docs/data/return-v3/` 是发给技术负责方的补充包，入口 [README](data/return-v3/README.md)：线性回传、编码器回传、融合选择记录、按 split 封存的数据包、v3 预测行、一次性 test 打开，以及参考导出脚本、金标向量与只用标准库的自检脚本。冻结交接包 fixture v2 一字节不变。登记、复核与导出命令见 [W07](data/expansion-v3-w07.md)、[W08](data/expansion-v3-w08.md)。每次打开封存 test 须项目负责人在对话里确认一次，CLI 不接受绕过参数。

发送步骤：按 `SHA256SUMS` 列出的文件逐个复制到发送目录（不要整目录复制：本仓库测试或参考脚本运行可能在 `reference/__pycache__` 留缓存，负责方自检会报清单外文件），复制后在发送目录跑一次 `python3 -I check_package.py .`，再另附 `SHA256SUMS` 自身的 sha256。融合选点规则已内置「证据必选」：融合预测在证据可评的记录上出现无证据的支持或矛盾成功行的网格点没有资格，复算与回传格式检查用同一判定（`models/v3/core.py::evidence_missing`）。

## 后续清单（触发后再派）

| 项 | 触发条件 | 要补的工作 |
|---|---|---|
| 五分类 head 的接收与显示 | 负责方书面答复「五分类走独立 head」 | criterion 线性与编码器注册、五类指标与 `rubric_version` 复核、criterion 预测行格式发布；14 项逐项「模型建议（不计分）」与冲突、未覆盖、待核验状态；model-flows 加 criterion 段。契约可选字段已保留，预计不需二次重导出 |
| Judge SFT 输入格式导出 | 负责方答复「做 SFT」并索取格式 | Judge messages 抽成纯函数（线上 prompt hash 不变），授权导出新增 `judge` 投影（含规则界与声明决定、`PROMPT_VERSION`、不含 gold），W07 手册补命令。模型服务接入已具备：JUDGE 槽配 `openai_compatible` 即可 |
| GRPO | 负责方决定执行 | 我方无接收工作，adapter 同样以 OpenAI 兼容服务接入；未执行时报告如实写「未执行」 |
| R2.support 候选长度 | 产品侧决定候选口径 | 现在候选是整篇材料；XLM-R 实测引用整篇材料时每句都超 512 而弃权。若改为引用片段或按段分块，需同时改证据包投影与证据口径，先定口径再派 |
| `MAX_UNITS` | 部署机 CPU 明显慢于开发机，或一次评审含多个 R2.support 包 | 只改 `models/v3/units.py` 的 `MAX_UNITS`（建议 12），或同包句子合批前向 |
| 契约小修集合 | 下次契约修订 | 启动时端口非法给错误码（`runtime/model_slots.py`，在契约指纹内）、relation 建议绑定 `R2.support`、是否给界面加「推理依赖版本」字段。手写契约文档三处一并改：`compatibility.md` 第 133 行 `GET /objects/material/{id}/{version}` 与第 140 行 `GET /objects/{kind}/{object_id}/{version}` 补上 `/sessions/{session_id}` 前缀（实际路由是 `GET /sessions/{session_id}/objects/{kind}/{object_id}/{version}`）；`module-interfaces.md` 第 292 行标题“交付前规则核对（169）”的内部线号改成日期；`module-interfaces.md` 补 PR #56 的说明：新反馈 `business_response` 的写法与顺序、候选证据顺序与 `input_hash` 的变化、`api/business_record.py` 进源码指纹 |

补做时沿用已保留的测试编号，不替负责方训练、不运行其命令、不新增费用。

### 对外部署前必做

现在只按本机部署设计。对外提供服务前要补下面几项：

| 项 | 现状 | 要补的工作 |
|---|---|---|
| 换继续码时让其他设备退出 | 换码只作废旧码；用旧码打开过的浏览器和它们排队中的任务照常 | 换码时能让凭继续码打开过的浏览器退出（收回派生用途为 `continue-code` 的本人凭据），并定下它们排队中的任务怎么办：收回后这些任务会失败且无法重试 |
| 继续码找回的限流来源 | `career-lab serve` 固定 `proxy_headers=False`，按直连对端计数；放在反向代理后，所有人共用代理那一个计数 | 只信任该代理地址的转发头（uvicorn 的 `proxy_headers=True` 加 `forwarded_allow_ips=<代理地址>`）。`cli.py` 在契约指纹内，改它要重导出契约 |
| 远程 MCP 的 Host 校验与 HTTPS | 只接受 Host 为 127.0.0.1、localhost、[::1] 的请求（`mcp/streamable_http.py` 的 `LOOPBACK_HOSTS`），全程 HTTP；限流计数在单个 API 进程内 | Host 校验换成真实域名，全程 HTTPS；多进程部署时决定限流要不要改成共享计数 |
| 令牌交到 Agent 手里的方式 | 连接卡把令牌放进复制的命令或下载的配置文件，会留在 Agent 配置和命令历史里，最长 60 分钟后失效 | 重新评估令牌怎样交付与保存 |

### MCP 结果过大

- **现象**：经 MCP 调 `tools` 返回 122,076 字符，`observation` 返回 12.4–13 万字符（可见资料片段越多越大；2026-10-15 实测），都超过 Claude Code 单次 5 万字符的上限，被转存成本地文件，Agent 只拿到文件路径，要用读文件工具或本机命令（如 `jq`）去翻；权限收紧时就看不到。服务端说明要求 Agent 先读 `observation`，所以每个 Agent 第一步就会碰到。
- **根因**：`observation` 内嵌完整工具清单（40 个工具的全部参数结构，其中 34 个经 MCP 可用，约 12.2 万字符，占九成以上），`tools` 工具返回的也是这一份；两者都和 MCP 的 `tools/list` 重复。代码在 `src/career_lab/api/delegations_v2.py`（`tools`、`observation` 两个读操作都用 `ToolService.catalogue`）。
- **建议**：只改 MCP 层，公开契约不动：经 MCP 返回 `observation` 时把工具清单换成精简清单（名称、是否可用、不可用原因）或去掉，`tools` 工具同样改成精简清单或不在 MCP 里列出；门禁加一条两者经 MCP 的结果都在 2 万字符以内。不靠 `_meta["anthropic/maxResultSizeChars"]` 放宽上限，那样每次会多塞 3 万以上 token 进上下文。

## 依据文档

以下文档在项目本地维护，不在仓库内，维护人均为项目负责人（产品侧）：

- 项目定义：范围、分工与产品决定的唯一主维护位置。
- 模型与数据准备事项：给技术负责方的交接说明与 fixture v2 冻结包。
- 143 模型承接波任务书：该波分线、接口、测试编号与 §8 后续清单。
- 模型承接波各线完成回执：各线证据与手册段落。
- 164 QA 修复波任务书与收口回执：PR #47–#56 的分线、产品边界、QA 问题 F01–F31 的逐项结果与部署须知。
- 164 真实 Claude Code MCP 往返回执：真实客户端中英两轮的步骤、请求头核对、问题清单与连接方式建议。
