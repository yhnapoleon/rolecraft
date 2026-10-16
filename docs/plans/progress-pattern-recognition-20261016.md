# 模式识别层：实施进度与交接（2026-10-16 至 10-17 会话）

写给下一个接手的会话或组员。执行依据仍是[完整设计](pattern-recognition-design-20261016.md)；本文记录做到哪、怎么跑、下一步按什么顺序做、和设计有出入的地方。**接手先读第 0 节和第 4 节。**

## 0. 暂停时的现场（10-17 凌晨）

- **开发服务正在跑旧代码，用之前必须重启**：最后一次重启之后又改了 `src/career_lab/recognition/{relation,judge,behavior}.py`（见 4.1），反馈 handler 会因源码快照变化拒绝执行（`execution_restart_required`）。重启：PowerShell 里 `$env:RC_OFF='0'; . runs\local\dev\start.ps1`。
- E4 评测已在暂停后跑完（`experiments/recognition/results/e4_decision.json`，并已更新 `c1-xlmr-cpu/lift.json`）。后台没有在跑的实验任务。
- 前端预览（18560）和开发服务（18562，1 个 API + 3 个 worker）都还开着。数据服务（18572）已停。
- 全部改动在本地工作区，**未提交、未推送**。推送前问用户。

## 1. 进度一览

| 步骤 | 状态 | 说明 |
|---|---|---|
| S0 环境 | 完成 | `.venv-encoder`（torch 2.8.0 CPU / transformers 4.57.1；另用 `uv pip` 装了 hmmlearn 0.3.3，未进 uv.lock）；e5-small、XLM-R base 权重在 `runs/local/`；JUDGE/SUPPORT 接 DeepSeek |
| S1 骨架 | 完成 | 契约 `contracts/v2/recognition.py`；`FeedbackV2`/`TestResultV2`/`RoleReply` 加可选 `recognition`；`GET /sessions/{id}/recognition`、`/behavior`；前端署名组件、复盘页汇总行 |
| S2 C2 | 完成 | assembler 候选切单元（≤80，预算 48 KB）；助手打分 = max(覆盖率, 校准 e5 相关度)；consumer 逐句只送 C2 top-5 |
| S3 数据 | 完成 | 第 3 节 |
| S4 轻量识别器 | 完成并登记 | C11 意图、C4 范围、C5 行为（`runs/local/recognizers/manifest.json`） |
| S5 三入口装配 | 完成 | JUDGE / ROLES / ASSISTANT 全部接上；端到端核过（第 5 节） |
| S6 C1 | 本机 CPU 版已训练并登记 | `runs/local/recognizers/c1-xlmr-cpu`（冻结 10 层、2 轮、max_len 160）；以 external_candidate 登记在 `runs/local/c1-return`；`env.ps1` 已切到它。Colab 版（冻结 8 层、3 轮）未跑 |
| S7 页面 | 完成 | 复盘页「你的行为模式」；识别实验室 `#/lab` |
| S8 it_ticket_pilot | 只做了数据版 | `data/releases/it-ticket-v1`；可玩场景未做 |
| S9 实验 | 见第 2 节 | E3、E4、E5、E6、E7、E9（检索与范围）完成；E1 基线需重跑；E8 需重跑；E10 待跑 |
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
| E8 Judge 开/关 | **需重跑** | 旧结果只有 10 对且「开」组是规则回退版：待核验 0.60 vs 0.74，引用 0.99 vs 0.74，标签一致 0.65，冲突率 0.4。要在重启后的 C1 版上重跑「开」组 |
| E9 跨领域 | 检索与范围完成；C1 待跑 | pm_pilot 的 C4 拟合搬到 IT：AUROC 0.60/0.50；只用 IT 知识库单元拟合：0.986/0.949；IT 改写问题 e5 Recall@5 0.82/0.64 |
| E10 晚期融合 | 待跑 | `experiments/recognition/fusion.py` 已写好，跑完会写 `c1-xlmr-cpu/fusion.json`，产品端随即启用融合 |

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

### 4.1 先确认三处未经服务验证的改动

最后一次重启后改了这三处，只做过导入检查：

1. `recognition/relation.py`：C1 可用且存在 `fusion.json` 时，与数值规则做晚期融合（规则「无可比依据」时只用 C1）。
2. `recognition/judge.py`：识别器核验不再返回 unsupported，只在引文全部落地时放行，其余交 LLM。原因：Judge 的解释句是批评（「计划 50 人超过容量 30 人」），被 C1 当成断言判为矛盾，导致两项被打回。
3. `recognition/behavior.py`：首次提交前不出现「调整」阶段（冲突时回到规则阶段）。

### 4.2 命令

```powershell
cd D:\HuaweiMoveData\Users\13736\Desktop\AIS\5002GPJ
$env:PYTHONUTF8='1'; $env:CAREER_LAB_RECOGNIZERS="$PWD\runs\local\recognizers"
# 1. E10：选融合权重，写 fusion.json
.venv-encoder\Scripts\python -m experiments.recognition.fusion --encoder runs/local/recognizers/c1-xlmr-cpu
# 2. 重启开发服务（识别层开、C1 登记）并冒烟
$env:RC_OFF='0'; . runs\local\dev\start.ps1
.venv\Scripts\python -m scripts.recognition.smoke --language zh --continue-code
# 3. E8：删掉 e8_raw_on_*.jsonl，重跑「开」组（中英两个进程），再 compare
.venv\Scripts\python -m experiments.recognition.judge_ab run --condition on --count 2 --languages zh
.venv\Scripts\python -m experiments.recognition.judge_ab run --condition on --count 2 --languages en
.venv\Scripts\python -m experiments.recognition.judge_ab compare
# 4. 加权基线 + C1 堆叠/融合（CPU 约 1 小时）
.venv-encoder\Scripts\python -m experiments.recognition.baselines --encoder runs/local/recognizers/c1-xlmr-cpu
# 5. E9 的 C1 部分
.venv-encoder\Scripts\python -m experiments.recognition.cross_domain --encoder runs/local/recognizers/c1-xlmr-cpu
# 6. 发布到实验室页
.venv\Scripts\python -m experiments.recognition.publish_lab --c1 runs/local/recognizers/c1-xlmr-cpu
cd apps\web; npm run build
```

