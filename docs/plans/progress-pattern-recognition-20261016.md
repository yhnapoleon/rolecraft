# 模式识别层：实施进度与交接（2026-10-16 至 10-17 会话）

写给下一个接手的会话或组员。执行依据仍是[完整设计](pattern-recognition-design-20261016.md)；本文记录做到哪、怎么跑、下一步按什么顺序做、和设计有出入的地方。**接手先读第 0 节和第 4 节。**

## 0. 现场（10-17 第二个会话结束时）

- **用户 10-17 定的方向**：这是 PoC 级演示 MVP，不在稳定性/安全性上发力、不总跑全量测试；先把模块搭完，模型效果（Colab C1 等）后面再说；ROLES / ASSISTANT 槽也接 DeepSeek；PR 一块一个，**用户手动 merge**（自动模式不允许 Claude 自合）。之后又定：技术部分做完 + 做「预置演示会话包」，报告先不管。
- **PR**：#58 后端、#59 前端、#60 实验、#61 IT 场景（叠在 #58 上）、#62 演示会话包与收尾（叠在 #61 上）。都未合并；合并顺序 #58 → #61 → #62，#59/#60 随意。本地工作区在 `claude/rc5-demo-pack` 分支上，前端与实验目录的改动不在这个分支里（在 #59/#60 的分支上）。
- 开发服务（18562）与前端预览（18560）开着，跑的是最新代码；四个模型槽全是 DeepSeek；目录里有 pm_pilot 三个变体与 `it_ticket_pilot`，各中英。

## 1. 进度一览

| 步骤 | 状态 | 说明 |
|---|---|---|
| S0 环境 | 完成 | `.venv-encoder`（torch 2.8.0 CPU / transformers 4.57.1；另用 `uv pip` 装了 hmmlearn 0.3.3，未进 uv.lock）；e5-small、XLM-R base 权重在 `runs/local/`；四个槽（JUDGE/SUPPORT/ROLES/ASSISTANT）都接 DeepSeek（`env.ps1`；`$env:RC_LOCAL_ROLES='1'` 退回本地模板同事） |
| S1 骨架 | 完成 | 契约 `contracts/v2/recognition.py`；`FeedbackV2`/`TestResultV2`/`RoleReply` 加可选 `recognition`；`GET /sessions/{id}/recognition`、`/behavior`；前端署名组件、复盘页汇总行 |
| S2 C2 | 完成 | assembler 候选切单元（≤80，预算 48 KB）；助手打分 = max(覆盖率, 校准 e5 相关度)；consumer 逐句只送 C2 top-5 |
| S3 数据 | 完成 | 第 3 节 |
| S4 轻量识别器 | 完成并登记 | C11 意图、C4 范围、C5 行为（`runs/local/recognizers/manifest.json`） |
| S5 三入口装配 | 完成 | JUDGE / ROLES / ASSISTANT 全部接上；端到端核过（第 5 节） |
| S6 C1 | 本机 CPU 版已训练并登记；E10 晚期融合已启用 | `runs/local/recognizers/c1-xlmr-cpu`（冻结 10 层、2 轮、max_len 160）；以 external_candidate 登记在 `runs/local/c1-return`；`fusion.json` α=0.4。Colab 版暂缓（用户：先搭模块） |
| S7 页面 | 完成 | 复盘页「你的行为模式」；识别实验室 `#/lab`（E1、E3–E10 全部有图）；**交付前预演卡逐句标色**（R2.support 的 C2+C1+C6，附依据原句） |
| S8 it_ticket_pilot | **中英可玩** | `content_it.py` / `content_it_en.py` + `scripts/recognition/build_it_scenario.py --languages zh en` 生成包 `scenarios/it_ticket_pilot/v2/candidates/it-1/`；同事名与 pm_pilot 一致（陈敏 / 经理），前端不用改；C4 中英都有 IT 专属拟合；前端入口「同样的结构，换一个领域」。B1 工程师路径接 C1 不做（自报是结构化 pass/fail，没有给 C1 判的句子） |
| 演示会话包 | 完成 | `scripts/recognition/demo_play.py` 录一局完整演示（读材料→三类测试→问三位同事→应用方案→刷新索引前后复测→交付→修订再交），`demo_pack.py export/import/show` 导出整局原始行、在任何部署导入并签发继续码（不调模型）；`demo/README.md`、`demo/catalog.json`（仓库相对路径）、`demo/demo-pack-v1.json` |
| S9 实验 | 见第 2 节 | E3、E4、E5、E6、E7、E10、E9（检索与范围）完成；E1 基线需重跑；E8 需重跑 |
| S10 报告 | 未开始 | |

