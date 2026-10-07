# W08 模型与实验管线

## 048现行职责与验证边界（2026-10-07）

我方仅推进运行导出、注册接入与独立复核；负责方承担数据生成/标注/划分、全部训练融合、SFT/GRPO、评价项五分类、E2/Jev及预算算力。以下既有训练/标注命令保留供负责方和历史复现使用，不表示本轮已执行或我方继续训练。v2-r1交接ZIP与数据保持原样。

本轮接续原035双语增量，新增检查只用合成记录或已保全产物，均标synthetic。语言、hash/span、译本同split和分别统计只证明机制；真实中英v4运行、外部真实回传和质量仍独立验收。未接真实模型的产品位置显示“等待模型接入”，事实规则显示“规则核实”；注册输出仅advisory，真实调用及外层恢复均零自动重试。

当前为 **implementation_only / partial**，消费031固定的c5公共候选`expansion-v3-deb8023ca664946f45c52692c65e3524703d77194c5100e0ee42939ae26cff4b`（commit `d82d7fe690ed0491744cb716df377a77bc2ed4b4`）。本模块已实现可运行代码及小数据管线验证；W07合法fixture发布已实际消费；正式业务release、W11真实多结构和产品加载仍未接齐，不能据此宣称新E1/E2、模型质量或课程交付完成。

所有候选输出固定为advisory、affects_score=false。G2v只代表模型复核标签；独立人工语义校准与正式scoring采用不由本模块自动开启。

## 中英文评测为必需覆盖（2026-10-07确认）

中文和英文均须可用，英文演示确定；Proposal英文优先评估继续执行。正式E1/E2、模型advisory与产品验收必须有zh、en各自实际证据，缺英文数据或真实运行时明确mandatory blocked，不能以中文结果替代，也不能把“TF-IDF能处理英文字符”或“XLM-R是多语模型”写成英文质量已验证。以下为待执行计划，不改变旧交付的accepted范围或旧指标。

### 必需输入

消费W07固定hash的双语release，以及033/032提供的同事实语言版本、工作语言和翻译来源契约。业务入口采用032统一的`work_language='zh'|'en'`；本包不改c5 schema，也不另加一套业务语言字段。当前DatasetMetadataV2.language可用于现有报表，但与新工作语言/材料locale的映射和旧会话兼容仍待固定输入。未知或混合语言须明确标记并核查，不能自动归为zh；界面语言不能代替源语言。

每个逻辑样本保留两端locale、record_id/input_hash、真实原文hash/span、译文定位、翻译执行/版本与复核状态。原文及译文共用structure/fact_root/component与连接组并保持同split；翻译数量不计作新增独立结构。训练只读train，候选/阈值/语言策略仅从dev选择；不通过将一种语言放train、另一种语言放test制造“未见”假象，不开启未登记的封存test。

relation三类和criterion五类的实际类别覆盖、evidence_evaluable与独立结构分母按zh/en分别检查。记录真实train语言构成和每种eval语言；本计划不预先承诺额外三套训练实验，也不假定中文训练可泛化到英文。现有G0英文数值fixture仅证明管线，不能作为英文自然语言/岗位语义质量数据。

### 成对验证与分语言报告

模型A/B对比须使用同语言、同record/input_hash、同源证据与预算，保留当前精确身份校验。中文/英文语义配对采用固定的翻译/事实连接组，保留不同的两端input_hash，不能伪造相同hash绕过模型配对检查。中文/英文的中性引用须映射回实际来源与翻译锚点后比较。配对一致不等于标签正确，还须有各语言经过核验的标签和适用性依据。

每种语言分别给样本/类别/结构数、macro-F1、逐类P/R/F1与混淆矩阵、误扣/误放及分母、格式/引用/时点失败、弃权、覆盖、evidence-F1和joint及分母、label-only排除、截断与检索损失、耗时/调用成本。缺分母填null并解释；缺必需语言显示未评/blocked，不静默省略该语言，也不以总体平均掩盖英文缺口。现有slices.language仅按现有行统计，不是双语覆盖通过标志。

