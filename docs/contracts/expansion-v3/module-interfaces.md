# W01 公共接口与模块接线

本目录是扩建协议候选冻结。`manifest.json`的精确SHA-256（前缀`expansion-v3-`）是输出契约版本；独立审阅和集成状态由项目登记维护。本包提供公共类型、存储与模块挂载。PM v2场景、助手行为、开放工作区产品流程、角色记忆、v4评价、MCP和研究策略由各所属包安装，默认未安装时HTTP返回503，不把路由存在称为功能完成。

## 消费固定版本

从031指定的base及不可变源码patch/新增文件包重建，核对完整tree digest后使用自己的工作区与依赖。不得直接导入032活动worktree。旧`draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e`仍原样保留；正式候选相对草稿的差异见manifest的`changes_since_draft`。W01认领输入仍为`preflight`，不能把输出revision回填成输入。

所有公共模型可从`career_lab.contracts.v2`导入。API挂载类型在`career_lab.api.modules`，原子存储计划在`career_lab.storage.v2_store`。全部公开模型各有schema及通过解析的合成样例；这些样例说明协议形状，不代表业务记录、训练数据或模型质量。四切面及c0的组合样例同时保留在已冻结draft的examples目录。

## 模块所有权与接入位置

| 消费者 | 独占业务实现 | 公共输入与输出 |
|---|---|---|
| W02/W11 | 场景、事实账本、材料、助手及生成校验 | ScenarioBundle、RoleSpecV2、FactV2、AssistantConfig、TestRequestV2/TestResultV2、确定性审批策略；register_scenario及actions/tests/materials槽位 |
| W03 | 工作区事项、作品、分享、浏览器迁移与前端feature | TaskCreate/TaskPatch、ProductCreate/ProductEdit、ShareCreate/ShareUpdate、WorkspaceImport、ObjectWrite/Mutation |
| W04 | 角色连续记忆、披露、申请与还价 | RoleContext、DisclosureRecord、TurnInput、BusinessRequest/Decision、JobContextSnapshot |
| W05 | 情境反馈与修订体验 | ReviewInput、SubmitInput、BeginRevisionInput、EvidencePackageV2、FeedbackV2、rules-v4注册 |
| W06 | 外部Agent工具、委托与MCP包装 | AuthContext、Observation、ToolSchema、Command、DelegationInput、JobEnvelope |
| W07 | 数据导出、标注、审计 | DatasetRecordV2、四类ModelInput、AnnotationV2、LegacyAnnotation、SplitManifest、SnapshotExport |
| W08/W09/W12 | 模型、参考Agent、判断与优化 | 文件式Runtime/Evaluation/Candidate/ModelBundle、ModelPrediction、RunManifest、Budget、SkillSpec、TestCampaign |
| W10 | 历史分支和诊断产品/研究封装 | SnapshotService、ActionBoundary、BranchManifest、Trajectory、Diagnosis |
| W13 | 工程师配置任务与复跑 | EngineerPack、EngineerSubmission、RegressionReport、AssistantConfig |
| W14/W15 | 公共接线、真实产品QA与采用验证 | 全部正式冻结接口、FeedbackV2、AnnotationV2与EvaluationBundle |

冻结后`contracts/`、`storage/`公共入口、`api/app.py`及API注册、CLI/依赖锁和前端共享入口继续由公共集成人串行修改。模块新增文件写入031分派的独占路径；需要增字段、注册新模型或改共同入口时提交具体变更请求，列出消费者和兼容测试。

## HTTP与模块注册

`create_app(database_url=..., extensions=registry)`同时创建v1与v2存储。`ExtensionRegistry()`默认没有v2业务模块。