## 2. 实验状态与结果（test）

| 编号 | 状态 | 结果 / 待办 |
|---|---|---|
| E1 C1 | 完成 | macro-F1 中 0.656 / 英 0.608，joint 0.611，证据 F1 0.75；ECE 0.021→0.014（T=0.9）。`c1-xlmr-cpu/metrics.json` |
| E1 C3 基线 | **需重跑** | 现存 `e1_baselines.json` 是不加权版（多数模型把逐对全判成「无关」，宏 F1 0.10–0.30；带手工特征的 LR 0.587/0.462、决策树 0.578/0.438）。脚本已改成 `class_weight="balanced"`，需重跑并带 `--encoder` 做堆叠与 α 融合 |
| E2 | 未跑 | 线性适配 / 全量微调对照在 Colab 笔记本里（CPU 上太慢） |
| E3 C2 | 完成 | 改写问题 Recall@5：e5 0.82/0.79，RRF 0.65/0.57，BM25 0.49/0.36；直述三法≈1.0；关系断言 e5≈RRF（0.985/0.96） |
| E4 C6 | 完成 | 经产品加载器复算 test：macro-F1 0.656/0.608，joint 0.611；ECE 0.009→0.006。按期望代价拒识：**误扣分率** 0% 拒识时 6.3% → 10% 时 2.4% → 20% 时 0.8%，但总错误率不降（0.37–0.40）——代价矩阵只针对误扣分，这正是它的设计目的，报告里要讲清楚。提升图：期望代价前 20% 只覆盖 17.8% 的错误（不比随机好），所以待核验排队的「x%」一句要据实写或改成按误扣分算。代价矩阵下送人工比例 7.9% |
| E5 C4 | 完成 | 马氏 AUROC 0.977/0.953；余弦最近邻 0.98/0.94；其余对照 0.70–0.91 |
| E6 C5 | 完成 | 策略识别三法都 1.0（脚本可分）；扰动 0.5 时 DTW 0.71、n-gram RF 0.55；HMM 5 状态；异常 AUROC HMM 0.90、DTW 0.88、IF 0.17；聚类 ARI 0.965 |
| E7 C11 | 完成 | LR 准确率 0.946/0.824，macro-F1 0.886；关键词规则 0.525 |
| E8 Judge 开/关 | 完成（10-17 重跑） | 28 对（7 策略 × 2 种子 × 中英），两组同事都用本地模板、在同一份代码上跑，357 个语义项：待核验 57.4% vs 61.1%，给出标签 42.6% vs 38.9%，每项引用 1.12 vs 1.05；两组标签一致 0.675；开组解释前缀 [识别一致] 20.7%、[与识别不一致] 11.8%、[识别缺失] 8.7%；R2.support 仲裁 17 次、冲突率 23.5%。提升小但方向一致，报告据实写。旧结果改名 `*.jsonl.old`（不入库） |
| E9 跨领域 | 检索与范围完成；C1 待跑 | pm_pilot 的 C4 拟合搬到 IT：AUROC 0.60/0.50；只用 IT 知识库单元拟合：0.986/0.949；IT 改写问题 e5 Recall@5 0.82/0.64 |
| E10 晚期融合 | 完成 | α=0.4（dev 0.634）；test macro-F1：C1 0.656/0.608/0.625（中/英/合计），规则 0.311，晚期融合 0.655/0.616/0.630。增益小，但冒烟里「住宿上限 500 元」从误判矛盾变成支持、「50 人」判成超限（置信 0.54 送人工）。早期融合未做（要重训） |