另列同源zh/en完整配对数与未配对原因、标签/适用性分歧、证据定位分歧、检索与翻译偏差，并按共享component/事实根聚类保留相关性。N-W08-04现有paired_vs_linear仍是label_correct差，不能直接冒称joint或跨语言差；下一实际报告增量需明确指标名称并补joint/分语言配对口径，旧结果不改签。

### 待真实实验与下一片

依次取得固定双语输入/translation provenance和authority，完成分区与成对审计，再做各语言真实标签与模型评测；资源获准后才做批准HF checkpoint的真实smoke、全label-only门槛与checkpoint重载。英文演示还需正常产品路径的英文检索、同事/助手、反馈与修订验证，数值fixture、离线指标或翻译完工均不能代替。当前HF运行时、训练锁、批准模型与真实source/model-advisory接口的阻塞不变；资源核对保持只读，没有新增下载、安装或费用。

旧v9/v7接受及回执保持原样。下一实际模块/公共输入增量再一并处理既有低风险P2，提交新commit/receipt；W07 applicability/label一致性按当前契约边界保留，真实criterion发布前由031/032统一，不自行重标旧数据。

## 模型与真实验证边界

| 候选 | 实现 | 当前证据 |
|---|---|---|
| 常量 | 固定第一类，无学习与证据选择 | 用于诊断指标，不冒充训练模型 |
| LR | train-only字符TF-IDF、多分类LR及单独的二分类证据选择头 | 真实fit、概率顺序和NPZ重载测试 |
| 旧字符MLP | 复用保留的字符特征+tanh MLP，仍引用全部候选 | 明确命名legacy_character_mlp；额外引用被joint惩罚 |
| 微型上下文编码器 | 从零初始化embedding和单头self-attention，残差tanh；关系和证据损失均反传 | NumPy真实梯度更新；整包/逐证据两结构；梯度有限差分、padding mask和重载一致性 |
| 预训练编码器 | 显式固定revision、仅本地权重的Hugging Face适配，带监督fit/predict/checkpoint重载接口 | 当前torch/transformers及XLM-R权重未就绪，代码路径尚未实跑，不能称XLM-R已训练 |
| SFT/GRPO | completion mask、固定奖励和含active adapter的参考策略hash机制 | 仅机制测试；没有执行SFT或GRPO训练 |

微型编码器的pair结构先编码claim–单条证据，按预声明候选比较概率均值与logit均值，训练损失针对整包标签；不把整包标签冒充每一条证据的独立真值。pack结构在一个上下文中编码全部候选。证据监督在多组充分集合中确定性选择一个最小集合；评估仍对全部可接受集合取最佳set-F1。

微型编码器是本地管线模型，未使用预训练权重，也不是XLM-R或Judge微调。单个小型synthetic运行只证明训练流程、实际参数变化和重载，不支持质量提升、稳定性或岗位能力结论。

## 输入、分区与证据

`ReleaseReader`消费W01的FileRef、SplitManifest和四切面ModelInput，仅为指定train或dev分区逐项打开input/annotation文件。它不读取混合正文的records.json，也不遍历全release验证test内容。非relation/criterion任务按指定模型任务过滤并在scope报告列明。metadata只读索引和所请求分区的单条文件，带language、bucket、完整lineage及annotation状态，不再永远unspecified。

正式release必须由集成方注入metadata_approval，对准确release/split的W07审计及W11独立结构证据作核验；声明结构数量至少6，train/dev/test各至少2。仅看目录或一个自报valid字段不会自动取得正式入口。CLI当前没有这个真实批准端口，因此只能显式`--fixture`运行有fixture标记的资料，生产入口缺配置时明确失败。

模型训练只接受train，选择只接受dev；test和regression不会被训练入口读取。输入hash、record身份、任务标签、已接受标注、引用及类别覆盖不符时拒绝，不在训练脚本修改标签。模型特征只来自允许的用途、claim与证据正文，gold仅作为训练目标或评测端输入。

