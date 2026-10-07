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


## W14 首个公共接线候选：权威引用上下文与读取恢复

候选基于W01 r6与031固定的W02—W05 owned输入，只提供公共接口增量；W02的runtime目前仍锁定r3构造条件，须由033按本候选重新绑定并交付后，才可完成真实ScenarioModule的S06/S07验收。下面的端口验证不冒充该模块整体验收。

新注册方式为 `registry.register_reference_resolver(kind, resolver, contextual=True)`。回调签名是 `(auth, ref, as_of, bindings, *, scenario_state)`；未声明contextual时保留原四参数调用及当前时点语义。API创建的V2Store同步该声明。回调必须是纯验证，不访问数据库、不缓存可变session状态；scenario_state由公共层在同一事务从真实snapshot窗口取得，绝不采信客户端自报激活数据。

普通ObjectRef用当前事务窗口。EvidenceRefV2的observed_at_seq早于当前时，公共层选择该seq对应、且不晚于当前storage_revision的真实已完成snapshot，再提供其ScenarioStateV2；不存在完整窗口则reference_window_unavailable，未来观察则future_evidence。seq增大本身不等于来源已激活。当前credential、object scope与跨session边界始终重新核对，历史窗口不能撤销当前授权限制。底层不将私有ScenarioState加入公共响应。

W02消费者迁移可以将其现有 `reference` 作为contextual回调，或让 `reference_resolver` 显式接收并传递scenario_state，再以contextual=True注册；同时更新runtime的真实foundation绑定。禁止临时替换旧manifest骗过构造校验。

合法已执行动作的command、对象content与result中外部引用，经同一resolver验证后在同一事务保存不可变ExternalReference锚点。没有ObjectWrite的材料读取也能按原request_id恢复原响应；验证失败时锚点、事件、事务与结果一起回滚。恢复查询只读取已记录信息并复核当前授权，不再次调用resolver或模型。相同对象版本的源文件/hash漂移仍拒绝。经验证的LegacyProvenance.raw为惰性原稿，不参与活引用或未来时点扫描；真实引用字段仍受校验。

`V2Store.resolve_reference(auth, ref, storage_revision=...)` 是独立只读验证入口，返回ExternalReference；省略revision取当前上限，给出revision必须对应真实snapshot。不要在Mutation回调内嵌套调用它；事务中的验证由公共execute负责。W03纯domain所需的操作内view权限predicate及导入回执另行提供，不能自行调用私有_records。当前restore未携完整历史snapshot序列；已复制锚点保持源身份，但缺失的历史窗口不会被虚构，需历史窗口的调用会明确不可用。


## 原键重放的统一权限边界

execute命中旧事务、worker replay及GET requests/jobs恢复，共用当前凭据、原动作权限、对象scope与精确记录可见性校验。不会仅因fingerprint相等返回旧正文，不会为重放再调用handler、resolver或模型，也不推进事件/版本。显式结果或可见事件里的私有引用不享受内部记账豁免。

旧scope_refs可能没有记录result-only引用，因此恢复合并已保存结果/对象及可见事件里的引用再次检查。缺外部锚点的历史投影，仅在元数据完整、原actor一致、外部类型仍已注册且当前scope允许时回放原内容；这不等于重新验证来源或补造锚点。元数据缺失、未知引用类型、跨session、缩权/撤销/过期或不可见引用均关闭返回。原权限合法的重试仍返回同一事务；同key不同command仍为request_id_reused。


恢复与重放事件按已持久化的operation选择当前安装注册中的projector：静态operation/action_name或明确Literal动作字段可唯一匹配；不能由读取请求自报projector。派生effect使用自己的持久化动作。未知动态字符串匹配不授予投影，继续默认脱敏；歧义匹配返回event_projection_ambiguous，不借另一模块函数泄露原始事件。可见性先过滤，projector仍校验PublicEvent身份。GET恢复、POST同键重试及worker ACK恢复不重跑业务handler/resolver，并保持合法原投影字段。