1. `registry.register_scenario(name, ScenarioRegistration(bindings, baseline_config, resources))`安装一个已经审查的场景入口。`POST /sessions`传`{"schema_version":2,"scenario":"已注册名称"}`创建v2。scenario/runtime/evaluation文件引用在会话创建时固定；客户端不能临时替换全局默认。W02/W11负责加载并校验ScenarioBundle全文件hash。
2. `registry.register(Operation(name, capability, request_model, handler, ...))`安装manifest的公共槽位。业务模块不得注册研究snapshot工具。写处理函数签名为`handler(TransactionView, Command, AuthContext) -> Mutation`，必须纯计算，无外部调用、无嵌套数据库事务；存储层统一提交。
3. 请求为显式`Command`：`schema_version=2`、`request_id`、`expected_version`（业务seq）、`expected_workspace_revision`、`operation`及类型化`payload`。operation必须匹配注册槽位；`action_name`可固定别名，例如`begin_revision`；`action_field="tool"`允许W02的ActionInput按实际tool核scope。路径中的对象ID必须与payload一致。
4. `mutates=False`的读处理函数接收`(TransactionView, parsed_payload, AuthContext)`并返回`response_model`。读取不追加业务记录。分页使用ResourcePage；可见事件可能有间隙，游标不等于学员实际已读。
5. 根session token解析出可信human executor；委托token解析出external_agent，不接受请求body自报executor。所有公共写入和恢复都重新验证能力、作用域、到期与吊销。内部研究授权和role_reader不挂在HTTP或tools中。
6. 控制面委托操作可用`service_mode=True`，仅允许delegations.create/revoke槽位，handler签名为`(V2Store, parsed_payload, AuthContext, request_id)`并返回声明的response_model。W06以session/request_id生成稳定grant ID，调用`issue_delegation`/`revoke_delegation`；同grant/同内容重试返回同token，改变内容或重新使用已吊销ID冲突。凭据不进入业务快照、导入或日志。

旧端点仍在原路径。旧六字段`/artifacts`只适用于v1；v2使用`/work-products`。新模块缺失返回`module_unavailable`，v2场景缺失返回`scenario_module_unavailable`。默认公开state只包含生命周期和版本元数据；场景资源与里程碑由W02/W06通过授权Observation投影，不直接输出内部世界状态。

运行中的`/openapi.json`和导出文件使用同一模型集合，`x-rolecraft-module-payloads`给出各槽位的payload类型。每个API仍需真实安装模块才能提供业务能力。参见`tests/contracts/expansion_v3/test_api.py`的真实HTTP适配器调用示例；其contract-test场景仅用于验证公共接口。

## 原子存储与版本

`V2Store.execute(auth, command, handler, capability=..., approval_policy=...)`在SQLite的BEGIN IMMEDIATE或PostgreSQL行锁事务中执行。对象版本、头指针、关系、事件、会话状态、幂等结果、后台任务入队在同一事务；任何失败全部回滚。

- `business_seq`只由显式EventDraft推进；普通草稿写入不产生政策事件。一次Mutation可包含多个事件，记录一个ActionBoundary，只有末点可分叉。
- `workspace_revision`在对象写入时推进；`storage_revision`覆盖每次已提交事务，包括同业务seq下的派生结果。固定快照必须同时给出这些版本，不能只用seq猜测拒绝/反馈先后。
- ObjectWrite包含精确ObjectRef、expected_head、已验证对象content、visible_to与全部dependencies。对象版本从1开始，配置编号另为0及以上。config引用的version与config_version各自核对。
- 对象ID在同一session内不跨kind复用；所有引用必须存在于同session、版本确切、可见且不形成循环。未来observed_at_seq拒绝。私人作品本体保持learner可见；角色必须经`read_shared_product`读取分享确切版本，撤销后不能通过旧链接再读。旧分享和旧提交记录保持不可变。
- 幂等指纹包含规范化Command、可信executor/actor/credential_id。相同key及语义返回原结果，换内容或执行身份冲突；无半次写入。
- 资源变化只能来自明确传入的确定性approval_policy，其返回BusinessDecision必须与事务所存决定相同。W02负责真实档位策略；W04追加协商。不允许通过一般state_changes修改资源。

`storage.v2_lifecycle`提供`record_review`、`record_submission`、`begin_revision`纯事务计划。前者固定主体/evaluation而不提交会话；submission固定cycle和bundle；begin_revision仅重开v2且引用当前cycle提交。W05在这些基础上实现评价与用户体验。

## 后台任务与恢复

