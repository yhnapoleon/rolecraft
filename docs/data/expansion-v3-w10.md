# W10 分支与过程诊断模块

当前为 implementation_only / partial。已实现独立映射、前缀比较、SQLite分支repository、准备/恢复守卫、事件事实诊断与结果比较；真实引擎恢复、真实W09轨迹、W05两侧评价及E7尚未接通。fixture验证不能替代必需验收。

## 输入和所有权

基准80cf1f6189cd25610d609f44283ff9668582d759。输入为031指定的draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e，12个上游contracts文件原样只读安装。W10没有读取或import W09活动源码。

源码限于branching、diagnostics/v2、本包测试及本说明。公共contracts、API、CLI、storage、reducer和锁文件均未改。运行库独立放在本包输出目录；BranchRepository拒绝含其他产品表的数据库，避免误接稳定运行库。

## 已实现接口

### 映射与前缀

mapping.validate_prefix重新核验SnapshotExport hash、完整动作事务边界、事件连续性、对象版本及产生时点、跨对象引用闭合和无环依赖。缺失对象、未来引用、未知对象/事件codec、未知事件字段均明确失败。

ObjectCodec使用已有Pydantic模型，EventCodec显式列明引用字段和普通字段。当前对象codec覆盖task、work_product、share、cycle、review、submission、feedback、business_request、business_decision、config和test。事件类型由集成端注入，不能凭文本猜测字段。

make_plan/remap_snapshot对session、对象、event、transaction、request及当前snapshot生成确定映射；版本号和业务值保留。嵌入配置和EvidenceRef同样重映射；普通正文不做字符串替换。LegacyProvenance保留为惰性来源记录，不将其历史ID解释为活动引用。明确声明的外部场景引用保留对象ID并换成子会话引用。

cycle.base_state_ref与source_return_id按已核对的W01 r3语义作为来源字符串保留；role turn、额外派生对象和活动循环引用仍需正式codec。缺少定义时拒绝，不近似复制。产品structured_payload引用变化时重新核内容hash。

prefix.compare_prefix将实际恢复结果与已经完成ID重映射的预期快照逐字段比较，仅排除顶层snapshot.id及snapshot_hash；对象集合按固定顺序比较，事件时序保留。资源、版本、可见范围、正文及绑定不被忽略。

### Repository与服务

BranchRepository是真实独立SQLite实现，包含分支、状态历史及失败记录。按parent_session/request_id唯一；重复同内容返回同branch，不同内容同键冲突。多连接竞争由BEGIN IMMEDIATE串行化。准备、恢复和失败均有明确状态，不把prepared称为restored。

BranchService.prepare先验证parent RunManifest的FileRef原始字节/hash及会话绑定，再核前缀、生成映射并保存prepared快照。它不调用模型、reducer、审批或干预动作。缺对象/不支持前缀保留失败记录。输入parent及snapshot不改写。

BranchService.restore仅调用注入的RestorePort。它核子session、source snapshot hash、state、全前缀及prefix digest，并在父摘要前后不变之后才登记restored。失败不会留一个成功状态。真实restore端口未挂载；独立fixture验证了守卫行为。

研究权限在reserve/get/变更时核对session、research capability及到期时间。具有对象/动作子范围的凭据默认拒绝整个前缀操作，待公共授权服务明确扩展检查。AuthContext必须来自可信服务端，不能将本地构造fixture当作真实鉴权验收。

### 诊断和比较

diagnostics/v2/events.py接收内部DiagnosticEvent适配视图；真实集成必须从事件、实际披露及可见状态生成input/state指纹。只报告当前可见记录中的重复输入、连续失败、直接旧版本引用及日志不完整。prompt/private事件不能推定学员已知；旧版本引用不自动判无效；合理重复、系统故障、no_go和暂缓不产生能力负分。输出分开保留观察、解释边界、来源与不确定性，ability_score始终为None。未实现语义解释provider，不虚造理解或“最佳干预”。

comparison.compare_runs要求同EvaluationBundle、同父运行/结构/component/split及正确子branch身份。输出全部指标差异、退化和未知；seed/runtime变化标为descriptive_only。parent_run是统计分组单位，明确仅为模拟干预，未测真人学习效果。EvaluatedRun为本包内部适配对象；正式输入需W05/W09按冻结身份提供，不能用fixture指标作E7结果。

## 模块命令

从本包worktree及它自己的.venv运行：

~~~sh
env -u PYTHONPATH .venv/bin/python -m pytest -q tests/unit/test_w10_branching.py tests/unit/test_w10_diagnostics.py tests/unit/test_w10_comparison.py tests/integration/test_w10_cli.py
env -u PYTHONPATH .venv/bin/python -m career_lab.branching.cli branch --help
~~~

