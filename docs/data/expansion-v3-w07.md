# W07 数据与标注模块

本轮完成2026-10-07 c5语义共识迁移，仍是 **implementation_only / partial**。真实源码、模块测试和本地CLI已实现；输入为031固定的032 c5公共候选，尚未通过正式W01/02/05联调。没有生产新场景数据、调用真实标注模型、开启新封存test或开展真人实验。测试中的provider、批次和release均明确为fixture，不计真实运行样本。

输入基准：`80cf1f6189cd25610d609f44283ff9668582d759`，合同 `expansion-v3-deb8023ca664946f45c52692c65e3524703d77194c5100e0ee42939ae26cff4b`（候选commit `d82d7fe690ed0491744cb716df377a77bc2ed4b4`）。1078份公共源码来自上游不可变归档，完整继承且逐文件核hash，**不属于W07独占产出**。原v1生成器、数据、freeze、接口及共享依赖不修改。

## 已实现的处理过程

1. `export.py`在一个固定business/workspace/storage版本上转换relation、criterion、trajectory、acquisition。只使用W01公共模型；校验来源对象、会话、权限、观察/生效时点、正文和原句。trajectory/acquisition每段observations必须逐段匹配该步时点可见的已引用原文或精确片段；source-map保存逐段绑定。无出处的自由概括不能被当作实际观察送入模型；缺来源整条记录进入quarantine，不靠全文黑名单保证隔离。输出中性引用ID，评测侧另存原始引用映射；保留c0、过期材料和未知/失败状态。重复导出不写源会话。
2. `quality.py`按structure、component、fact root、session/run/branch、decision/candidate、派生和祖先连通关系检查分区。decision_id与candidate_id是跨副本保留的因果身份；生产者若使用局部编号，应先提供包含原决策作用域的全局ID，不能按新fork session重命名来拆开谱系。拒绝未知祖先、循环、精确/近重复跨区；输出实际条数、语言、来源、等级、状态、独立结构数和排除原因。词面近重复不能证明语义或因果独立，后续仍需W11审查。
3. `g0.py`只验证明确数值语法，如`capacity <= 30`与当前JSON数值证据。缺数值、冲突、过期或不支持的语义分别处理；自由判断、理解程度、最优信息动作不因此成为G0。
4. `labeling.py`先核对并冻结来源审查与原始文件hash；未approved、已撤销、缺许可/部门授权/真人同意的记录在可发送批次生成前隔离，fixture也不豁免。每次issue/run重核冻结策略和prompt manifest。使用独立SQLite outbox保存每次调用的原始输出、模型/provider、prompt、证据顺序、hash、时间、成本可知性和失败。两遍各自从model_input开始；分歧需真实第三遍，成功记录不会在resume时重复调用。空输出、格式错、无效引用和超时保留pending或disputed，不升级G1。真实provider由调用方显式注入，模块没有默认密钥或自动联网行为。
5. `release.py`先审计再原子发布。inputs、labels、source-map、split manifest、来源审查和质量报告分开保存并逐文件hash。发布和回读同时解析每个pass的完整原始request/receipt，核对record/input/payload/prompt/执行者/model身份并重新验证decision引用、适用性，从有效原文重建一致或第三遍裁决；空凭据、原文/声明不一致及无效引用即使外层hash重算也不能放行。输出路径不可覆盖；缺许可/部门授权/个人同意的记录被排除，其标注原文也不打包。正式发布拒绝fixture；fixture发布明确标识且training_ready=false。缺训练类覆盖或标签待处理同样不能声称训练就绪。

## 导出端口

集成方实现`SnapshotPort.read_snapshot(session_id, VersionPoint)`，在一个只读一致事务中返回`FrozenSnapshot`。`export_from_port(port, session_id, point, build_units)`只读一次；`build_units`提供该快照对应的`ExportUnit`列表。内部dataclass是适配端口，序列化协议仍为W01的DatasetRecordV2、AnnotationV2、SplitManifest等。

快照需提供可信session/actor、三个版本号、确切SourceObject文本与读取权限、真实源码digest及来源类别。`Provenance.actual_sources`必须指向可核验的本地固定文件。live端口不得从LLM文字生成业务事实。来源声明本身不能证明业务真实运行，最终需上游API/worker记录及独立验收。

