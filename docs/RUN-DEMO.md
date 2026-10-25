# Run the RoleCraft demo · 一条命令起演示环境

本页是起演示环境和录制演示的唯一说明。手动逐个起服务的方法见 `docs/HANDOVER.md`「起服务」。

## Quick start (English)

Requirements: [uv](https://docs.astral.sh/uv/) and Node.js 22.12 or newer. uv fetches Python 3.12 itself.

```sh
scripts/demo/up.sh        # Windows PowerShell: scripts\demo\up.ps1
```

The first run installs the dependencies and builds the web app, which takes a few minutes. It then:

- starts the API, a worker and the web app;
- imports the recorded demo sessions;
- prints an address and one continue code per session.

The codes are valid only on the database and credential key they were imported with. `scripts/demo/status.sh` prints them again.

- Open <http://127.0.0.1:18560/>. Choose **Have a continue code?** and enter a code to open a recorded session, or choose **Start** under AI Product Manager to begin a new practice.
- Add `?lens=1` to show the recognition lens (for example `http://127.0.0.1:18560/?lens=1#/work`). `#/lab` is the system profile, and `#/engineer-report` holds two sample regression reports.
- `scripts/demo/check.sh` tells you whether the environment is fit to record (see [录前自检](#录前自检)). `scripts/demo/down.sh` stops everything.

Without the recogniser weights and a model key, the system runs as a **replay**. The recognition layer is on, and every recogniser uses its rule fallback, labelled as such. Recorded sessions show the recognition results stored with them. Colleagues, review and the knowledge assistant show "waiting for model". To run the full system, see [完整系统](#完整系统).

## 做什么

`scripts/demo/up.sh` 依次完成八步：

1. 检查 uv、Node.js（22.12 以上）和两个端口。
2. `uv sync --locked --inexact`。配了关系编码器时加 `--extra encoder`。
3. `apps/web` 里按需 `npm ci`。前端源码自上次构建后改过，或者 `dist/` 被别处重建过，就重新 `npm run build`。
4. 生成场景目录：用 `scripts.regression.published.write_catalog` 从 `demo/catalog.json` 生成，会核对已发布场景的身份。同时在本机生成一把凭据密钥。
5. 数据库是新的，就导入演示包 `demo/demo-pack-v1.json.gz`，并存下继续码。
6. 起 API，等 `/health` 就绪。
7. 起 worker，等它报完四个模型槽和五个识别器。
8. 起前端（`vite preview`），等首页和经代理的 `/api/health` 都能访问。

最后打印地址和继续码，再跑一遍[录前自检](#录前自检)。任何一步失败，都会停掉已经起来的进程，并打印对应日志的最后几行。

**识别层默认打开。** 没给权重目录时，`CAREER_LAB_RECOGNIZERS` 指向运行目录里一个空的 `no-weights`。这样识别层是开着的，只是全部走规则回退：透镜里照样能看到逐句标注和识别链，署名如实标「规则回退」。只有设了这个变量，识别层才会打开；不设时，交付前预演的逐句块、评审页的识别汇总和入口、「你的行为模式」都不会出现。要关掉识别层，加 `--no-recognition`。

所有状态放在一个运行目录里，默认是 `runs/demo-stack/`（`runs/` 被 Git 忽略）：

| 文件 | 内容 |
|---|---|
| `catalog.json` | 用本机绝对路径写成的场景目录 |
| `credential.key` | 凭据密钥，权限 600。继续码靠它校验，删掉它，旧码就全部失效 |
| `rolecraft.db` | SQLite 数据库 |
| `continue-codes.json` | 演示包每一局的继续码，权限 600 |
| `logs/` | `api.log`、`worker-1.log`、`web.log`；上一次的日志加 `.1` 后缀保留 |
| `state.json` | 端口、进程号、所用配置。可能含密钥的变量只记「已设置」，不记值 |
| `web-build.json`、`npm-lock.sha256` | 前端构建指纹，自检用 |

再次 `up` 会沿用同一个数据库和同一批继续码。

## 演示包的几局

继续码不写在文档里。每个码只在导入它的那套数据库、那把凭据密钥下有效，由 `up` 在首次导入时打印，之后用 `status` 再看。打印出来的每一行是「继续码 + 这一局的说明」，说明分别是：

| 说明 | 用来拍什么 |
|---|---|
| 知识助手试点（中文）：完整一局 + 修订 | 结果封面、反馈、第 2 次交付与第 1 次的对比、系统剖面里本局的一句 |
| Knowledge-assistant pilot (English): full run + revision | 同上，英文 |
| 知识助手试点（中文）：交付前（看预演逐句标色） | 打开交付面板，看交付前预演和透镜里的逐句标注。**不要点提交**，点了这一局就交付了 |
| Knowledge-assistant pilot (English): before submission (preview) | 同上，英文 |
| IT 工单助手试点（中文）：完整一局 + 修订 · IT ticket-assistant pilot (English): full run + revision · 交付前两局 | 录 AI 产品经理主线时不用。码仍能打开，但首页已不显示 IT 情境，局内还留有知识助手场景的字样，比如「差旅政策更新为 v2」 |

要拍首分钟的方向、看板卡、交付盖章和结果封面，就新开一局：首页「AI 产品经理」→「开始」。新局需要 worker 在跑。

## 录制时打开

- 首页：`http://127.0.0.1:18560/`。打开演示包的某一局：首页「有继续码？」→ 输入继续码 → 找回。
- 识别透镜：在地址里加 `?lens=1`，例如 `http://127.0.0.1:18560/?lens=1#/work`。只对当前标签页生效，不改保存的偏好；`?lens=0` 强制关闭。也可以从「⋯ → 识别透镜」打开。
- 系统剖面：`#/lab`，或「⋯ → 系统剖面」。
- 工程师回归报告样例：`#/engineer-report`，内含两份真实签字复核：「根因修法」和「改得太宽」。

## 录制前

1. **先预热。** 把要拍的页面都打开一遍，等加载完再开拍。用继续码找回的局，第一次打开结果页或系统剖面页要等 5–10 秒，这期间页面显示「正在等待服务端确认…」。
   - 2026-10-24 在集成树 `8ff471d` 上实测（本机负载约 7）：同一标签页里第二次进结果页，仍等了约 9 秒；整页刷新后要二十多秒。
   - 最慢的接口是 `submission-rule-check`（15–35 秒）和 `work-products`（约 14 秒）。
   - 所以每次进结果页都要等加载完再拍，剪辑时剪掉等待。
2. **自动录制用真实指针点击。** 用 Playwright 的 `page.mouse` 或 `locator.click()`；程序化的 `element.click()` 会让右栏标签出现粗焦点圈。
3. **要显示识别过程，就加 `?lens=1`。**
4. **先在录制用的浏览器里把每一局打开一次。** 用继续码找回后，页面底部会弹出恢复提示：中文是「已找回。只在原浏览器里的草稿、测试归属和笔记不会跟过来。」，英文是「Restored. Drafts, test filing and notes kept only in the other browser stay there.」。等它消失再开拍，否则会被录进视频。
5. **系统剖面页用默认的第 5 句。** 第 6 句在「表示」这一站检索到的第一条不对题，这是识别层的数据造成的。

录前跑一次 `scripts/demo/check.sh`。它的「录制前」一栏会核对系统剖面和回归样例的数据能否取到，列出这三个地址，并再提醒一次预热。页面有没有预热过，自检看不出来。

## 常用选项

| 选项 | 作用 |
|---|---|
| `--api-port`、`--web-port` | 端口，默认 18562、18560 |
| `--run-dir <目录>` | 换一个运行目录，等于一套全新的部署。`down`、`status`、`check` 也要带同一个值 |
| `--provider deepseek` | 所有模型槽的默认 provider（也可选 `openai`、`openai_compatible`），等同 `career-lab serve --provider` |
| `--env-file <文件>` | 读入 `CAREER_LAB_*`、`HF_*`、`TRANSFORMERS_*` 配置（见下）。不要往里放 key |
| `--encoder` | 强制安装 torch 与 transformers（`uv --extra encoder`） |
| `--workers <n>` | worker 个数，接真实模型时可开 2–3 个 |
| `--catalog published` | 只装已发布的知识助手场景，不含 IT 工单场景，演示包里 IT 的几局就打不开 |
| `--no-demo-pack` | 不导入演示包 |
| `--reimport` | 覆盖导入演示包：旧继续码作废，发新码。先 `down` |
| `--no-recognition` | 不打开识别层 |
| `--lang zh\|en` | 输出语言，默认跟随系统语言；也可设 `ROLECRAFT_DEMO_LANG` |

当前 shell 里已经导出的 `CAREER_LAB_*` 也会传给服务。场景目录、场景归档、凭据密钥和数据库这四项由脚本统一设定，不用外面的值。

## 完整系统

完整系统还需要三样东西：识别器权重、关系判定编码器和模型 key。权重目前只在技术同学的机器上，见 README「Full system」。

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

- key 只放在 `*_KEY_FILE` 指向的文件里，例如仓库根的 `ds.txt`（已被 `.gitignore` 忽略）。脚本既不读也不写 key，服务启动时自己去读。
- 相对路径按仓库根解析。SUPPORT 槽不单独配置时，跟随 JUDGE。
- 设了 `CAREER_LAB_RELATION_ENCODER` 时，`up` 会自动安装 encoder 依赖（CPU 版 torch，第一次下载较大）。

<a id="录前自检"></a>
## 录前自检

```sh
scripts/demo/check.sh            # --json：输出机器可读结果；--no-encoder-load：跳过编码器试加载
```

自检只读：不写库、不调模型，也不调用继续码找回接口。找回接口会签发新凭据，而且每个来源 15 分钟内只能用 10 次，所以继续码改成用凭据密钥和库里存的校验值离线比对。逐项检查：

| 区块 | 看什么 |
|---|---|
| 服务 | API `/health`、每个 worker 进程、前端首页，以及经代理的 `/api` |
| 前端版本 | 正在服务的页面是不是当前源码的构建；`workbench-engine.js?v=` 在源码、`dist/` 和页面上是否一致；页面加载的引擎文件是不是 `public/` 里那份 |
| 场景 | 装了哪些场景包、哪些语言 |
| 模型槽 | worker 启动时报的四个槽，各自是 `local`（界面会显示「等待模型接入」）还是真实 provider。只看配置，不调用模型 |
| 识别器 | 识别层是关着、开着但无权重，还是有权重。worker 启动时报的五个识别器各自的状态。关系判定编码器在同一配置下实际试加载一次，并核对堆叠集成和它是否匹配 |
| 评审页模型建议 | 是否设了 `CAREER_LAB_MODEL_REGISTRY` |
| 录制前 | 系统剖面与回归报告样例的数据能否取到、三个录制地址、预热提醒 |
| 演示包 | 每个继续码是否还能打开对应的那一局 |

结论分三档，退出码分别为 0、1、2：

- **能录完整系统**：服务、前端、继续码都正常；四个模型槽都是真实 provider；五个识别器和编码器都已加载。
- **只适合录演示包回放**：有标 ○ 的项，画面上会显示「规则回退」或「等待模型接入」。
- **现在不能录**：有标 ✗ 的项，例如服务没起、前端是旧构建、继续码失效、识别层关着。

标 `!` 的是提醒，标 `·` 的是信息，都不影响结论。

下面是 2026-10-24 在集成树 `8ff471d` 上、无权重并用本地模型时的实测输出。端口已换成默认值：

```text
RoleCraft 录前自检 · 2026-10-24 16:36 · runs/demo-stack

服务
  ✓ API http://127.0.0.1:18562 运行中
  ✓ worker 1/1 运行中
  ✓ 前端 http://127.0.0.1:18560，/api 代理通

前端版本
  ✓ 页面是当前源码的构建（5618034+changes）
  ✓ workbench-engine.js?v=20261024 一致

场景
  ✓ 8 个场景包：it_ticket_pilot, pm_pilot, pm_pilot_capacity15, pm_pilot_urgent · en/zh

模型槽（worker 启动时）
  ○ ROLES 同事回复：local — 界面会显示「等待模型接入」
  ○ JUDGE 评审的语义评分项：local — 界面会显示「等待模型接入」
  ○ SUPPORT 依据核验：local — 界面会显示「等待模型接入」
  ○ ASSISTANT 知识助手回答：local — 界面会显示「等待模型接入」

识别器（worker 启动时）
  ○ 识别层开着，但没有权重：全部走规则回退，透镜里如实标「规则回退」
  ○ 证据检索（BM25 + e5）：规则回退（没有这项权重）
  ○ 范围检测（马氏距离）：规则回退（没有这项权重）
  ○ 提问意图（TF-IDF + LR）：规则回退（没有这项权重）
  ○ 行为识别（DTW / HMM）：规则回退（没有这项权重）
  ○ 关系判定堆叠集成：规则回退（没有这项权重）
  ○ 关系判定编码器（XLM-R）：未设 CAREER_LAB_RELATION_ENCODER

评审页模型建议
  ! 评审页逐句模型建议未登记（CAREER_LAB_MODEL_REGISTRY）：新交付没有这一块，演示包里存下的照常显示

录制前
  ✓ 系统剖面与回归报告样例的数据 28/28 份可取
  · 识别透镜：http://127.0.0.1:18560/?lens=1#/work
  · 系统剖面：http://127.0.0.1:18560/#/lab
  · 回归报告样例：http://127.0.0.1:18560/#/engineer-report
  ! 录前把要拍的页面各打开一遍预热：继续码找回的局，第一次打开结果页或系统剖面页要等 5–10 秒；自动录制用真实指针点击（见 docs/RUN-DEMO.md「录制前」）

演示包
  ✓ 演示包继续码 8/8 可用

结论：只适合录演示包回放。标 ○ 的项会在画面上显示规则回退或「等待模型接入」；要录完整系统，按 docs/RUN-DEMO.md 补权重与模型配置后重新 up。
```

配了真实 provider 时，模型槽那一行会显示 provider 和模型名，例如 `✓ ROLES 同事回复：deepseek · deepseek-chat`，并多一条提醒：自检只核对配置，不调用模型验证 key；录前先在界面里问一次同事、测一次助手。

## 已知限制

- 演示包里没有被判为「矛盾」的句子。透镜里的红线和页边原文只在真有矛盾时出现，要拍矛盾的样子，得重录一局。
- 没有权重时，关系判定走规则回退。透镜里如实标「规则回退」，不标深度学习。
- 反馈页「理由与证据的支持关系」一栏仍显示「评价模型：deepseek · deepseek-chat」，因为演示包登记的是真实评价模型。这一处待修。
- 资料标题里的「陈敏」来自已发布场景的原文，按约定不改。同事的显示名是 Grace、Chen、Daniel。
- 模型槽为 local 时，同事、评审和知识助手都显示「等待模型接入」。
- 同事回复已改成短句、第一人称，但要接上真实模型才看得到效果。演示包里存的是旧提示词生成的回复。

## 常见问题

- **端口被占用**：`up` 会直接报出被占的端口，换 `--api-port`、`--web-port` 即可。
- **继续码打不开**：
  - 换过 `--run-dir`、删过 `credential.key` 或 `--reimport` 过，旧码都会失效，用 `status` 看当前的码；
  - 自检的「演示包」一栏会写明是哪一局、什么原因；
  - 本机经前端代理反复找回时，15 分钟内最多 10 次。
- **手动起服务**：按 `docs/HANDOVER.md`「起服务」一节。演示包每局的内容和看点见 `demo/README.md`。
- **Windows**：`up.ps1`、`check.ps1`、`status.ps1`、`down.ps1` 和 `.sh` 版本调用的是同一个 `scripts/demo/launcher.py`。截至 2026-10-24 只在 macOS 上实测过，Windows 尚未实测。