`Mutation.jobs`中的JobRequest与对象/状态原子入队，sources及可信身份形成JobContextSnapshot。`registry.register_job("v2.<name>", handler)`与既有独立worker相接，handler接收`(TransactionView, JobEnvelope, AuthContext)`，可在事务外调用其获授权的模型，返回Mutation。

handler 的 TransactionView 来自入队或显式刷新后的固定 storage snapshot，并按当前授权过滤。sources 和 command 中的精确引用固定输入；无关草稿或另一反馈完成不使它失效。普通job另有不可省略的生命周期条件：会话必须active、当前周期open，并且与快照周期一致。仅 operation=`feedback.create` 且 subject 为 submission/review 的job是固定主体派生反馈；公共提交仍强制它只创建新FeedbackV2、绑定原subject/evaluation，不能带事件、资源、状态或其他对象写入。

| job类别与当前情况 | handler前行为 | refresh与写回 |
|---|---|---|
| 普通job，active且原周期仍open | 通过身份/来源/相关依赖检查后生成 | 每个输出expected_head必检；作品cycle必须是当前open周期，job不能写cycle对象 |
| 普通job，paused或submitted | needs_context / job_session_inactive，0次handler调用 | 此时refresh拒绝；恢复或开启修订后才可显式刷新 |
| 普通job，已开启另一个周期 | needs_context / job_cycle_changed，0次handler调用 | 显式refresh取新周期快照；原question、command/request_id与精确来源保留，不能偷偷写旧周期 |
| handler开始后发生提交/修订 | 提交前再次检查，拒绝旧结果并停放 | 已发生的外部调用如实计费；不继续三次相同调用，用户明确刷新后可续跑 |
| 固定主体派生反馈，原提交或新修订已存在 | 当前身份/来源仍有效时可完成 | 只追加原subject的不可变FeedbackV2；不重开周期、不改旧提交，即使新周期paused也允许纯反馈 |
| 业务结果已提交但ACK丢失 | 先回放原幂等结果，不调用handler | 已生效任务不能refresh；当前scope和实际claim仍核对 |

模块还可声明 JobRequest.head_dependencies 和 state_dependencies（config_version/resources/applied_milestones/status/cycle_id）。这些是额外的新鲜度条件；空集合也不能关闭上述普通job生命周期条件。执行前、模型返回后和事务内均核对相关条件、当前credential/action/object scope、实际WorkerClaim/租约和输出expected_head。

context_stale、可刷新对象头冲突及生命周期暂不可提交使Worker置needs_context，保留原问题和稳定错误码。RequestResult.status直接返回needs_context，不再混为unresolved；后者只表示缺失可核对的effect等不完整结果。固定新对象ID已占用返回job_result_identity_conflict并立即failed，不能无限refresh；模块须使用唯一结果ID。写旧周期返回job_output_cycle_closed并立即failed。其他确定性ProtocolError（4xx及明确模块/对象契约错误）也只尝试一次；仅ProtocolError.code作为稳定协议码，未知异常归job_execution_failed并沿有限瞬时重试预算。v1仍保留旧异常类名处理。

调用者明确POST `/sessions/{session_id}/jobs/{job_id}/refresh`，发送显式v2 Command（operation=jobs.refresh，payload含同路径job_id和当前业务/工作区版本），经Gateway/公共事务重取快照及声明的head。原逻辑command/request_id、精确sources/subject/evaluation不变；旧job_context保留，refresh_count递增，旧claim失效。JobRefreshRecord保存每次停放原因、attempt、queued/started/parked时间和refreshed_at，并由RequestJobResult.refresh_history提供可恢复查询。原credential失效/越权、普通job当前会话非active或周期非open、永久失败或已有effect时均拒绝刷新，不重排注定失败的任务。学员可刷新所属agent job，但原agent凭据必须有效；agent自行刷新还需allowed_actions含jobs.refresh及原动作。

context_hash保留原入队模块输入身份，不代表刷新后prompt；模块根据新as_of/refresh_count重建并记录真实prompt/hash与usage。尚未提交时外部模型调用仍可能重复，缺失usage写unknown，不声称外部计费恰好一次。旧r3已queued任务的缺省字段可消费；r3已failed且只保留通用ProtocolError的任务不能可靠推断失败原因，本版本不自动复活，保留历史并由业务模块为用户显式新建关联请求。

