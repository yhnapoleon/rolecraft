# 交接：进入视频和报告阶段（技术部分收尾）

日期：2026-10-21　读者：准备录视频、写报告的组员　上一份技术交接：[公开数据与 E11–E15](handover-public-data-20261021.md)

## 0. 现在的状态

- 技术部分收完了。PR #63–#66 合进 main 后，main 上有：识别层和三个 LLM 入口的装配、堆叠集成、8 局预置演示会话、识别实验室页、以识别为中心的 README 和架构图、公开数据和 E11–E15 的脚本与结果。
- **产品里跑的关系判定链是「堆叠集成 + 数值限额规则」**（XLM-R 交叉编码器与 TF-IDF + 特征 LR 堆叠，α = 0.4 晚期融合），relation-v3 test 0.698 / 0.635。
- **E15 的多语言 NLI 交叉编码器（0.903）只做了离线评测，没有接进产品。** 报告和视频里可以讲它，但要讲成「离线评测的升级版句对分类器」，不能说产品在用它。
- 演示怎么跑：[`handover-recognition-demo-20261017.md`](handover-recognition-demo-20261017.md) 和 [`demo/README.md`](../../demo/README.md)。录好的 8 局会话用 `demo_pack import` 导入，不调模型；完整系统要设 `CAREER_LAB_RECOGNIZERS` 和 `CAREER_LAB_RELATION_ENCODER`（README「Running」一节）。

## 1. 课程要什么（`PRS-PatternRecognitionSystems-Practice-Module 7.0 - FT.pdf`）

| 要求 | 页 | 现成的材料 |
|---|---|---|
| 四项技术里至少做三项：监督 / 无监督、ML / DL、混合 / 集成、智能感知 | 9 | 四项都有：监督（关系判定、意图、堆叠）和无监督（范围检测的单类马氏距离、行为 HMM 和聚类）；ML（TF-IDF + LR、随机森林、HMM、DTW）和 DL（XLM-R、mDeBERTa、e5）；集成（堆叠、规则与模型晚期融合、RRF）；感知（学员行为事件流 → 符号序列） |
| 可运行系统 | 15 | main + `demo/` |
| 数据集 | 15 | `data/releases/`，清单 [`docs/data/DATA_INVENTORY.md`](../data/DATA_INVENTORY.md) |
| 报告：工具与技术、系统设计与模型、系统性能、发现与讨论 | 15 | 见第 2 节 |
| 代码、模型文件 | 15 | 仓库 + `runs/local/recognizers/`（清单第 4 节） |
| 10–15 分钟视频、两次展示的 slides | 15 | 架构图 `docs/figures/architecture.{svg,png}`；识别实验室页 `#/lab` 有 E1、E3–E10 的图 |
| 每人 1–2 页个人报告、互评 | 16 | — |
| 一个 ZIP 交到 Canvas | 16 | 打包按 DATA_INVENTORY 第 1 节，**别把 `ds.txt`、`openai.txt` 打进去** |

## 2. 报告四块各用什么

写之前先读 `AIS/.claude/skills/ais-design-writing/SKILL.md`（写法）和 `references/rolecraft-mechanisms.md`（机制、数字、不要说的话，已更新到 E15）。对外一律用识别器的名字，不用 C 编号。

| 报告一章 | 内容 | 出处 |
|---|---|---|
| 工具与技术 | 每个识别器的方案名、模型、库 | README「Recognisers」表；机制速查第 4 节 |
| 系统设计与模型 | 第一节写「系统识别什么」；然后是流水线：感知 → 预处理 → 表示 → 识别 → 决策，三个 LLM 消费识别结果 | 架构图；机制速查第 2–5 节 |
| 系统性能 | 项目自建数据上的 E1–E10；公开数据上的 E11–E15 | 第 3 节的表；`experiments/recognition/results/`；[`docs/data/public-sources-v1.md`](../data/public-sources-v1.md) 第 6、8、9、10 节 |
| 发现与讨论 | 第 4 节的局限、与 proposal 的偏差 | 第 4 节 |

## 3. 数字总表（报告「系统性能」一章用）

断言级 macro-F1 都是 test，中 / 英，除非另注。

**项目自建数据（产品）**

