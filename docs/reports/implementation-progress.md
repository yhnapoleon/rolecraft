# 后端实施进度

计划：`docs/plans/career-training-implementation-plan.md`；用户授权日期：2026-10-02。

本轮范围：依次落实Task 2–9、Task 12可独立实现的候选注册、Task 13后端反馈与回放、Task 14可自动验证的演示和打包。排除前端、Task 10 SFT、Task 11 GRPO及依赖其真实模型的对照实验。真人试用、人工双标、课程视频与个人报告不能由自动测试冒充完成。

沿用executing-plans及TDD流程，每项完成后追加真实命令、结果、偏差与待验收事项。工作区尚未采用Git，本轮继续在用户指定目录保存源码与运行证据，不自动上传或发布。

接口裁定：Task 2的历史视图由持有场景及快照存储的SessionStore.project_view提供；纯project_view需显式接收spec/events，不能仅从WorldState凭空读取历史与角色定义。Task 5从固定submission快照组装证据；Task 6返回规则评价和未知语义项；Task 8与9只使用按分区授权的数据。

| Task | 当前状态 | 验证与边界 |
|---|---|---|
| 1–6 | 后端代码及工程验证完成 | 私有权限、版本、事务、任务、API、证据、规则反馈 |
| 7 | 数据管线与pilot完成 | 中文90项+公开85项；正式双标待做 |
| 8 | Eval工程验证完成 | resume、独立grader、错误分母、paired diff |
| 9 | CPU监督基线与E1 dev完成 | 融合无增益；test未参与选型 |
| 10–11 | 本轮排除 | SFT/GRPO后训练 |
| 12 | 候选注册完成 | 后训练对照、confirmatory test待做 |
| 13 | 反馈/回放后端完成 | 前端排除；规则升级至rules-v2 |
| 14 | 自动演示、干净安装、打包完成 | 真人试用及课程材料待做 |

最终验证：67 tests通过（含PostgreSQL），干净解压环境66通过/1项PG跳过；详细证据见task-14-tests.xml、task-14-clean-install.json和final-results.md。下方逐项记录保留当时测试数量与规则版本，最新修订以最终验收为准。

## Task 2：代码与本机数据库验证完成

全量29 tests通过，包含真实PostgreSQL持久化恢复；报告task-02-tests.xml。schema 001，SQLite支持离线测试，PostgreSQL使用55439端口。历史视图从指定快照生成；事件、状态、幂等结果同事务。未做Git提交。

## Task 3：代码与真实模型联调完成

全量33 tests通过；DeepSeek deepseek-chat真实回合2轮，含read_material工具反馈，结果见task-03-live-model.json。任务支持lease/heartbeat/retry与过期worker fencing；API调用不是exactly-once，本地回合提交幂等。默认本地模式明确标注。

## Task 4：后端代码与API流程验证完成

全量35 tests通过。真实BM25文本检索、可替换生成接口、源/索引/配置版本、成果及不可变提交、会话令牌鉴权已实现；API重启恢复通过。UI按用户要求排除，非实现者试用与演示录屏未完成。

## Task 5：输入隔离与组装代码验证完成

全量38 tests通过。按submission时点与learner权限构建oracle/retrieved输入、中性引用及来源映射；input_hash白名单校验；溢出显式overflow，检索模式保守标记missing。10份真人/人工成果核验未执行，当前为工程验收。

## Task 6：规则与反馈聚合代码验证完成

全量47 tests通过；容量批准例外、资源约束、三正三反、未知分数上下界与coverage、全部不适用均验证。开放语义项保留待核验，不冒充完整Judge。规则版本rules-v1，场景rubric未修改。

## Task 7：数据管线与pilot发布验证完成，人工验收待完成

全量52 tests通过。已生成90条中文G0试运行样本（6因果模板，45/30/15分区）并审计；真实下载ContractNLI，导入5份原始train合同共85项，保留span偏移与原标签，来源hash/许可证见task-07-public-source.json。真实数据发现空白span，已回归修复以保留原文。未冒称双标或正式800–1500条研究发布。

## Task 8：Eval基础设施与双候选冒烟完成

全量55 tests通过；30项dev数据上常量候选accuracy=1/3、故障候选30个infrastructure errors且端到端准确率0；断点恢复不重复调用、replicate新建试次、引用充分性与多组证据验证通过。已生成manifest/predictions/metrics/errors/report与paired diff，group bootstrap按模板；测试分区未运行。

## Task 9：CPU监督基线与E1开发集实验完成

全量57 tests通过；实际训练TF-IDF Logistic、字符n-gram MLP(32,16)和概率融合，非预训练Transformer/非SFT。dev Macro-F1分别0.7661/0.6667/0.7661，选alpha=0，融合无增益；保存权重hash、训练输入ID和独立Eval报告task-09-e1-dev.json。正式大样本复核待数据人工验收，test未用于选型。

## Task 10：本轮排除

用户明确排除后训练；未进行SFT、下载底座或GPU训练。