预测时文本预算不足或必要输入缺失显式abstain；训练时超长条目按冻结预算排除并记录record_id、input_hash、长度与计数，若剩余类别覆盖不足则明确失败。不截掉必要材料后仍宣称完整判断。数据文件/hash/标注错误会附record_id拒绝整个冻结release，交W07修复，不能静默改标签。程序缺陷与基础设施失败分开；KeyError等编程错误保存具体record_id并中止，不包装成模型能力失败。E1/E2各候选保存manifest、config、predictions、errors与metrics；目录存在不代表正式实验完成。模型输出携task_type、input_hash、模型revision、有序概率、引用及状态；格式、引用、基础设施失败和弃权分别保留。真实模型版本与候选预期不一致时保留原始adapter返回记录并计失败。

## 融合、指标与规则

关系概率顺序固定SUPPORTED/CONTRADICTED/INSUFFICIENT；criterion顺序固定MET/PARTIAL/NOT_MET/INSUFFICIENT/NOT_APPLICABLE。三类与五类不能混合，置信自评不能替代归一化分类概率。

选型策略在训练前落盘冻结为joint-first-dev-v1：joint正确性为第一项，其次coverage、macro-F1、预先声明的调用次数成本和稳定次序。joint为0或不可评价时不强行给出合格赢家。LR与编码器的alpha网格为0/0.25/0.5/0.75/1，证据阈值网格为0.25/0.5/0.75，只在dev选型。端点胜出或joint未优于端点时如实记录无融合增益；不允许引用全选但macro-F1高的候选掩盖joint=0。所有候选dev结果和落选项保留，不读取test再选择。

报告固定标签空间的macro-F1、逐类计数、混淆、误扣/误放及分母、覆盖、弃权、失败、引用F1与joint。证据不可评价时不进入joint分母，失败仍进入全请求分类分母；另报合法输出子集。引用多余、缺失、未解析或时间无效不能joint正确。按结构/连通根做配对与聚类bootstrap，小样本区间只作描述。

`reconcile_advice`仅对已适用项核对MET/PARTIAL/NOT_MET的确定规则界；INSUFFICIENT和NOT_APPLICABLE不放进数值排序。模型意见冲突时保留待核验，不能改写世界状态或已核验事实。

## 模型产物与冻结

LR、旧MLP、微型编码器及概率融合通过W01 ModelBundle保存为JSON+NPZ，不反序列化不可信pickle。加载核对文件hash、形状、固定标签顺序、允许的inference_entrypoint、源码及依赖引用；搬移目录后仍按相对路径加载。

开发运行保存实际runtime源码内容/hash及base commit，复制对应uv.lock，再保存训练、预测、错误、指标、选择、模型及冻结信息。源码在运行中变化、模型或配置漂移都会拒绝；重复输出目录不能覆盖。未获提交授权时source_digest覆盖实际运行代码，不只写HEAD。

冻结不直接打开inputs/labels/gold/proofs；数据通过release与split元数据hash固定。TestCampaign还需准确候选、runtime/evaluation、源码、预算与已开放时间匹配。当前只实现批准身份校验，不提供未经031登记即可读取test的路径。正式确认性评测仍待集成端和真实release，不用fixture自行授权研究。

## 运行入口

从本包独立checkout使用自己的虚拟环境：

```sh
.venv/bin/python -m career_lab.experiments.v3.training --help
.venv/bin/python -m career_lab.experiments.v3.training train-v3 --release-root <fixture-release> --release-hash <sha256> --split-hash <sha256> --output <new-output> --workspace <this-checkout> --fixture --epochs 4 --dimension 8 > train-result.json
.venv/bin/python -m career_lab.experiments.v3.training predict-v3 --root <saved-model> --bundle-hash <sha256> --input <allowed-model-input.json>
.venv/bin/python -m career_lab.experiments.v3.training check-freeze-v3 --root <experiment> --freeze-hash <sha256>
```

`train-v3`成功输出保留内部`freeze_id`，同时给出实际`freeze.json`绝对路径`freeze_path`和文件SHA-256 `freeze_hash`。`check-freeze-v3 --freeze-hash`使用文件hash；内部ID不能代替文件hash。上面的训练命令保存stdout为`train-result.json`后，以下命令可直接复制执行，路径中有空格也适用：