| 任务 | 结果 | 出处 |
|---|---|---|
| 断言—证据关系，产品判定链（堆叠 + 规则） | 0.698 / 0.635 | `e1_stack.json` |
| 同上，堆叠单独 / XLM-R 单独 / 最好的经典模型 | 0.713 / 0.633；0.656 / 0.608；0.646 / 0.572 | `e1_baselines.json` |
| 决策层：20 % 送人工时的误扣分率 | 4.2 % → 0.7 % | `e1_stack.json` |
| 范围检测 AUROC | 0.977 / 0.953 | `e5_scope.json` |
| 换领域后重新拟合 | 0.986 / 0.949 | `e9_cross_domain.json` |
| 检索，改写问题 Recall@5 | e5 0.82 / 0.79，RRF 0.65 / 0.57，BM25 0.49 / 0.36 | `e3_retrieval.json` |
| 提问意图准确率 | 0.946 / 0.824 | `e7_intent.json` |
| 行为：步骤扰动 50 % 时的策略准确率；异常 AUROC | DTW 0.71；HMM 似然 0.90 | `e6_behavior.json` |
| 评审有 / 无识别摘要 | 给出标签 42.6 % / 38.9 % | `e8_judge.json` |

**公开数据（E11–E15）**

| 实验 | 结果 | 出处 |
|---|---|---|
| E11 产品判定链直接迁移 | relation-v3 0.658；public-synth 0.687；ContractNLI / VitaminC / CFEVER 0.377 / 0.385 / 0.340 | `e11_transfer_public.json` |
| E12 只在浅层（词法 LR、元学习器）混训 | ContractNLI 升到 0.50–0.56，域内掉到 0.46–0.47 | `e12_mix_public.json` |
| E13 范围检测（MASSIVE）| 0.961 / 0.940 | `e13_scope.json` |
| E13 检索（PrivacyQA，稠密）| Recall@5 0.770、MRR 0.562 | `e13_retrieval.json` |
| E14 根因 | C1 只认出 ContractNLI 6.5 % 的金标支持条款、VitaminC 7.6 % 的矛盾修订；DeepSeek 复核 390 条，错误绝大多数是模型真错 | `e14_*.json` |
| E15 多语言 NLI 交叉编码器，混合微调 | relation-v3 0.903；ContractNLI 0.806；VitaminC 0.792；CFEVER 0.641；public-synth 0.825 | `e15_nli_mix.json` |
| E15 用于回复核查（三个单元合成一段读） | 合成回复三分类 0.928、泄露 F1 0.94；RAGTruth AUROC 0.462 → 0.735 | `e15_reply_mix.json` |

报告里最有分量的一条线是 **E11 → E14 → E15**：合成数据训的识别器在人写的断言上接近随机 → 根因落在句对分类、复核确认是真错 → 换成预训练过 NLI 的多语言交叉编码器并混训，五份 test 全部大幅提升。

## 4. 局限和偏差（只写进报告「发现与讨论」，不进视频和 README）

- 自建数据由 DeepSeek 生成、DeepSeek 盲判复核，生成和复核同厂家；没有人工双标。
- E15 只做了离线评测，产品仍用堆叠 + 规则；只训了 1 轮，没有留一来源。
- ContractNLI 只有 17 条固定假设，按合同划分，0.806 是「没见过的合同」，不是新断言。
- E15 的底座训练数据含 FEVER，VitaminC、CFEVER 同属维基体裁。
- 真实大模型回答（RAGTruth）上的回复核查仍弱：AUROC 0.735，精确率 0.225。
- 真实行为序列上：tau-bench 成败识别 macro-F1 最好 0.674（每类 HMM）；Jira 关单前的序列预测不了结局。
- 与 proposal 的偏差：SFT / GRPO 没做（评审是 DeepSeek）；人工双标换成了 DeepSeek 盲判；同伴试用只有协议，没有记录。
- 机制速查第 10 节「不要说的话」全部适用。

## 5. 本地工作区

本机工作区停在 `local/deliverables-20261019`，#66 的文件是未跟踪副本。切到 main 拉取之前，先删掉这些副本（清单见上一份交接第 0 节），否则 git 拒绝覆盖。