返回值`ExportResult`包含四切面记录、待标注AnnotationV2、评测侧source_maps和逐项quarantined原因。原始来源不得放进标注请求。新数据保留schema定义的label_tier，但pending不代表该等级标签已完成；统计分别报告status与已接受标签。

## 本地模块命令

从本包独立checkout使用自身虚拟环境：

```sh
.venv/bin/python -m career_lab.datasets.v3 --help
.venv/bin/python -m career_lab.datasets.v3 export --snapshot <fixture-snapshot.json> --units <units.json> --output <new-export-dir>
.venv/bin/python -m career_lab.datasets.v3 label prepare --export <export-dir> --source-root <fixed-source-root> --policies <source-reviews.json> --output <new-batch-dir> --annotation-version <version> --executor-id <actual-agent-id>
.venv/bin/python -m career_lab.datasets.v3 label issue --batch <batch-dir> --record-id <id> --phase 1
.venv/bin/python -m career_lab.datasets.v3 label receive --batch <batch-dir> --receipt <actual-receipt.json>
.venv/bin/python -m career_lab.datasets.v3 label status --batch <batch-dir>
.venv/bin/python -m career_lab.datasets.v3 publish --export <export-dir> --batch <batch-dir> --source-root <fixed-source-root> --policies <source-reviews.json> --output <new-release-dir>
.venv/bin/python -m career_lab.datasets.v3 validate-data --release <release-dir>
```

离线JSON不能证明是live快照，因此`export`文件入口仅接受`origin=fixture`；真实来源通过上述可信端口接入。夹具发布必须显式`--fixture`，未标注开发夹具另加`--allow-pending`；二者不能产生正式实验结论。出错返回JSON错误与非零退出码。

总`career-lab`入口尚未挂载。032可把已有argparse的subparsers传给`register_commands(commands)`，解析后仅对带`w07_handler`的参数调用该函数并输出JSON。现有命令无需重建。API、storage和主CLI的接线由032处理。

## 标注调用与恢复

`AnnotationBatch.create`必须显式提供source_root和policies，建立不可覆盖的批次；冻结source-policy.json，批次只存获准记录，quarantined只留记录ID和原因。Python调用`batch.run(executor)`，executor接收hash绑定的请求并返回`LabelResult(raw_output, model_revision, provider, usage, invocation_id, context_id, independence_method)`。提供的OpenAICompatibleExecutor支持注入httpx client/明确endpoint/model/key；真实调用前由集成人安排资源和授权。本轮仅以明确的test double和MockTransport测试此适配器。

离线`issue`输出与API相同的model_input、原input_hash、重排后payload_hash、request_hash和真实请求ID。`receive`要求原样回传这些签收字段、raw_output、真实model_revision/provider、实际invocation_id/context_id/fresh_context及已知usage，并回传batch_id/source_policy_hash/output_schema_hash。这里的hash签收不等于密码学身份签名，也不自动证明真人参与。成功回执同内容重放；改内容冲突。原结果文件及SQLite记录互相核验，漂移拒绝。

网络请求前先记录dispatched。已经收到但缺model_revision/provider的结果保留raw/usage并标failed，可以正常retry_failed；不会冒充未知发送。进程在发送后中断时，恢复会报告`dispatch_outcome_unknown`，不会静默重新发出可能收费的请求。已知失败可通过`retry_failed=True`或离线`--retry-failed`显式补跑；未知结果需核对provider回执再由程序调用者明确选择`retry_unknown=True`。本地幂等不能保证远端provider只执行一次。每次尝试保留，不隐藏失败成本；未知成本不记为零。

## 尚需上游接通

- W01正式冻结、W02真实运行及隔离候选副本、W03/W05作品/提交/修订/反馈一致读取；现在的抽象端口和fixture不满足W07-AC11。
- 至少一次真实API或真实离线Agent双遍/裁决、签收与恢复；本轮test double不能满足真人或模型实调验收。
- 真实模型双遍/裁决仍未执行。c4下已实现invocation_id、context_id和fresh_context回执；零/单证据保留顺序，轨迹保留时序，记录不可置换的原因，普通证据第二遍置换。离线执行者必须回传实际身份，单靠请求中的建议context_id不构成真实执行证明。
- W11最终结构及split manifest、统一test campaign。当前label和publication默认拒绝test；不能将此开发实现称为封存测试发布完成。由隔离上游提供已授权结构/评测端后再接入。
- public_aux需URL、访问时间、许可、原文hash和approved审查；business_synth需authorization_ref；human_session需consent_ref。未获得的新部门/真人来源不填数字。