```sh
.venv/bin/python - <<'PY'
import json
import subprocess
import sys
from pathlib import Path
result = json.loads(Path("train-result.json").read_text())
subprocess.run([
    sys.executable, "-m", "career_lab.experiments.v3.training",
    "check-freeze-v3", "--root", str(Path(result["freeze_path"]).parent),
    "--freeze-hash", result["freeze_hash"],
], check=True)
PY
```

校验仍检查文件SHA-256、内部记录摘要及全部冻结成员。传错hash或篡改freeze文件/成员会拒绝；没有增加按内部ID跳过文件校验的入口。

总career-lab入口尚未挂载；模块提供`register_commands(commands)`及`w08_handler`给032串行集成。所有预测是advisory；predict CLI同时返回训练release引用和synthetic/development边界，不能把fixture模型显示为已验证产品模型。本地predict CLI不替代W05产品接口实调。

## 条件资源与接续

本机本轮只读核对为ARM64、16GiB内存、10CPU核心。W08独立基础环境含NumPy/scikit-learn，未安装torch/transformers；本次检查未发现可用XLM-R缓存，没有下载模型、购买资源或付费调用。最小依赖请求在本包配置目录的dependency-request.json，由032生成独立训练锁；默认产品安装不追加大型训练依赖。

预训练适配遵循官方的[本地权重与revision加载接口](https://huggingface.co/docs/transformers/main_classes/model)及[Tokenizer接口](https://huggingface.co/docs/transformers/main_classes/tokenizer)，强制local_files_only、固定提交revision、禁用remote code。接口代码存在不代表依赖、许可证、权重和设备已验证。

下一步由负责方回传业务源数据、结构证据与正式E1/E2；我方完成注册、重载复现、指标复核及真实产品调用。HF真实训练/重载、正式数据与test、三seed稳定性、真实检索损失、SFT/GRPO及正式产品调用均不得用本轮smoke代替。W07若有返工反馈仍优先处理。


## 2026-10-07 共同证据与新审阅边界

W07/W08统一使用historical-evidence-time-v1：被评价主张/行为的as_of是参照时点，导出capture point另存。已知开放区间与未知区间分开，未知上下文待核验；历史时点合法的旧材料可以支持历史事实，当前已失效的规则不能作为当前可接受引用。所有已接受gold集合在该帧必须存在合法joint输出；违反者带record_id退回数据端，不在grader里把本来不可能正确的目标用于训练/评测。

模型读取允许的参照时间和材料有效时间，不读取gold。误拒SUPPORTED现在将CONTRADICTED与INSUFFICIENT计入同一分母下的失败，并分别保留两类计数；弃权/服务失败另列覆盖和错误统计。该指标是模型判断代理量，advisory并未真实扣用户分。旧v1结果不可与新指标版本无说明混比。

单模型证据阈值按dev选型并写入模型配置；复合ModelBundle保留组件bundle、alpha、阈值、数据/代码身份，目录搬移后重载仍一致。随机seed、max_tokens可以通过CLI显式传入并冻结；单次运行仍只支持该seed的结论，三seed正式实验尚未执行。

HuggingFace本地目录不凭40位revision字符串认定身份。加载还需经批准的local checkpoint manifest，source_revision、完整文件成员和每个hash都匹配；pack实现由单次拼接后的token spans形成多标签证据头。HF真实设备/训练/重载仍未执行，代码修正不等于该能力已验证。

参考策略sft_identity由base与active adapter的完整FileRef集合哈希派生；任意自由字符串不再可用。该函数只核冻结机制，没有执行SFT/GRPO，也不自行证明输入确由SFT训练得到。set-F1仍保持独立v3实现，公共函数收敛待032确定共同落点；两者数学规则的回归需继续保留。

## c4元数据与跨包验证

ReleaseReader读取公共DatasetMetadataV2，依据实际model_input.task_type取得family；不再依赖私有metadata.family或source_snapshot_digest。每条侧记只含自身snapshot，核对语言、来源、完整谱系、capture_point及accepted状态，再用公共record/annotation配对及metadata_projection重建比较。自身正标签空证据/时点严校验保留。

W07以12个合成快照实际发布6 train与6 dev，W08用独立进程直接读取同一release/split hash，执行LR、旧字符MLP、微型attention pack/pair及融合选择，保存并重载模型。原始fit、权重变化、预测、错误、冻结、CLI输出和两端源码身份保存在本轮交付证据。没有模型下载、付费调用或封存研究test。fixture不能冒充真实业务release；本次仍不满足正式E1/E2、W11六结构、模型质量或产品调用验收。


## c4审阅补充：证据监督与来源身份

`evidence_evaluable=False`允许保留有独立依据的分类标签，但证据训练目标为None，LR不生成证据pair、attention不计算证据loss，evidence/joint指标均排除该行。训练报告列出evidence_train_ids与label_only_train_ids；分类损失与分类分母保留。不可评不表示标签正确：真实非G0纯标签记录还需独立label_only_authority核验，fixture只用于已知合成流程，不能推断语义真值。

可评记录的final.evidence_ids必须等于至少一组合法acceptable集合。证据监督统一从已完整校验的acceptable集合中选确定性最小集合，其他合法集合仍在评价时接受；合法INSUFFICIENT/NOT_APPLICABLE可以为空。不一致记录拒绝并带record_id，不静默修标签。

每条记录额外读取`origins/<record_id>.json`，绑定来源桶、session、完整lineage摘要、snapshot/source摘要及实际原文件FileRef；与DatasetMetadataV2和输入记录重建比较。删marker、改桶、重算外层hash仍不能将fixture变成业务输入。非fixture消费者除总体metadata_approval外，还必须注入独立source_authority逐条返回可信来源绑定；只接收release自报内容的回调不构成真实授权。该端口尚未接真实业务源，正式数据仍blocked。

来源绑定是验证用内部侧记，未修改冻结公共schema；新reader拒绝缺少来源绑定的旧release。旧release按原冻结源码追溯，不原地改写。


## v4训练就绪入口

新reader只消费W07 release-v4：readiness采用complete-accepted-training-v1，必须status=ready且scope匹配fixture/development；真实来源同时要求training_ready=true。合成数据的training_ready保持false，显式fixture ready仅开放本地合成流程，不代表研究通过。非ready发布在读取训练正文前带具体record_id/原因拒绝；即使manifest自报ready，实际input.completeness不足也在reader内拒绝，不等到fit时匿名整批崩溃，不生成替代标签或证据。


## Joint候选的最小训练资格

当前LR、Legacy MLP和Attention joint候选统一要求train至少有1条完整校验通过、evidence_evaluable=true的记录。pipeline在读取dev、训练和选型前执行同一training_examples闸门；Attention按容量排除记录后再次执行该闸门，不能保留未训练证据头参与joint选型，也不能用dev补训。缺少条件时返回joint_training_evidence_required及train记录范围，不生成该候选的可用模型包。该条件只是最低机械资格，一条证据不证明质量合格。

label-only导出与读取仍合法，既有分类标签及证据分母排除规则保持；没有新增classification-only产品模式。直接fit遇到不完整输入会给record_id、split和具体input原因。Reader的label_only_records按release hash、partition、record_id幂等记录，只有整行全部校验成功后才登记；读取日志仍保留每次真实访问。

ReleaseReader初始化已有SplitManifest.isolation，structure/component/ancestor跨区会在metadata/input/label/test正文读取之前拒绝。本轮入口反例验证该既有防线，不另复制一套校验。W07的全谱系与来源闸门、真实authority要求仍保持。origin-binding-v1跨包兼容继续用实际W07发布物→W08读取验证。


最低joint门槛与候选自身的训练条件分别生效。LR证据选择头要求正、负两类证据pair；例如唯一可评行为INSUFFICIENT且合法目标为空时，所有pair都为负，仍以evidence_selector_class_coverage_missing拒绝。当前pipeline保留候选失败即中止的fail-closed行为，不用dev补齐、不降低LR覆盖、不新增分类模式；至少一条可评记录不保证每个候选都能训练，更不保证质量。HF门槛目前仅做源码检查，真实运行继续blocked；没有安装依赖、下载checkpoint或付费验证。