## Task 11：本轮排除

用户明确排除后训练；未进行GRPO、奖励训练或continued-SFT。

## Task 12：候选注册代码完成，后训练对照与确认性测试待做

全量59 tests通过；3个真实CPU模型与dev报告已注册，绑定模型/数据/rubric/报告hash；篡改失效、缺指标拒绝注册。全部标记relation_eval_only且不允许替代产品criterion Judge；没有SFT/RL候选或独立test结论。

## Task 13：反馈任务与回放后端验证完成

全量60 tests通过；后台反馈job、固定submission/rubric/rules-v1、原版本证据链接、回放不调用模型且不追加业务事件、刷新重取结果通过。前端排除；主任务及两变体整体验证随Task 14演示执行。

## Task 14：可自动执行的后端交付完成，人工与课程材料待做

全量67 tests通过（含真实PostgreSQL）；主任务和两个变体均submitted且重开回放一致；真实DeepSeek HTTP/独立worker完成；实际PostgreSQL容器重启恢复通过。源代码包在独立解压目录uv sync后66 tests通过、1项PG跳过，并完成demo、数据重建/审计、CPU训练和eval smoke；见task-14-clean-install.json。首次干净安装暴露pytest父目录缺失，已修复并从新目录重验。前端、真人试用、正式双标、slides/视频/个人报告未冒称完成。

## 最终审查与修复（2026-10-03）

独立审查四项问题均已处理：只采用提交配置对应测试、缺失事件/测试日志保留未知、待核验PARTIAL允许上界达MET、主管模拟审批具有API入口。另修复末次job租约过期终止、训练审计读取test gold和首次安装pytest临时目录。新增规则版本rules-v2，历史rules-v1反馈不被覆盖。模型卡见model-card-pilot.md；没有隐藏融合零增益结果。

最终干净包额外复现E1评价与3个候选注册，8条命令全部通过；脚本scripts/evaluate_baselines.py可独立重跑。最新HTTP扩容→测试→提交→独立worker反馈链路成功，见task-14-live-final.json。交付压缩包为dist/career-lab-backend-v1.zip，代码与干净安装验证包逐文件hash一致。

## 场景实验阶段 Task 1（2026-10-03）

完成6能力族、24结构模板矩阵及G0/G1/G2标注规范，固定模板分区。新增三值逻辑与结构覆盖测试2项通过；后续数据继承此协议。计划见../plans/scenario-experiments-plan.md。

## 场景实验阶段 Task 2（2026-10-03）

首批100条通过逻辑/证据校验；两个独立盲标CSV与导入、分歧统计工具已实现。全量71 passed、1项PG skipped。人工实际提交0项，一致率为null，保持pending；没有伪造G1。受控G0实验继续，不替代人工验收。

## 场景实验阶段 Task 3（2026-10-03）

正式受控G0 v2为1152项，24结构模板，训练576/开发288/测试288，标签各384项。完成线性、MLP、融合训练及常量/有限规则/混合对照、E5检索和E6风格/排序/事实对照。开发Macro-F1：0.5455/0.3692/0.5455；有限规则初版0.5333（弃权误计，修复后0.5000）、混合0.7076。融合无收益；MLP训练loss=0.0265但dev弱，提示过拟合。报告controlled-v2-dev.json；未读取test做候选选择。独立审查与最终回归进行中。

## 场景实验阶段 Task 4（2026-10-03）

完成一次独立审查及回归，81 tests通过（含真实PG）；冻结dev选出的hybrid与代码/数据/模型/逐项结果，正式test Macro-F1=0.6496，误扣分0.3333，joint=0.3333。数值及人工门槛未通过，因此只接入shadow relation API；真实HTTP 200，历史权限、幂等复取、状态不变验证通过。详情controlled-v2-results.md、controlled-v2-test.json、controlled-v2-live-shadow.json。

四项自动工程与受控实验均已执行；首批100项人工双标仍为0，完整G1语义验证和正式自动评分部署待完成。前端与后训练继续排除。当前没有Git提交，版本用不可变目录与hash记录。

场景实验最终交付：独立解压环境16条复现命令全部成功，80 tests通过/1项PG跳过，重新生成1152项、训练、冻结与test的主要指标一致。源码包dist/career-lab-experiments-v2.zip；数据/权重/已冻结实验产物另包dist/controlled-v2-data-models.zip。

## GitHub项目归档（2026-10-03）

用户授权上传至https://github.com/yhnapoleon/rolecraft。已初始化main、配置origin并整理RoleCraft README，包含启动、API、课程三项实验、v2结果与待完成事项。暂存源码/场景/配置/脚本/文档/测试共195文件，密钥扫描通过；API key、数据库、运行缓存、原始资料与个人标注不纳入仓库。使用Git暂存内容导出到全新目录，锁定安装后81 tests通过（含真实PostgreSQL），一条上游弃用警告。历史实施记录中的“无Git”描述保留为当时状态。
