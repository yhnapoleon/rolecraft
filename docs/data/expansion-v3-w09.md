# W09 参考 Agent 模块

本包处于 implementation_only / partial 阶段。独占模块已经实现并测试；真实 W06 API、独立 worker、W01 快照恢复、W05 终态评价、合格结构及实际 LLM 的 E4 尚未接通和执行。

## 输入与边界

基准为 80cf1f6189cd25610d609f44283ff9668582d759。输入契约为 draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e，来自031放行的不可变归档。12个上游 contracts 文件只读安装并核验原hash，属于输入，不属于本包交付。没有从032活动工作区import。

未修改公共API、CLI、contracts、存储、reducer或依赖锁。模块只使用现有依赖。公共接线详见 configs/expansion-v3/w09/shared-file-requests.json。

## 可调用实现

- belief.py：只从 Observation 中实际可见的原句更新 BeliefState；保留来源与时点，同一事实不同原句形成待核对冲突。known 表示观察过这条陈述，不表示独立核实为世界真值，更不表示理解。模型prompt成员及未披露记忆不能补齐知识。
- legal.py：可用动作与参数的保守校验，支持发布工具所需的JSON Schema子集；未知约束拒绝而非忽略。服务端仍负责最终权限、版本及语义校验。
- policies.py：固定清单、普通工具循环及主动获取入口草稿。主动入口目前只有观察事实整理与不同提示词，尚缺显式unknowns/hypotheses/current_plan及信息效用计算。普通循环只得到目标、当前观察及实际历史；主动获取额外得到信念、候选与待查目的。两种模型策略只请求简短可审查理由。候选副本结果不会回灌正在比较的策略。
- runner.py / journal.py：派发前原子保存Command、逐次模型预算预留/usage、动作失败、有限重试、异步job有界查询、停止及恢复。单run互斥锁避免并发推进。恢复通过独立有界窗口按原request_id只读复取；新动作预算或主壁钟耗尽仍可复取已发生结果。
- ports.py / model.py：HTTP路由与解码由集成人注入。拒绝跨站路由/重定向，错误不转存服务端私密正文。模型桥接复用现有ModelAdapter，禁止内部隐藏重试；旧适配器不支持seed/decode控制的事实明确保留。
- suite.py：校验文件hash、runtime源码身份、策略配置冻结、lineage/split、同预算/同评价及普通/主动同模型配置；确认性test需已开放且包含该候选的TestCampaign。失败留在分母；运行结果不自动宣布研究验收通过。
- acquisition.py：消费W01 SnapshotPort进行候选副本执行，验证完整动作末点、父hash与新session身份；原始成本未知时写null。它没有自建世界引擎。
- cli.py：提供 agent-suite 注册函数及模块CLI。未挂载实际factory时返回JSON错误和非零码。

## 本包验证命令

从本包独立worktree根运行，使用它自己的.venv：

~~~sh
env -u PYTHONPATH .venv/bin/python -m pytest -q tests/unit/test_w09_core.py tests/unit/test_w09_suite.py tests/unit/test_w09_copies.py tests/integration/test_w09_http.py
env -u PYTHONPATH .venv/bin/python -m career_lab.reference_agent.cli agent-suite --help
~~~

测试中的环境、模型、snapshot服务、评价及HTTP MockTransport均明确标为synthetic/test double。测试实际执行上述产品模块，但不能代表真实角色模型、API/worker、场景成功率、数据发布或E4实验。

模块CLI可验证由集成人冻结的suite：

~~~sh
env -u PYTHONPATH .venv/bin/python -m career_lab.reference_agent.cli agent-suite --suite /absolute/suite.json --root /absolute/frozen-input --validate-only
~~~

suite文件使用SuiteSpec，引用RunManifest、policy配置、SplitManifest及可选TestCampaign的真实FileRef。运行factory必须由受信任的集成代码提供；不执行manifest中的任意Python入口。factory签名为 factory(policy_name, policy_config, manifest) -> ReferenceRunner。实际全局CLI尚未挂载，不能用示例假称已经可运行E4。

## 恢复和结果解释

同一run再次执行必须显式resume；输入、策略配置或预算不同拒绝复用原输出目录。已完成checkpoint原样读取，不重调模型。已派发但未决的Command只通过reconcile读取原请求结果；不因结果未知重新POST。pending job只查询原job。缺只读查询接口、找不到结果或窗口耗尽保持unresolved，再次resume可重新核对。每次恢复默认最多2次只读请求、10秒独立窗口，reconcile_attempts与action_attempts分开记录。未决状态不再被failed/stopped终态短路。模型调用期间崩溃时usage保持unknown并停止，避免悄悄重新付费。恢复不提供远程模型exactly-once保证。