## W07/W08 小数据契约切片

DatasetRecordV2.bucket明确允许fixture。带fixture:not-business-run变换声明的记录必须仍是fixture；metadata侧记中的fixture快照也不能被env_run等记录冒领。fixture用于管线与契约验证，不计为真实业务运行、真人会话或模型效果证据。

`model_input(record)`仍只返回四类业务输入，外层language、bucket、lineage、provenance、label_ref及标签方法均不进入该载荷。`metadata_projection(record, annotation=None, capture_point=..., source_snapshots=...)`输出独立DatasetMetadataV2侧记，保留完整lineage、来源文件/代码身份、语言、来源桶、各snapshot_digest及capture_point；不能把此侧记拼进模型prompt。未提供annotation时状态为unloaded，accepted_label_tier为空。

record.label_tier表示该标签流声明的方法，单独字段不能证明标签被接受。`validate_record_annotation`重验AnnotationV2结构并核对record_id/input_hash/tier/task；require_accepted=True时pending/disputed/failed拒绝进入已接受发布。metadata侧记分别保存requested_label_tier、annotation_status和accepted_label_tier。pending的G1计划不等于新G1；accepted G1仍须已有两名独立human成功记录和裁决引用。实际文件hash、调用/人工身份真实性与源记录事实由W07发布验证器核验，schema不能代替现场证据。

relation/criterion的as_of是被评价主张/行为的历史参照点，capture_point是后来读取快照的时点，不改写as_of。已接受配对必须有rule_context.evidence_time_context：policy=historical-evidence-time-v1，status=known，reference_seq等于as_of.business_seq，validity_known_ids恰好覆盖所有候选。valid_until_seq=None仅在源适配明确声明known时代表已知开放区间；未声明或undetermined仍pending，不能推成当前有效。引用与可接受证据集合须满足observed_at≤as_of、valid_from≤as_of<valid_until（known开放上界除外）；evidence_evaluable要求存在合法联合目标。过期旧政策可证明旧时点事实，未来政策不能倒扣历史行为。每个已记录capture_point不得早于该参照点。

这是公共契约与验证函数；W07/W08须按固定候选迁移，执行真正fixture release→W08消费的跨包回归。当前没有下载模型、训练或把脚本标注计为正式实验。新增manifest会改变严格foundation绑定：W07/W08需迁移，W02即使未用这些模型也须按其runtime精确绑定规则重新确认；不能拿前一manifest冒充当前实现。


### 已接受标签的联合证据目标

公共配对验证与W08训练入口采用同一门槛：当evidence_evaluable=True时，必须提供acceptable_evidence_sets；除INSUFFICIENT和NOT_APPLICABLE外，其中每个集合都必须非空。SUPPORTED、CONTRADICTED、MET、PARTIAL和NOT_MET不能用空集合充当可接受的证据输出，也不能把一个空集合混进其他有效集合来绕过。所有引用仍须属于历史时点可用候选。INSUFFICIENT/NOT_APPLICABLE可使用显式空目标((),)；evidence_evaluable=False时允许没有证据目标，不为满足格式编造引用。pending仍不等于accepted。

此规则修正c3 helper对空集合的漏检；它不证明语义标签正确，也不替代真实标注来源核验。只影响公共数据接受/metadata投影门槛，不改变W02业务schema。c2业务绑定及独立HTTP证据继续保留，累计业务联调前由031统一固定新foundation输入，不因每个data-only候选要求立即重打场景包。


G2v仅比较两个独立pass是否语义分歧时使用semantic_decision_key：task_type、label、applicability、evidence_evaluable与规范化可接受证据集合。措辞/missing_reason或合法代表引用不同不额外触发第三遍；语义相同则确定性保留首遍。G2单遍final、G2v共识final与首遍、分歧final与真实裁决遍仍用完整decision_key绑定，不能改写最终措辞/代表引用冒充实际调用结果。真实语义分歧仍须有成功第三遍及裁决引用。原始输出、解析记录、真实调用身份、独立上下文、证据合法性和原始数据均保留。