## 3. 数据（`data/releases/`，未入库）

| 目录 | 内容 | 规模 |
|---|---|---|
| `intent-v1` | 五类意图 × 四文风 | 1,236（盲判一致 91%） |
| `assistant-queries-v1` | 域内直述/改写、近域外/远域外 | 538 + 79 被筛（`rejected.jsonl`，E3 合并评测） |
| `paraphrases-v1` | C4 拟合用改写问题 | 124 |
| `relation-v3` | pair_aggregate 格式，1 金标 + 3 难负例 | 4,325 断言 / 17,281 句对；按 (语言, 材料) 60/20/20 |
| `trajectories-v1` | 8 种脚本策略的符号序列 | 400 |
| `it-ticket-v1` | 第二领域材料、关系断言、查询（全部 test） | 1,199 断言、624 查询 |

DeepSeek 合计约 2,600 次调用。生成与复核同为 DeepSeek，报告须写明同源局限。

## 4. 下一步（按顺序）

### 4.0 PR 切分

按目录：#58 `src/` 识别层与入口、#59 `apps/web/**`、#60 `experiments/**`、#61 IT 场景（`src/career_lab/scenarios/v2/**`、`scenarios/it_ticket_pilot/**`）、#62 演示会话包与收尾（`demo/**`、`scripts/recognition/demo_*`、漂移数值规则、预演性能、IT 英文、本文件）。后续前端改动追加到 #59 的分支、实验结果追加到 #60 的分支（未合并前），其余叠在 #62 上。PR 描述写「演示版，契约未重导出」。

### 4.1 已做完（10-17 第二会话后半）

E8 重跑（两组同一份代码）；IT 场景英文版与同事改名（陈敏 / 经理，前端不用改）；漂移识别加数值规则（「数值变化 500 → 400」）；预演卡只在草稿上跑识别、按包 hash 缓存、API 启动时后台预热 C1、前端预演请求放宽到 60 秒；演示会话包（`demo/`，8 局：中英 × 两个场景 × 完整一局与交付前）；加权基线与 E9 的 C1 部分（结果见第 2 节）。

### 4.1.1 还剩的

1. S10 报告、slides、视频、架构图（用户：先不管）。
2. 性能：预演首算约 23 秒、再算约 8 秒（8 秒是规则核查 + C2 候选排序本身，没识别器也要 8.7 秒）；C1 换 Colab 版；E2。
3. 人机判别（没有 Agent 轨迹）、B1 工程师路径接 C1——不做，报告里写「下一步」。

### 4.2 性能项（用户说放最后）

- 加权基线 + C1 堆叠（`baselines --encoder …`，CPU 约 1 小时）；E9 的 C1 部分（`cross_domain --encoder …`）；Colab 版 C1（第 7 节）；E2。

### 4.3 命令备忘

```powershell
cd D:\HuaweiMoveData\Users\13736\Desktop\AIS\5002GPJ
$env:PYTHONUTF8='1'
$env:RC_OFF='0'; . runs\local\dev\start.ps1
.venv\Scripts\python -m scripts.recognition.smoke --language zh --continue-code
.venv\Scripts\python -m scripts.recognition.smoke --scenario it_ticket_pilot --language zh --continue-code
.venv-encoder\Scripts\python -m scripts.recognition.build_it_scenario          # 重建 IT 包，打印 catalog 条目
.venv-encoder\Scripts\python -m scripts.recognition.fit_it_scope               # 重拟合 IT 的 C4 并重新登记
.venv\Scripts\python -m experiments.recognition.publish_lab --c1 runs/local/recognizers/c1-xlmr-cpu
cd apps\web; npm run build
```

重建 IT 包后 `scenario_hash` 会变，要同步改 `runs/local/dev/catalog.json` 里那一条再重启。

## 5. 已核过的验收

