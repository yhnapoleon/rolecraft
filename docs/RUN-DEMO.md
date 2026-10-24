# Run the RoleCraft demo · 一条命令起演示环境

## Quick start (English)

Requirements: [uv](https://docs.astral.sh/uv/) and Node.js 22.12 or newer. uv fetches Python 3.12 itself.

```sh
scripts/demo/up.sh        # Windows PowerShell: scripts\demo\up.ps1
```

The first run installs the dependencies and builds the web app, which takes a few minutes. It then starts the API, a worker and the web app, imports the recorded demo sessions, and prints an address and one continue code per session.

- Open <http://127.0.0.1:18560/>. Choose **Have a continue code?** and enter a printed code to open a recorded session, or choose **Start** to begin a new practice.
- `scripts/demo/check.sh` tells you whether the running environment is fit to record (see [Before recording](#录前自检)).
- `scripts/demo/status.sh` shows the processes, the address and the codes again. `scripts/demo/down.sh` stops everything.

Without the recogniser weights and a model key, the system runs as a **replay**. Recorded sessions show the recognition results stored with them. Anything computed live (the pre-submission preview, "Your behaviour pattern") uses the rule fallback, and colleagues, review and the knowledge assistant show "waiting for model". To run the full system, see [完整系统](#完整系统).

## 做什么

`scripts/demo/up.sh` 依次完成八步：

1. 检查 uv、Node.js（22.12 以上）和两个端口；
2. `uv sync --locked --inexact`，配了关系编码器时加 `--extra encoder`；
3. `apps/web` 里按需 `npm ci`。前端源码自上次构建后有改动，或者 `dist/` 被别处重建过，就重新 `npm run build`；
4. 用 `scripts.regression.published.write_catalog` 从 `demo/catalog.json` 生成场景目录（会核对已发布场景的身份），并在本机生成一把凭据密钥；
5. 数据库是新的就导入演示包 `demo/demo-pack-v1.json.gz`，把继续码存下来；
6. 起 API，等 `/health`；
7. 起 worker，等它报完四个模型槽和五个识别器；
8. 起前端（`vite preview`），等首页和 `/api/health` 经代理都通。

最后打印地址和继续码，再跑一遍[录前自检](#录前自检)。任何一步失败，都会停掉已经起的进程，并打印对应日志的最后几行。

所有状态放在一个运行目录里，默认 `runs/demo-stack/`（`runs/` 被 Git 忽略）：

| 文件 | 内容 |
|---|---|
| `catalog.json` | 本机绝对路径的场景目录 |
| `credential.key` | 凭据密钥，权限 600；继续码靠它校验，删掉它，旧码就全部失效 |
| `rolecraft.db` | SQLite 数据库 |
| `continue-codes.json` | 演示包每局的继续码，权限 600 |
| `logs/` | `api.log`、`worker-1.log`、`web.log`，上一次的日志加 `.1` 保留 |
| `state.json` | 端口、进程号、所用配置；可能含密钥的变量只记「已设置」，不记值 |
| `web-build.json`、`npm-lock.sha256` | 前端构建指纹，自检用 |

再次 `up` 会沿用同一个数据库和同一批继续码。

## 常用选项

| 选项 | 作用 |
|---|---|
| `--api-port`、`--web-port` | 端口，默认 18562、18560 |
| `--run-dir <目录>` | 换一个运行目录，等于一套全新的部署；`down`、`status`、`check` 也要带同一个值 |
| `--provider deepseek` | 所有模型槽的默认 provider（还可选 `openai`、`openai_compatible`），等同 `career-lab serve --provider` |
| `--env-file <文件>` | 读 `CAREER_LAB_*`、`HF_*`、`TRANSFORMERS_*` 配置（见下）；不要往里放 key |
| `--encoder` | 强制装 torch 与 transformers（`uv --extra encoder`） |
| `--workers <n>` | worker 个数，接真实模型时可开 2–3 个 |
| `--catalog published` | 只装已发布的知识助手场景，不含 IT 工单场景；演示包里 IT 的两局就打不开 |
| `--no-demo-pack` | 不导入演示包 |
| `--reimport` | 覆盖导入演示包，旧继续码作废、发新码；先 `down` |
| `--lang zh\|en` | 输出语言，默认跟系统语言；也可设 `ROLECRAFT_DEMO_LANG` |

当前 shell 里已经导出的 `CAREER_LAB_*` 也会传给服务。场景目录、场景归档、凭据密钥和数据库这四项由脚本统一设定，不用外面的值。

## 完整系统

完整系统还需要三样东西：识别器权重、关系判定编码器，以及模型 key。权重目前只在技术同学的机器上，见 README「Full system」。

把路径和 provider 写进一个 env 文件，例如 `runs/models.env`：

```sh
CAREER_LAB_RECOGNIZERS=runs/local/recognizers
CAREER_LAB_RELATION_ENCODER=runs/local/recognizers/c1-xlmr-cpu
CAREER_LAB_ROLES_PROVIDER=deepseek
CAREER_LAB_ROLES_KEY_FILE=ds.txt
CAREER_LAB_JUDGE_PROVIDER=deepseek
CAREER_LAB_JUDGE_KEY_FILE=ds.txt
CAREER_LAB_ASSISTANT_PROVIDER=deepseek
CAREER_LAB_ASSISTANT_KEY_FILE=ds.txt
# 评审页逐句模型建议（可选）：CAREER_LAB_MODEL_REGISTRY 与 CAREER_LAB_MODEL_REGISTRATIONS
```

然后运行：

```sh
scripts/demo/up.sh --env-file runs/models.env --workers 2
```

- key 只放在 `*_KEY_FILE` 指向的文件里，例如仓库根的 `ds.txt`（已被 `.gitignore` 忽略）。脚本不读 key，也不写 key；服务启动时自己去读。
- 相对路径按仓库根解析。
- SUPPORT 槽不单独配置时，跟随 JUDGE。
- 设了 `CAREER_LAB_RELATION_ENCODER` 时，`up` 会自动装 encoder 依赖（CPU 版 torch，首次较大）。

<a id="录前自检"></a>
## 录前自检

```sh
scripts/demo/check.sh            # --json 输出机器可读结果；--no-encoder-load 跳过试加载编码器
```

自检只读：不写库、不调模型，也不走继续码找回接口。找回接口会签发新凭据，而且每个来源 15 分钟内只能用 10 次。继续码改成用凭据密钥和库里存的校验值离线比对。逐项检查以下内容：

| 区块 | 看什么 |
|---|---|
| 服务 | API `/health`、每个 worker 进程、前端首页和 `/api` 代理 |
| 前端版本 | 正在服务的页面是不是当前源码的构建；`workbench-engine.js?v=` 在源码、`dist/` 和页面上是否一致，页面上的引擎文件是否就是 `public/` 里那份 |
| 场景 | 装了哪些场景包、哪些语言 |
| 模型槽 | worker 启动时报的四个槽：是 `local`（界面会显示「等待模型接入」）还是真实 provider；只看配置，不调用模型 |
| 识别器 | worker 启动时报的五个识别器：已加载，还是规则回退及原因；关系判定编码器在同一配置下实际试加载一次，并核对堆叠集成与它匹配 |
| 评审页模型建议 | 是否登记了 `CAREER_LAB_MODEL_REGISTRY` |
| 演示包 | 每个继续码是否还能打开对应的一局 |

结论分三档，退出码分别为 0、1、2：

- **能录完整系统**：服务、前端、继续码都正常；四个模型槽都是真实 provider，五个识别器和编码器都已加载。
- **只适合录演示包回放**：标 ○ 的项会让画面显示「规则回退」或「等待模型接入」。
- **现在不能录**：有标 ✗ 的项，例如服务没起、前端是旧构建、继续码失效。

标 `!` 的是提醒，不影响结论。

2026-10-24 在 macOS 上从无 `.git`、无依赖的干净副本起出、无权重且用本地模型时的实测输出（端口为测试用）：

```text
RoleCraft 录前自检 · 2026-10-24 13:05 · runs/demo-stack

服务
  ✓ API http://127.0.0.1:18642 运行中
  ✓ worker 1/1 运行中
  ✓ 前端 http://127.0.0.1:18643，/api 代理通

前端版本
  ✓ 页面是当前源码的构建（no-git）
  ✓ workbench-engine.js?v=20261014 一致

场景
  ✓ 8 个场景包：it_ticket_pilot, pm_pilot, pm_pilot_capacity15, pm_pilot_urgent · en/zh

模型槽（worker 启动时）
  ○ ROLES 同事回复：local — 界面会显示「等待模型接入」
  ○ JUDGE 评审的语义评分项：local — 界面会显示「等待模型接入」
  ○ SUPPORT 依据核验：local — 界面会显示「等待模型接入」
  ○ ASSISTANT 知识助手回答：local — 界面会显示「等待模型接入」

识别器（worker 启动时）
  ○ 证据检索（BM25 + e5）：规则回退（未设 CAREER_LAB_RECOGNIZERS）
  ○ 范围检测（马氏距离）：规则回退（未设 CAREER_LAB_RECOGNIZERS）
  ○ 提问意图（TF-IDF + LR）：规则回退（未设 CAREER_LAB_RECOGNIZERS）
  ○ 行为识别（DTW / HMM）：规则回退（未设 CAREER_LAB_RECOGNIZERS）
  ○ 关系判定堆叠集成：规则回退（未设 CAREER_LAB_RECOGNIZERS）
  ○ 关系判定编码器（XLM-R）：未设 CAREER_LAB_RELATION_ENCODER

评审页模型建议
  ! 评审页逐句模型建议未登记（CAREER_LAB_MODEL_REGISTRY）：新交付没有这一块，演示包里存下的照常显示

演示包
  ✓ 演示包继续码 8/8 可用

结论：只适合录演示包回放。标 ○ 的项会在画面上显示规则回退或「等待模型接入」；要录完整系统，按 docs/RUN-DEMO.md 补权重与模型配置后重新 up。
```

配了真实 provider 时，模型槽一行显示 provider 和模型名（如 `✓ ROLES 同事回复：deepseek · deepseek-chat`），并多一条提醒：自检只核对配置，不调用模型验证 key，录前在界面里先问一次同事、测一次助手。

## 常见问题

- **端口被占用**：`up` 会直接报出是哪个端口，换 `--api-port`、`--web-port` 即可。
- **继续码打不开**：
  - 换过 `--run-dir`、删过 `credential.key`、或者 `--reimport` 过，旧码都会失效，用 `status` 看当前的码；
  - 自检的「演示包」一栏会说明是哪一局、什么原因；
  - 本机经前端代理反复找回时，15 分钟内最多 10 次。
- **手动起服务**：仍按 `docs/HANDOVER.md`「起服务」一节。演示包每局的内容和看点见 `demo/README.md`。
- **Windows**：`up.ps1`、`check.ps1`、`status.ps1`、`down.ps1` 与 `.sh` 调用同一个 `scripts/demo/launcher.py`。截至 2026-10-24 只在 macOS 上实测过，Windows 尚未实测。