RoleContext受众只允许system与自身真实role_id，普通learner不可读；保留字role_id也不授予权限。visible_to必须包含自身role_id才能供role_reader读取；仅system受众的内部记录只供research审计。当前RoleContext是每次capture的新ID快照：caller只能创建私有v1，不能更新旧ID，也不能把私有context当作公开产物依赖。合法方向是私有context引用安全回复；向学员展示走PublicDisclosureRecord/公开回复。W04可信派生产物与更新/事件读取通道另按S01—S06集成，不借research权限绕过。

同一Mutation允许按顺序写同一对象v1…vN，每个expected_head对已有或前序planned版本递进；版本、依赖、头和事务结果全部原子提交。中间版本不连续或后续失败时全量回滚；重复请求回放同一结果。导入可利用此能力保留真实历史，不可补造缺失版本。research_context新凭据只读，且公共授权层也拒绝旧research凭据的act/submit/delegate写入；内部研究读取仍无自动到期/撤销通道，调用方需控制句柄生命周期。SnapshotExport含私有原句，不得把它直接送进面向学员的生成或公开输出。

execute(expected_storage_revision=...)保留为已有内部调用的显式同步CAS兼容参数；job路径不再传它。当前没有内置模块依赖它，不把全session storage_revision重新引入异步有效性判断。

## 研究隔离恢复

`SnapshotService(store).export(internal_research_auth, source_digest, storage_revision=..., fork_seq=...)`固定状态、全部对象版本/依赖、事件和动作边界；同一固定版本导出hash可重复。只接受完整事务末点。无存储版本的v1历史前缀没有此服务支持，不按时间戳猜测。

`restore(snapshot, session_id=..., token=...)`在新命名空间恢复，重映射session/对象/事件/事务ID；不复制token、授权或可执行任务队列。复制job context等旁路对象作为历史数据。它不会调用模型、重放动作、触发外部审批或改写父记录；返回完整id_map和原前缀digest。恢复后可在副本执行候选动作。W09可直接使用，完整历史分支/比较由W10封装。权限、source文件及最终数据分区仍由相应研究入口校验；这不是学员工具。

## 数据与文件bundle

四类输入严格分开：relation→RelationInput，criterion→CriterionInput，trajectory→TrajectoryInput/trajectory_diagnosis，acquisition→DecisionPointInput/acquisition。只有前两类使用EvidencePackageV2原子Judge。DatasetRecord的模型调用入口是`data.model_input(record)`，标签通过独立labels/文件引用；W07负责按此边界写出物理分离数据并做来源/泄漏审计。

AnnotationV2的G2v需要两个真实成功调用、不同prompt以及可行时不同证据顺序；比较标签、适用性及引用集合，引用顺序不算语义差异。分歧需第三次实际裁决和引用，失败/空结果不能算一致。旧G1由LegacyAnnotation保留其原语义，不能直接成为新双真人G1。

SplitManifest约束同结构/连通分量/祖先同区，seen-test只能作train/regression。TestCampaign固定候选、版本、预算与首次开放；`require_confirmatory`拒绝未预冻结候选，`require_training_split`拒绝test/regression进入训练、技能及优化。实际隔离和数据生产由W07/W11及031执行。

FileRef只允许受控根下的相对路径和精确hash；`files.load_bundle(root, ref, ModelClass)`校验全部文件、拒绝缺失/漂移/越界符号链接，读取不执行入口代码。ModelBundle和ModelPrediction保留任务、有序labels及概率对应关系；RuntimeBundle和EvaluationBundle各自冻结，W08/W09不必等待W12完整registry服务。

## CLI与检查

模块可调用`registry.register_cli(name, configure_parser)`；公共集成人在CLI装配处调用`install_cli(subparsers)`。本包未改全局`cli.py`，因此计划中的export/agent-suite/branch命令尚不能当作已安装。冻结导出入口已经可用：