- S1：测试卡、同事回复、反馈页逐项、复盘页汇总行在全规则回退下都显示灰色署名（浏览器 DOM 核对）。
- 3.1：含「安排 50 人」的作品，R2.support 解释以 `[识别一致]` 开头（C1 版）；`GET /recognition` 有 relation、retrieval、decision、arbiter 记录；不设 `CAREER_LAB_RECOGNIZERS` 时回到原行为。
- 3.2：同事回复下有意图与依据核查署名；`learner_state` 出现在 `role_context` 私有审计对象里。
- 3.3：「火星天气」域外；「住宿报销上限」全范围域内、排除政策后域外。漂移标注未做端到端验证（这一版场景很难触发索引前后版本不同）。
- 10-17 第二会话（重启后冒烟）：4.1 旧三处都生效——融合后「住宿上限 500 元」支持 0.51、「50 人」矛盾 0.54 送人工；SUPPORT 核验只出 supported/unverified；行为阶段 探索→测试→探索→决策，无提交前「调整」。
- DeepSeek 同事：回复 `generation_mode=model`；技术负责人曾答「上限是 60 人」（把可审批上限当现有容量），C10 把这句判为与 brief 矛盾——演示里可以拿来讲「识别层抓 LLM 的错」。
- 预演卡：`GET /sessions/{id}/submission-rule-check?submission_id=` 带 `recognition`（7 句，CPU 约 3–12 秒），依据列给出命中的那一句原文。
- IT 场景：助手答「P2 响应时限为4小时」，C4 用 IT 拟合（域内 1.21 / 阈 1.89）；Judge R2.support `[识别一致]`；融合识别出「4 hour」同量、「50>30」超限。首页 `#/pm` 出现 IT 卡片（headless Edge 截图核过）。
- 漂移端到端：同一问题索引刷新前后各测一次（500 → 400），测试卡署名「漂移 · 数值变化 500 → 400（向量距离 0.02）· 异常」（浏览器 DOM 核过）。
- 演示会话包：在全新数据库、仓库相对路径目录、无识别器权重、无 DeepSeek 的条件下导入 8 局，8 个继续码都能换到令牌，timeline / recognition / behavior / feedback 全 200；交付前那局的预演退回规则版照常返回。浏览器里复盘页汇总行、行为模式、反馈页 `[识别一致]` 前缀、预演卡 4/4 规则项 + 9 句标色都核过。
- 演示录制要点：提交时必须带上当前配置引用（`config`，工作台就是这么交的），否则规则项全部「依据不完整」；同事回复偶尔被 LLM 安全复核拦下（`role_help_unverified`），`demo_play` 会整局重录。

## 6. 怎么跑

- 开发服务：`. runs\local\dev\start.ps1`（DeepSeek 评审，端口 18562/18560，3 个 worker）。`$env:RC_OFF='1'` 不带识别层；`$env:RC_SYNTHETIC='1'` 模型槽退回合成线性回传。前端 `apps/web` 下 `npm run build`，再 `npm run preview -- --port 18560`（设 `ROLECRAFT_API_TARGET=http://127.0.0.1:18562`）。
- 数据服务（全本地模型，端口 18572）：`. runs\local\data\start-data.ps1`；轨迹生成器 `scripts/recognition/run_strategies.py`。
- 冒烟带 `--continue-code` 会打印继续码，在浏览器首页「有继续码？」输入即可打开该会话看界面。
- 合成脚本：`scripts/recognition/{synth,synth_relation,synth_domain}.py`；实验脚本：`experiments/recognition/*.py`，结果在 `experiments/recognition/results/`。

## 7. 需要人决定或动手

- **合并 PR**：#58 及 4.0 节的后续 PR 由用户或组员合并（自动模式不允许 Claude 自合，也拦了后续 git 操作，开 PR 2–4 要用户放行）。
- **Colab 训更好的 C1**（用户 10-17：暂缓，模块搭完再说）：打开 `runs/local/colab/colab_train_c1.ipynb`，上传同目录 `c1-bundle.zip`，下载 `c1-out.zip` 解压到 `runs/local/recognizers/c1-xlmr/`，然后 `python -m experiments.recognition.relation.register_c1 --train-out runs/local/recognizers/c1-xlmr --out runs/local/c1-return-colab`，把打印的变量写进 `runs/local/dev/env.ps1`，再重跑 E10（`experiments.recognition.fusion`）。
- 已定：ROLES / ASSISTANT 接 DeepSeek（10-17 已接）；PR 一块一个。

