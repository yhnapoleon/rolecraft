# W08 模型与实验管线

当前为 **implementation_only / partial**，消费031固定的c4公共候选`expansion-v3-81f4855d5cdf8c601c6b09d7b350b11dcda5ed156e2d801d8e542fa197718c85`（commit `b55b4c260867ba04ca8ecac7232c9f5d3bcbc41f`）。本模块已实现可运行代码及小数据管线验证；W07合法fixture发布已实际消费；正式业务release、W11真实多结构和产品加载仍未接齐，不能据此宣称新E1/E2、模型质量或课程交付完成。

所有候选输出固定为advisory、affects_score=false。G2v只代表模型复核标签；独立人工语义校准与正式scoring采用不由本模块自动开启。

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
.venv/bin/python -m career_lab.experiments.v3.training train-v3 --release-root <fixture-release> --release-hash <sha256> --split-hash <sha256> --output <new-output> --workspace <this-checkout> --fixture --epochs 4 --dimension 8
.venv/bin/python -m career_lab.experiments.v3.training predict-v3 --root <saved-model> --bundle-hash <sha256> --input <allowed-model-input.json>
.venv/bin/python -m career_lab.experiments.v3.training check-freeze-v3 --root <experiment> --freeze-hash <sha256>
```

总career-lab入口尚未挂载；模块提供`register_commands(commands)`及`w08_handler`给032串行集成。所有预测是advisory；predict CLI同时返回训练release引用和synthetic/development边界，不能把fixture模型显示为已验证产品模型。本地predict CLI不替代W05产品接口实调。

## 条件资源与接续

本机本轮只读核对为ARM64、16GiB内存、10CPU核心。W08独立基础环境含NumPy/scikit-learn，未安装torch/transformers；本次检查未发现可用XLM-R缓存，没有下载模型、购买资源或付费调用。最小依赖请求在本包配置目录的dependency-request.json，由032生成独立训练锁；默认产品安装不追加大型训练依赖。

预训练适配遵循官方的[本地权重与revision加载接口](https://huggingface.co/docs/transformers/main_classes/model)及[Tokenizer接口](https://huggingface.co/docs/transformers/main_classes/tokenizer)，强制local_files_only、固定提交revision、禁用remote code。接口代码存在不代表依赖、许可证、权重和设备已验证。

下一步取得W07业务源审计数据与W11结构证据后跑正式E1/E2；选择并锁定编码器资源，再完成产品加载和逐项AC。HF真实训练/重载、正式数据与test、三seed稳定性、真实检索损失、SFT/GRPO及正式产品调用均不得用本轮smoke代替。W07若有返工反馈仍优先处理。


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