```sh
.venv/bin/python -m career_lab.contracts.v2.export --output docs/contracts/expansion-v3
.venv/bin/python -m pytest tests/contracts/expansion_v3 -q
```

已被下游采用的manifest、草稿及旧fixture不能覆盖。重新冻结先发布新的候选身份，由031协调消费者迁移与复验。


## 消费者交付后的契约收口（r2）

具体请求逐项处置见consumer-request-resolution.json。这些变更不表示已接入W02/W03/W07/W09真实模块；各作者须按新revision迁移，031再安排组合验收。

- AssistantConfig的freshness_guard固定为none/warn/fallback；min_score=0.35只是待校准初值，min_score_calibration为空不代表标准已验证。TestResultV2必须带实际execution和config_ref，来源/索引/使用版本、chunk身份、执行者、时间及每次模型尝试如实记录并按权限投影。
- BusinessRequest必须有BusinessBasis。proposed固定拟议配置但不赋予生效含义、不触发apply或政策；applied绑定确切配置引用。内容hash覆盖配置行为参数，ID/所在session/版本标识另行固定；请求后续状态版本不能改basis。实际审批策略仍由W02提供必要性和档位判断。
- ScenarioStateV2保存source/index版本、激活记录及current_config引用。它在TransactionView.private_scenario_state中仅供服务器模块纯计算；不得序列化给学员。W02把PlannedTransition转换为公共Mutation，公共层计算实际seq/workspace/storage版本并原子提交。private_scenario_state的受限材料变化仍受allowed_objects约束。
- 场景文件中的材料/事实不必复制成另一套可变权威对象。安装reference_resolver(kind, callable)，签名(auth, ObjectRef或EvidenceRefV2, VersionPoint, SessionBindings)->ExternalReference。它必须实际验证权限、范围、版本、引用原句/时点和冻结文件hash；拒绝用稳定脱敏错误。公共层验证返回身份，随事务记录不可变来源锚点；snapshot同时携带锚点。冻结场景材料ID保持canonical ID，session命名空间改变，普通可变对象ID重新分配。
- HTTP和异步任务对外结果是PublicTransactionResult；TransactionResult保留内部权威状态。默认事件输出只给公共元数据，具体data由W02安装event_projector按完整AuthContext投影。StepResult通过make_step_result绑定可信原请求、实际effect_request_id、完整边界、执行者和真实step.id；不猜ID、不覆写来源步骤。W06据此提供W09 codec。
- Observation.visible_sources只能是实际获得的ObservedFragment，必须明确learner audience、获取途径/时点及核验等级。catalog可见不等于已读；role_private/model_only和未来观察被拒绝。合法学员记忆可保留，不能把未知memory直接当模型输入。旧信息过期不等于忘记；历史投影须显式include_expired，且始终受actor范围约束。
- G2v的两次成功pass必须有不同invocation_id/context_id/prompt，method=fresh_context。仅可无损置换且至少两条候选的permutable模式要求不同顺序。零/单证据用singleton_or_empty，语义时序用semantic_order，必须保留顺序并写independence_reason；不能添加假证据。第三遍裁决仍需真实记录，失败/空输出不能形成一致。
- TestCase保留intent/refs；test_compare有精确test_refs；review_focus(index/source/uncertain/other)与review_direction分开，不能把“核对索引”变成支持/矛盾判断。ProductAdopt单独表达采用请求，executor/adopter由服务端确定；TaskBatch用于原子多项改动。ImportResult有冲突及来源版本映射，缺历史不能补造。
- 任务委托默认精确对象授权；只有显式create_under_tasks才允许在指定事项下新建并继续维护该委托创建的作品。其他既存作品/引文不因同属事项而自动获权，仍需单独授权。被授权操作生成的评审/测试/提交等回执可由实际执行者恢复，但不反向授予其引用目标的读取权。作业运行前/提交前仍复核到期、吊销、scope和租约。
- SnapshotPortAdapter提供export/read_snapshot、幂等restore、结构化remap_action和parent_digest。restore严格使用给定新session，同目标异request或不同snapshot冲突；同请求重试复取。动作只改结构化身份字段，文字不替换。environment_factory由真实W06/场景组合提供，未安装明确失败；不会用stub假装候选动作已经执行。
- ProviderRequest明确deadline/output_limit/seed/decode和工具hash；SingleAttemptProvider一次最多调用transport一次，未知usage/cost保留空值，超时及丢响应仍留attempt。真实供应商适配必须证明其支持的控制参数；未实调不记模型质量或E4已通过。旧runtime.model_adapter.complete完全保留。