## 验证与交付边界

测试覆盖四切面转换、旧数据契约、c0/时点/权限、原句、连通泄漏、双遍/裁决、离线恢复、崩溃窗口、并发dispatch、标签隔离、原子发布和真实模块CLI进程。原始结果和失败保存在本包`runs/local/expansion-v3/W07/`，准确命令、退出码和源码hash见完成回执。

mandatory AC仍按真实上游和实调条件逐项核验。局部测试通过仅支持本阶段partial；后续由031更新输入基准后补真实联调，再交独立review和组合验收。没有commit、push、merge、部署或新增费用。


## r1修复与历史批次

031的五项独立反例分别进入`test_w07_review_r1.py`，包含跨family反例、重新计算外层hash的攻击、来源在发送前隔离以及已收到失败回执的恢复。所有回归仍使用明确fixture/test double，不计真实场景或模型验收。

r1阶段曾将内部证据协议升级为v2；本轮继续升级为v3。v1/v2目录、回执、patch和归档保持原字节；新代码拒绝将缺来源策略或完整原始回执的v1批次/release直接当作已验证证据。需要在新目录按v2规则重新核验和取得回执，不覆盖历史结果，也不通过补造旧回执升级证据。

冻结的来源许可只证明批次生成时保存的审查依据；上线后的即时撤销/会话授权仍需W01真实读取及dispatch权限端接入，当前未声称真实服务权限联调完成。


## 2026-10-07 新审阅修复

两遍通过完整合法性校验后，以task_type、label、applicability、evidence_evaluable及规范化acceptable集合比较共识。missing_reason措辞和合法代表引用不参与比较；一致时精确保留首遍decision，只做两遍。原始返回与parsed decision仍逐字段一致，最终attestation仍完整重建比较。pending/disputed统一保持未接受模型状态，不允许导出者声明G0/G1/G2v；质量报告的label_tiers只统计已接受annotation，pending数量另列，metadata中的accepted_label_tier为null。

一次snapshot导出仍保留单一来源身份；新aggregate_exports与publish_exports支持多个session/结构/分区，各自保留capture point、snapshot digest、source代码身份、record成员和完整lineage。每个来源有自己的文件根和审查策略，同名source.json也按record核验，不能只拿第一个来源。手工拼入没有对应来源清单的记录会被拒绝。CLI使用`publish --sources <清单.json>`，清单为包含export、source_root、policies和可选batch的数组；各路径相对该清单目录解析。

元数据使用record-metadata.json索引加metadata/<record_id>.json单条文件，保存语言、来源桶、完整谱系、snapshot身份和annotation状态，不带model_input、gold正文或模型解释。W08按分区读取对应metadata，避免读取混合records.json。release与标注批次均升级到v4，旧产物按原冻结运行时追溯，不原地重写。

历史时点采用`historical-evidence-time-v1`：EvidencePackage.as_of绑定被评价主张/行为的参照点，snapshot.capture_point只表示采集时点。SourceObject须明确声明validity_known及原始有效区间；ExportUnit须明确evaluation_time_known。未知时点/有效范围保留待核验；不因None或字符串“false”被误当已知。已公开的未来生效材料和过期材料可以保留在输入中，但可接受引用必须在目标参照点适用；原历史判断不会套用后来规则。实际事件记录的事实有效范围与政策的生效范围由来源适配器分别声明，不能猜测。

数值G0、模型标注、发布审计采用同一时间规则；W08按同一版本规则检查gold和输出。正式gold的每组可接受引用都必须合法，未知或当前已失效的集合不能发布为已接受标签。框架保留旧文本，改变的是它能否证明当前被评价的主张。

候选编号按许可模型输入的稳定哈希置换，不依赖producer顺序或任何私有snapshot内容；私有事实变化不会改变公开model_input。词面检查改为语义文本char-5 shingle精确Jaccard位集，仍不证明因果独立或翻译独立，也不允许将同结构改数字后跨分区。

批次冻结实际output schema，不因后续schema说明文字变化重构历史请求。HTTP失败保留状态、脱敏正文、request_id和已知usage；编程/数据错误不得被包装成模型一致。质量CLI返回具体record/原因。