model_calls、action_attempts、polls分别记录。token预算在派发前以消息UTF-8字节、输出上限及协议余量预留，已知usage用实际值结算，未知usage保留预留并明确标识；预留不是供应商实测token数。环境内部角色调用成本尚需W06回传，现阶段不能宣称已具备全系统成本验收。指定currency_limit但无价格预留接口时拒绝模型调用。wall预算跨resume保留起点；请求必须遵守剩余timeout，已经发出的远程调用无法由本模块撤销。

policy的proposed_complete或checklist_exhausted只产生未核验停止。只有独立evaluator返回同一EvaluationBundle下的明确接受，运行才标completed；接受no_go无需solutions ID白名单。completed也只表示该次评价结果，suite的research_acceptance仍为not_assessed。

checkpoint为恢复真源，其余manifest、steps、observations、belief、decision-points、errors和result文件由其导出。正式W07导出仍需经过冻结导出器，不能把模块sidecar直接当发布数据。反馈、隐藏事实、未来事件、solutions不得进入policy输入。

## 后续验收

先由032/W01提供正式结果协议、snapshot服务与新的输入revision，031以update-context登记后迁移。接入W06真实凭据/投影/工具与worker、W05固定终态评价及实际模型的计量端口，再执行W09全部AC及四个开发结构、两个未见结构的E4。没有实际模型/结构时维持partial。

W12晚于W09开发或调优时使用W11新生成并隔离审查的至少两个新因果结构做确认性test。W09已开启test仅作回归，其反馈不进入模型、提示词、技能和优化选择。共享campaign只限首次开放前已冻结的所有比较。

## R2 模块修复与适配要求

031独立审阅的R1—R4已在本包局部收口，仍需独立复审与正式接口实测。

- 只读复取必须由EnvironmentPort.reconcile提供；HttpBindings.request_result_path仅用于GET已存结果。返回None表示未知，不授权重做动作。原r1的终态checkpoint只要仍有pending，也进入只读复取。
- 成功ActionOutcome必须有服务端可信request_id或ActionBoundary；与当前Command不一致即拒绝。ObservedStep.id按来源原样保存，command_request_id另记，不推测两者相等。codec不得把客户端请求ID直接填回当作服务端关联证明。
- SnapshotPort.prefix_digest提供W01定义的规范化前缀身份。每个restore必须返回指定目标session，候选间唯一，完整state版本/资源/里程碑/映射后的cycle一致，prefix_digest一致后才执行。W09不自定义另一个公共前缀算法。
- memory/learner_memory都需要可信source_authorizer根据实际来源认定learner_known。仅凭频道名不能授权。未知来源被隔离，只记录源hash；角色私有/prompt-only明确拒绝。合法学员记忆进入belief与模型请求。共同投影同时约束更新和最终policy payload，避免只过滤belief。source_authorizer是集成端口，正式来源字段仍交W01/W04/W06冻结。

测试是synthetic回归，不能证明真实私有信息曾泄露或真实API/worker已经通过。r1归档与回执保持不变；r2证据在独立运行目录。

## R3 定向修复

模型可读内容统一由projection.model_view构造，并在交给策略前再次使用：观察、history正文及引用quote、主动获取belief都要回指已授权的观察片段。原始step留在受限审计中，不能整包送入策略。无法证实来源的摘要正文暂不透传；合法历史披露通过disclosed_sources继续可读。未知memory及不受支持的quote不会因出现在history/引用中重新进入模型。

候选同步返回及pending接纳均须带可信request_id或ActionBoundary。每条结果另存command_request_id和原command，原服务端step ID不改写；pending记录session/request/job的明确绑定。resume_candidate只做一次有界只读poll，核对同一request及job后才接受结果；缺失或错配保持unresolved，保留原绑定，不接受其他请求正文或job。pending仍非完成，实际异步服务接线待补。

R3仅修复031复核指出的两处遗漏。115项模块回归及派生自031反例的定向探针通过；没有重复无关实验、使用付费模型或宣称真实信息泄漏/产品QA通过。

## 2026-10-07 限定返修与研究延期

按用户最新排序，仅修当前已证默认配置、异常处理及快照协议缺陷后交接：AdapterModel将45秒默认timeout按单次剩余预算克隆下调，不改共享adapter；未派发的前置失败保留原错误且不计调用预算。ProtocolError转换后按原code记录；运行中job保留waiting，错job拒绝，确定性私有观察隔离并终止自动重试。

兼容检查使用W01 r3的已归档924文件源码（source digest 4e0909bb…ce6b），不使用活动源码。支持qualified cycle identity key及r3规范的parent prefix digest；已用真实SQLite恢复副本，环境factory缺失仍准确记environment_adapter_unavailable，未运行候选动作或E4。这是参考候选兼容检查，不是正式输入迁移。

明确延期：信息动作的合法性/状态变化/新增事实等环境推导量尚未实现；主动Belief的unknowns、hypotheses、current_plan和时效适应尚未完成；三入口存在不能计作完整三策略研究。E4、真实provider计量和完整接口验收保持未完成。W12已停止并保全。