注意：步骤 3 跑 E8 期间不要改 `src/`；不要和步骤 4 同时跑（CPU 打满后 SQLite 会锁超时，会话报 500）。

### 4.3 之后

- 冒烟里观察到 C1 把「我们计划安排 50 人参加试点」判成 insufficient、把「住宿上限 500 元」判成 contradicted；E10 融合后复查。更好的 C1 走 Colab（第 7 节）。
- 实验室页的 E4、E8、E10 图表还没做（`publish_lab.py` 已会发布 `e8_judge.json`；`lab.ts` 需加对应小节）。
- S8 可玩场景、E2、人机判别、S10 报告。

## 5. 已核过的验收

- S1：测试卡、同事回复、反馈页逐项、复盘页汇总行在全规则回退下都显示灰色署名（浏览器 DOM 核对）。
- 3.1：含「安排 50 人」的作品，R2.support 解释以 `[识别一致]` 开头（C1 版）；`GET /recognition` 有 relation、retrieval、decision、arbiter 记录；不设 `CAREER_LAB_RECOGNIZERS` 时回到原行为。
- 3.2：同事回复下有意图与依据核查署名；`learner_state` 出现在 `role_context` 私有审计对象里。
- 3.3：「火星天气」域外；「住宿报销上限」全范围域内、排除政策后域外。漂移标注未做端到端验证（这一版场景很难触发索引前后版本不同）。

## 6. 怎么跑

- 开发服务：`. runs\local\dev\start.ps1`（DeepSeek 评审，端口 18562/18560，3 个 worker）。`$env:RC_OFF='1'` 不带识别层；`$env:RC_SYNTHETIC='1'` 模型槽退回合成线性回传。前端 `apps/web` 下 `npm run build`，再 `npm run preview -- --port 18560`（设 `ROLECRAFT_API_TARGET=http://127.0.0.1:18562`）。
- 数据服务（全本地模型，端口 18572）：`. runs\local\data\start-data.ps1`；轨迹生成器 `scripts/recognition/run_strategies.py`。
- 冒烟带 `--continue-code` 会打印继续码，在浏览器首页「有继续码？」输入即可打开该会话看界面。
- 合成脚本：`scripts/recognition/{synth,synth_relation,synth_domain}.py`；实验脚本：`experiments/recognition/*.py`，结果在 `experiments/recognition/results/`。

## 7. 需要人决定或动手

- **Colab 训更好的 C1**：打开 `runs/local/colab/colab_train_c1.ipynb`，上传同目录 `c1-bundle.zip`，下载 `c1-out.zip` 解压到 `runs/local/recognizers/c1-xlmr/`，然后 `python -m experiments.recognition.relation.register_c1 --train-out runs/local/recognizers/c1-xlmr --out runs/local/c1-return-colab`，把打印的变量写进 `runs/local/dev/env.ps1`，再从 4.2 的 E10 起重跑。
- ROLES / ASSISTANT 槽要不要也接 DeepSeek（现在同事回复是本地模板）。
- 何时提交、怎么切 PR（设计第 10 节建议按 S 步拆）。

## 8. 与设计的出入（代码注释里都写了）

1. `PROMPT_VERSION` 没改（发布包钉死 v1，改了服务起不来）；识别段落只在输入含 `recognition` 时追加，修订号记在识别记录里。
2. 场景包里不放 `runtime/recognition.json`（发布包有 hash 校验）；检索方法与 e5 校准锚点在 `recognition/assistant.py`。
3. 助手识别只作用于学员自己的测试；隐藏探针与工程师重放走原规则。
4. ROLES 的识别上下文在 `RoleService.generate` 开头建立（私有端口在那时就对 prompt 求哈希）。
5. C4 的 scope_on 定义为「开了范围过滤且排除了政策类领域」。
6. SUPPORT 槽：识别器只放行不否决（4.1 第 2 条）。
7. 行为异常规则 1 泛化为「世界变化（里程碑通知或索引刷新）后未再测就提交」。
8. 人机判别未做（无 Agent 轨迹）；S8 只有数据版。
9. 助手 C2 用 e5 而非 RRF（E3 的结论）。

## 9. 坑

- 改了 `src/` 下任何 .py 都要重启服务（`execution_restart_required`）。
- Bash heredoc 会吃反斜杠；含 `\n`、`\\` 的补丁用 Write/Edit 或写成脚本文件。
- Claude in Chrome 窗口被最小化时截图超时、布局宽 0；改用 `msedge --headless=new --screenshot=<png> --window-size=1280,3000 <url>`。
- `GET /recognition`、`/behavior` 的响应信封是 `{"result": {"result": {...}}}`。
- 重 CPU 负载 + 多 worker 时 SQLite 锁超时（500 `OperationalError`）。
- DeepSeek 起草材料时会把账本键名写进句子；`synth_domain.py` 已改为自然语言账本 + 键名回填 + 拒收。
- Windows 下远端单测约 70 个平台性失败（文件锁、symlink、权限），与本次改动无关；前端 `score-range.test.ts` 在 CPU 满载时会 5 秒超时。