模块CLI提供branch create/compare注册函数。create需要可信factory装配授权、repository和真实RestorePort；未挂载返回JSON错误及非零码。compare的当前CLI只核验两个前缀文件，E7父子反馈比较用compare_runs；全局career-lab CLI未接线。

~~~sh
env -u PYTHONPATH .venv/bin/python -m career_lab.branching.cli branch compare --expected-prefix /absolute/expected.json --actual-prefix /absolute/actual.json
~~~

所有本包fixture均为synthetic；SQLite并发/持久化实际执行，engine/model/approval restore为明确double。没有运行真实E7、PG、HTTP/独立worker或外部模型。

## 交集成人的接线请求

1. W01快照导出需固定business/workspace/storage三维时点、完整ActionBoundary和该时点内的所有派生对象。确认历史snapshot锚点、对象kind/主键及全部实际事件codec；role turn、分享/撤销、拒绝和反馈不能遗漏。W10拒绝未知形状。
2. 将RestorePort接到W01内部research恢复入口。可由适配层验证W10的预期ID映射并提交原子恢复；实际结果必须精确匹配预期子namespace及全内容，禁止模型/审批外部副作用。统一prefix_digest规范，不能靠忽略字段让不一致通过。新公共定义由032冻结。
3. W05提供同一EvaluationBundle下的真实父/子反馈，W09提供冻结轨迹、实际模型调用/预算与父run引用；W07导出保持父结构/component/split，不能将子分支变成未见测试。事件诊断适配需明确实际披露与依赖版本，不能输入角色prompt事实当学员已知。
4. 公共CLI由032挂载branching.cli.register_commands(commands, factory=...)及w10_handler分派；正式API/UI只经可信AuthContext使用本包服务。新库/表及公共入口不由本包并发改动。
5. 首个真实联调切片：含作品→分享→测试→申请/拒绝→提交/反馈的父前缀，核hash后恢复，检查零模型/批准调用和父不变，再执行一项明确干预并取得同评价包的两侧结果。真实输入和接口到位后逐项补W10-AC01—AC11及E7，不把本轮prepared快照或局部测试算最终完成。

## 2026-10-07 · 首轮独立审阅修复

- 对已支持对象显式检查opened_at/shared_at/revoked_at/as_of的三维VersionPoint不晚于fork或对象创建窗口。不可变作品的证据按创建storage revision所对应的已提交动作边界校验；test/submission等还受自身as_of限制。保留全部时间字段和自由正文，不用删字段掩盖差异。更早workspace时点仍需公共协议提供明确依据，不以wall-clock猜测。
- 同branch准备/恢复持有独立本机文件锁；活跃写者返回branch_operation_in_progress，进程退出由内核释放锁。相同请求发现preparing时在获得锁后继续纯映射并保存同branch。锁限定本机独立工作目录，不宣称分布式锁。
- restore增加持久claim token和CAS完成状态。传输或未知异常记录unresolved；身份/前缀/父变化等已证实不变量失败仍failed。恢复保留原request与child，优先lookup_restore只读复取；只有端口明确声明idempotent_restore才允许同键重试写请求。未提供任一能力时保持未决，不改用新branch。原失败历史保留，晚到失败不能覆盖restored。
- 新增真实进程退出、并发互斥和CAS故障回归；所有引擎端口仍为明确double，真实W01/W05接线与E7保持未执行。

## 2026-10-07 限定兼容返修与研究延期

W01恢复会自行分配ID。新的W01BranchPort传入原父snapshot及确定目标session，消费其真实id_map；依据该映射构造预期子前缀，同时独立检查非身份字段没有改变，再与实际子快照逐字段比较。提供者的原父prefix digest与本地子前缀比较各用其明确语义，不把二者混用。恢复后的公开manifest采用真实映射，请求时预览manifest单独保留。

已用hash一致的W01 r3归档源码及独立SQLite执行：预览ID与实际ID不同但恢复成功、完整前缀一致、正文原样保留、父摘要不变、重复读取不再次恢复。当前仍使用登记的draft输入；归档候选兼容测试不等于正式迁移或人用QA。旧分支若未保留原父快照，明确报branch_source_snapshot_required，不猜测或改写旧证据。

已报的prepare瞬时存储异常保留preparing并可同键续接；同事件多个旧引用的finding ID区分来源。并发操作按内核锁明确返回在执行，稍后同键返回同branch。

按用户最新排序延期：诊断当前只有重复输入、重复失败、旧版本引用、缺日志四类；criterion_refs/具体干预建议、资源未批准/测试缺口/过早交付等其余检测、干预延续执行及完整E7主线尚未实现。不得把本轮分支准备/比较模块称为完整诊断或研究完成。