W04旧role_reply含prompt/context/source映射字段时，共同read、view、can_reference、GET request恢复及execute/replay均拒绝向learner及其Agent返回该对象；不改写或清理历史行，受信任匹配角色和research审计仍可读取原件。新写role_reply必须没有内部字段；spoken_evidence仅含schema_version/label/quote/verification的公开已说引文保留，含source等内部字段则拒绝。已有snapshot export仅开放research能力，公开凭据不能使用。旧r1回归夹具需直接载入已保存历史行，不能通过新write边界重新制造旧记录。本修复不等于正式角色快照、私有审计carrier、worker工厂或浏览器三轮协作已完成。


W03公共恢复接线：在同一ExtensionRegistry先安装固定W03.install_workspace_operations，再安装api.workspace_integration.install_workspace_recovery。preview只在Gateway只读query中计算，返回ImportResult且不写请求/事件/事务/回执；apply走共同execute，在同一事务写任务、各作品历史版本及不可变WorkspaceImportReceipt。task原始来源保存在receipt.task_sources，不另建legacy_task存储。LegacyProvenance.raw不参与引用/时间遍历。GET workspace-imports及指定import_id可恢复回执；GET work-products/{id}/shares返回带sharing_complete与分页指针的WorkspaceSharePage。外层沿既有V2Response信封。

TransactionView.reference_allowed是仅在当前事务存活的验证回调；离开query/execute后即拒绝，不用于保存或worker实时补读。普通store.view返回的快照不携带该权限。只有同一正式事务view的removal_cascade=current_product_only表示共同存储会对已授权移除的当前产品撤销其所有活跃分享，包括调用者不可见的分享；不扩大调用者scope，不返回隐藏分享ID/正文，不给其后续重放读取权。结果removals含all_active_shares_revoked及仅本来可见的visible_revocations、sharing_complete；恢复产品不重新分享，异步任务重新检查有效分享和产品移除状态。W03 own handler仍需由原owner消费此端口，不能把shares_complete伪装成True。

WorkspaceProductPage的visibility严格针对该作品版本；当前v2为private时历史v1分享仍可活跃。sharing_complete表示权限视图的完整程度，next_cursor仍须用于取完分页。不可见且完整性未知时visibility为null；客户端不得默认为private或清空其他页/历史版本分享。当前内核及受控API验证不代表原生DOM已消费这些新槽位。

非公共私有对象不能通过普通caller mutation写入，必须使用已批准的专用私有通道；当前仅已有结构对象白名单，W04正式私有carrier尚待接通。公共operation声明的固定action或Literal action集合在注册时检查重名，拒绝模糊投影路由。


W05正式反馈持久字段：FeedbackV2新增verified_facts、historical_responsibilities、rule_items，均为optional typed section，默认None=旧反馈未记录。不得将其补成空数组来暗示没有调查/违约。VerifiedFactsSnapshot按确切产品版本分组，分开作品as_of、请求requested_at、来源captured_at/source_snapshot_hash、作者/执行者/采用者与actor；引用不可核验时只保存submitted_reference_hash+安全状态，不保存未授权标题、原文或对象引用。完整日志计数必须有从零开始覆盖作品时点的窗口，unknown计数只能为null；受限对象授权不能发布complete全局统计。source_snapshot_hash只证明固定输入身份，不单独证明真实世界来源或当前权限。

HistoricalResponsibilitiesSnapshot把完整性与记录列表分开。每项保留实际行动/承诺/完成声明类型、发生及评价时点、确切scope、核验来源，actor/executor缺失仍None。承诺不证明实际执行；配置不能当actual_*来源。此层与rule_items及items中的模型建议分开持久化，不自动改业务结论或能力分数。现W05 r4只返回sidecar，034须按固定新契约输出正式字段；可信source adapter必须先拒绝无权主体/会话，单项支持来源不可核验仅该项pending，其他项保留。当前切片尚未安装生产可信reader/默认评审worker，不能把持久化夹具当线上事实。