## 8. 与设计的出入（代码注释里都写了）

1. `PROMPT_VERSION` 没改（发布包钉死 v1，改了服务起不来）；识别段落只在输入含 `recognition` 时追加，修订号记在识别记录里。
2. 场景包里不放 `runtime/recognition.json`（发布包有 hash 校验）；检索方法与 e5 校准锚点在 `recognition/assistant.py`。
3. 助手识别只作用于学员自己的测试；隐藏探针与工程师重放走原规则。
4. ROLES 的识别上下文在 `RoleService.generate` 开头建立（私有端口在那时就对 prompt 求哈希）。
5. C4 的 scope_on 定义为「开了范围过滤且排除了政策类领域」。
6. SUPPORT 槽：识别器只放行不否决（4.1 第 2 条）。
7. 行为异常规则 1 泛化为「世界变化（里程碑通知或索引刷新）后未再测就提交」。
8. 人机判别未做（无 Agent 轨迹）；S8 可玩版只有中文，B1（工程师路径接 C1）不做。
9. 助手 C2 用 e5 而非 RRF（E3 的结论）。
10. ROLES 接 DeepSeek 后，`CooperativeHelpVerifier` 的方括号引文格式与五个质量项不再拦截回复，只留四个安全项（`roles_v2.py` 注释）；每句依据由 C10 标注。不这样改约一半回复被拦。
11. IT 场景是「换皮」：所有材料 id、事实 id 和数值与 pm_pilot 相同（`hotel_limit` 在 IT 里是 P2 响应时限 4→2 小时），所以评分规则、识别器、行为模型不用改；数值与 `it-ticket-v1` 数据版（E9 用）的账本不一致（候选 50 人 vs 60 人），两者独立。
12. 预演卡调用了识别器（C1 在 API 进程里推理），不再是「不调用模型」；文案改成「不调用大模型」。

## 9. 坑

- 改了 `src/` 下任何 .py 都要重启服务（`execution_restart_required`）。
- Bash heredoc 会吃反斜杠；含 `\n`、`\\` 的补丁用 Write/Edit 或写成脚本文件。
- Claude in Chrome 窗口被最小化时截图超时、布局宽 0；改用 `msedge --headless=new --screenshot=<png> --window-size=1280,3000 <url>`。
- `GET /recognition`、`/behavior`、`/timeline` 的响应信封都是 `{"result": {"result": {...}}}`（`client.objects` 已改成逐层解开；之前的冒烟其实从没打印出同事回复）。
- 多局并行录制或并行实验会把 SQLite 锁住（`database is locked`，即使有 30 秒等待）：录演示一次一局。
- Claude in Chrome 的标签页在后台/最小化窗口里定时器被重度节流，`javascript_tool` 里 `setTimeout` 等待会让 CDP 45 秒超时；要么分两次调用（先触发、再读），要么直接用 Python 打 API。
- Windows 长路径：`git worktree add` 要加 `-c core.longpaths=true`，删 worktree 用 `cmd /c rd /s /q "\\?\<绝对路径>"`。
- Windows 上 `write_text` 会把 `\n` 写成 `\r\n`，而发布记录用 `read_text` 读回清单再比 hash → `release_content_mismatch`。构建场景包时清单一律 `write_bytes(...encode())`。另外仓库 `.gitattributes` 是 `eol=lf`，包里文件若是 CRLF，提交后别人检出的字节就和清单里的 hash 对不上；`build_it_scenario.py` 已把 `Path.write_text` 强制成 LF。
- 重 CPU 负载 + 多 worker 时 SQLite 锁超时（500 `OperationalError`）。
- DeepSeek 起草材料时会把账本键名写进句子；`synth_domain.py` 已改为自然语言账本 + 键名回填 + 拒收。
- Windows 下远端单测约 70 个平台性失败（文件锁、symlink、权限），与本次改动无关；前端 `score-range.test.ts` 在 CPU 满载时会 5 秒超时。