## r3 独立审阅修复与迁移

r2未通过独立验收；R01—R09的修复由新source digest、manifest及回执重新标识。旧r2源码包、日志和原始反例保留。

1. **实际租约传递**：v2 worker handler必须为`ClaimedHandler`，Worker把本次claim的`WorkerClaim(job_id, lease_token, worker_id, attempt)`传入`Gateway.run_job(name, payload, claim=claim)`。入口及提交核对同一claim；禁止从数据库读新token冒充调用者。create_app自动完成包装，手工装配须使用同一包装。旧v1 payload-only handler保持兼容。
2. **提交后的派生反馈**：带真实claim的job以`command.payload.subject`固定submission/review。公共层只允许新建绑定该主体及evaluation的FeedbackV2；不能混入事件、状态/资源修改、其他对象或新job。submitted保持终态，begin_revision仍是显式重开路径。
3. **类型化重映射**：id_map的key使用`storage.v2_remap.identity_key(kind, old_id)`，其字节是`canonical(["object", kind, old_id])`；event/transaction各有独立namespace。不要再用裸object_id查表。外部场景引用保持canonical ID；可变对象改ID，所有ref换session。正文JSON、PlanPayload.sections及LegacyProvenance原样保留，恢复前检查映射后整图。remap_action仅解析已注册的参数模型（默认使用正式请求DTO）；自定义工具通过SnapshotPortAdapter(action_models=...)提供类型，未知模型明确503，不能按任意JSON键名替换。
4. **公开披露记录**：RoleContext继续保存内部DisclosureRecord。Observation.actual_disclosures改用PublicDisclosureRecord，其source是禁止原始quote/span的PublicDisclosureSource。调用`project_disclosures(reply_text, records, session_id=..., as_of_seq=...)`验证实际回复原句后清理内部来源；仍核对source/reply的session和时点。
5. **恢复凭据**：同snapshot/target/request重放时，传入或生成的token必须对应已保存且可用的owner凭据，否则409 restore_token_conflict。首次显式token的调用者须保留并复用它，不能通过省略或替换token获得虚假的成功。
6. **请求结果只读复取**：`GET /sessions/{session_id}/requests/{request_id}`返回RequestResult；公共槽位名requests.read，已内置，无需业务模块。它仅查询原事务及job/effect关联，不运行handler、model或resolver。未知/无法验证的旧记录404，不声称未执行。状态为completed/pending/failed/unresolved，job link保留origin_request_id和effect_request_id。原委托必须仍有效且范围足够；换委托、跨session、过期/吊销会拒绝。人类owner可在自身权限内查同session。该端口覆盖V2Store记录的命令，控制面grant使用自身幂等ID，不伪造不存在的事务收据。
7. **provider审计**：ProviderResult.received在整体校验前保存实际响应、正文和可独立解析的tokens/cost。缺身份记invalid；ModelAttemptUsage.provider/model_revision可空，expected_provider/expected_model_revision另存。收到123+7 tokens和0.42成本即使缺模型名也保留，不把请求模型名冒充实回身份；真实供应商质量依然未验证。
8. **单次G2绑定**：accepted G2必须恰好一个成功pass，final与其实际判断一致（引用集合按已有规范比较）。无记录的人工覆盖不能作为G2；裁决/人工结果须使用有对应来源的标注记录。

W09更新request_result_path及RequestResult解码；W04/W06更新公开披露投影；W09/W10更新kind/namespace映射及typed action model；W05使用固定subject的反馈job；W07/W08/W09/W12处理实回模型身份为空和独立审计收据。不得因本轮基础修复把尚未安装的业务或真实模型QA标为通过。