api.feedback_integration.install_feedback_recovery注册共同Gateway槽位：GET /feedback-records/{feedback_id}读取原始反馈正文及sections recorded/not_recorded状态；POST /feedback/{feedback_id}/responses以明确feedback_version追加异议或补证；GET同路径分页，GET /feedback-responses/{response_id}恢复单条。FeedbackResponseRecord固定关联原feedback和确切证据，保存原executor；旧反馈不可新增版本覆盖，补证必须带当前可引用的确切证据。请求幂等/权限/撤销/引用核验均走同一个V2Store。

反馈回应允许在active/paused/submitted阶段追加，只能写单个feedback_response，不能夹带事件、世界状态、队列或其他对象。它不重开周期，也不推进business_seq；再次改稿仍需显式begin_revision。后续ReviewInput可给显式decision（含None）及followup_of反馈回应引用，ReviewRequest原样保存；关联不自动标记旧异议已解决，不修改旧反馈hash。当前只提供正式公共记录入口，原生v4展示/操作和实际无模型事实生成接线仍需后续组合验证。


角色私有快照读取：普通TransactionView没有job_context权限；真实job_view携带已保存JobContextSnapshot，role_snapshot_records重新检查原凭据、生命周期、不可变记录、角色与原提问、固定state/binding。只在原job as_of读取角色自己的私有记录和已实际接收事件，不把原调用者换成owner/role凭据。FixedRoleSnapshotPort重建角色记忆和收到的作品收据；分享修订、接收者、确切产品版本、收到时点及正文必须匹配真实历史。当前scope裁剪由W04 ContextSnapshot按learner_refs执行，历史内存存在不等于本次模型可读。

事件只从真实recipient/type/refs及与实际material_activation一致的before/after版本变化构造来源引用；不把notice正文当权威材料。旧回复缺可验证私有收据时返回role_history_requires_migration，保留原记录而不伪装为全新历史。RoleContext新增generation_audit，包含原executor/credential/scope、实际prompt/hash、job/attempt、refresh_count、调用usage与来源收据；字段定义不代表可信写入端口已完成。普通read/view/恢复继续保护全部私密字段。当前没有PrivateGenerationPort持久sink、租约绑定失败审计、私有派生写入以及event引用落库通道，因此模型入口继续明确关闭，不能据schema/读取测试声称三轮生产角色协作完成。

恢复补齐FeedbackResponseCreate.feedback_id，以及ResourcePage中的feedback_id/response_id/import_id声明式映射；任意文本与旧来源raw不重写。


031-C8-01反馈共同读取边界：显式授权feedback ID不替代主体权限；feedback.subject、review/submission实际作品，以及事实/历史层subject均须在当前调用者scope内，否则read拒绝、view省略，job来源/请求恢复/重放同样拒绝。主体有权但部分支持源无权时，store只返回read_projection=partial的临时投影：有权且有引用依据的项保留；无权项转pending/unknown，移除源引用/原句/标题/ID及不能独立归因的派生自由文本。局部历史时点可变为None，不伪造时间；未知引用hash和完整snapshot hash不回传。有限对象scope不沿用全局完整统计。

投影同样过滤StoredObject.dependencies；针对投影的EvidenceRef引用/复制被拒绝，裸ObjectRef仍可用于授权的反馈关联。FeedbackResponse随父反馈主体授权和部分依据状况做同样的安全读取。read_projection不得写回持久对象；原FeedbackV2/回应内容、来源和hash不改。API仅消费共同投影，不能自己绕过store恢复旧原文。GET、execute/replay会识别保存的反馈对象/元数据/原提交边界，即使旧缓存缺对象列表，也不能返回未绑定的自由文本；部分权限下返回安全feedbacks/feedback_responses集合并隐藏无独立权限证明的事件正文。未能建立身份关联的旧feedback缓存明确拒绝。