## c4迁移与跨包样例

发布与回读均使用公共`validate_record_annotation`及`metadata_projection`；每条DatasetMetadataV2仅带所属snapshot，历史as_of与capture_point独立。需证据的正标签拒绝任何空acceptable集合，包括非空与空混合；保留明确INSUFFICIENT/NOT_APPLICABLE空目标及不可评边界。发布端严校验继续保留，pending不计accepted/G1。

`fixture_pipeline`用真实export_snapshot、G0数值验证、publish_exports和audit_release生成12条明确fixture：6 train、6 dev，各自独立来源文件，包含历史/当前时点。来源与结构均为合成，没有真人记录、实际场景执行或封存test。W08已直接读取该发布hash完成CPU训练、预测、模型保存和重载；只能证明跨包流程可运行。

```sh
.venv/bin/python -m career_lab.datasets.v3.fixture_pipeline --output <new-output-dir> --workspace .
```

输出publication.json提供发布/分区hash与producer commit，runtime-identity.json保存实际源码身份。新交付绑定各自commit，旧回执与失败原件保持不变。输入候选未获正式验收，真实业务源适配、真实标注批次、W11结构及产品QA仍待后续实现与独立审阅。rule_context/动作参数的深层白名单公共投影尚待接线，现有schema加黑名单不能作为完整泄漏证明。


## c4审阅补充：最终引用、纯标签与来源验证

可评final引用必须与至少一组合法acceptable集合相等；不一致会在标注、发布和审计阶段拒绝，不能作为有效证据监督。INSUFFICIENT/NOT_APPLICABLE的合法空目标保留。不可评记录不伪造引用；数值G0纯标签路径仍重新运行受限数值验证器，只取消定位监督，不把不可评当作标签正确的依据。真实非G0纯标签发布与回读还需独立label_only_authority确认语义来源，未接该端口时拒绝。

发布端将record.bucket与snapshot.origin、源session和lineage配对，读取并核对实际源文件hash；源文件明确声明fixture时，移除transformations标记也不能转成业务来源。非fixture还强制注入source_authority，按独立真实源读取给出record/session/lineage/snapshot/source/files绑定；无此权威端口时明确失败。回读审计重新要求该端口，不能依靠release内自报凭据认证来源。当前只接fixture和明确测试替身，没有完成真实业务来源验证。

每条来源绑定保存为`origins/<record_id>.json`并进入release文件hash清单；它是评测侧内部收据，不是公共schema或密码学签名，不进入model_input。W08按请求分区读取并重核，非fixture再经独立来源验证。当前联合样例的12条G0记录中，train/dev各1条SUPPORTED只有已验证的数值标签、没有定位监督，用于证明证据训练和指标分母正确排除。


## 完整性与监督范围报告

发布前先对全部原记录检查源/分区谱系，再处理不完整项，不能靠隔离掩盖跨区依赖。训练发布隔离不完整输入；显式allow_pending可保存原始诊断发布，readiness.status为diagnostic并按record_id给input_missing/truncated或annotation_not_accepted等原因。审计从实际record/annotation重算ready，不能手工改manifest放行。

完整且已接受、训练类别齐全的合成发布使用readiness.status=ready、scope=fixture；training_ready仍为false，避免冒充真实研究数据。非fixture需相同机械条件及来源权威端口，training_ready才为true；这仍不代表研究、语义可靠性或产品验收。W08只消费对应范围ready发布，在读取入口再检查单条completeness。

quality-report的evidence_supervision列出可评与label-only数量、ID、来源文件/session/代码身份及定位监督隔离原因。模型自报evaluable=false不能证明分类标签正确；G0重新核算，真实非G0纯标签另需独立authority。新v4协议拒绝重解释旧v3批次/attempt/release，旧产物按当时冻结运行时追溯，不改签。


当前c5仅将公共a/b共识改为语义比较，final完整绑定未放宽。W07在线run、离线claim和artifact rebuild共用same_semantics；冗余phase3（包括只保留首遍final的伪造第三遍）在生产端仍拒绝。线上、恢复、离线、发布和重算外层hash后的审计均已回归；原c4的6项阻塞在c5已关闭。该结论只覆盖模块自验，真实provider双遍、业务authority及正式研究/产品验收仍未完成。