外部支持源回读使用该报告同actor写入时已核验的不可变ExternalReference锚点、当前对象scope及仍安装的引用kind；缺少原始actor/锚点证明按待核验处理。不在GET/重放中重跑resolver、handler或模型。真实生产源绑定及不可变来源由现有源提供器负责，类型或hash本身不代表真实业务结论。内部research快照仍保留原始审计；公开token不能导出该内部快照，未来公开导出须消费共同投影。


W03作品重放：仅work_products.create/versions.create/adopt返回的、与确切已保存授权作品匹配的product.cycle字段可作为结构关联保留；visibility允许读取时派生。该cycle不能因此展开读取。相同cycle若同时出现在显式来源、event refs、直接对象列表或未匹配的作品体中，仍须独立scope；其余嵌套引用照常核验，不更改原令牌、share/cycle权限或保存的返回关联。W03新owned实现另以固定checkpoint overlay验证，不混入当前W14继承树。

有限对象scope的反馈自由摘要、无逐项引用依据的解释与全局统计属于当前无法独立核验的内容，使用安全待核验投影；有权且有明确来源引用的其他项仍保留。read_projection是读取语义，不能当作原始反馈写入、评分或伪造新来源hash。


正式私有角色写入：api.private_roles.PrivateRoleGenerationPort配合StoreJobHandler使用实际Gateway.store及WorkerClaim；API和独立worker均由同一ExtensionRegistry注册对象模型/引用提供器。begin_role_execution固定原AuthContext、原问题、snapshot、prompt/history hash、精确私有refs和经过角色reader核验的外部锚点。原调用者始终传给RoleService，内部role reader只核私有来源，不能替换caller token或扩大其scope。

公开role_turn由受控turns.create派生，role_reply由实际fenced job派生，保留原executor。提交计划需不可序列化的本store许可与完整计划hash；改受众、删审计、改scope/上下文/周期/身份或加未批准来源均拒绝。公开回复只可引用原turn与确切原/生成cycle；私有audit可以引用公开reply，反向禁止。reply和completed RoleContext同一共同事务提交/回滚，私有依赖不塞入公开重放所需scope，也不给caller私有对象访问权。

record_role_attempt用同一v2对象/事务/快照表及storage_revision保存实际接口给出的attempt/usage与prompt；由真实lease和原捕获许可授权，system作者记录原caller在audit.scope中。它不改变business_seq/workspace_revision。调用后暂停或撤销不会抹去实际尝试，公开结果仍按原caller当前授权/生命周期拒绝；缺失/过期/被替换lease不能写结果或审计，未保存usage不能解释为零调用/零费用。成功回复提交失败保留尝试，重试可再次实际调用模型，不能宣称外部调用恰好一次。

RoleReply的公开写/历史读按固定公共DTO字段白名单判定，宽松ObjectModel(extra=allow)不能放行generation_audit、scope、used_sources、job_attempt及未知字段；合法公开spoken_evidence仍允许，私有原件留给内部角色/research。generation_audit写入须正式许可，不能靠改visible_to把私有记录公开。

事件引用kind=event由共同事件表管理：验证真实id/version/session、受众与窗口，带原文/跨度的事件证据须另经安全投影；研究快照在原event namespace重映射，RoleGenerationAudit中指向RoleTurn的attempt.request_id随该明确引用映射，实际provider attempt_id、usage和原prompt不改。

install_private_role_runtime默认enable_generation=False。当前成功/受众/回滚/三轮/刷新测试使用明确受控模型与catalog；旧固定W04仍有待037修复的私有来源ID回显，未装入新修正版前不启用业务生成。实际材料/有效时点绑定、私有stance新计划、原生display/Observation/tools及产品QA仍需累计接线，不能用本切片替代。
