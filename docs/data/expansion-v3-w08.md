# W08 模型与实验管线

## 现行职责与验证边界（2026-10-09）

我方仅推进运行导出、注册接入与独立复核；负责方承担数据生成/标注/划分、全部训练融合、SFT/GRPO、评价项五分类、E2/Jev及预算算力。以下既有训练/标注命令保留供负责方和历史复现使用，不表示本轮已执行或我方继续训练。v2-r1交接ZIP与数据保持原样。

本轮接续原035双语增量，新增检查只用合成记录或已保全产物，均标synthetic。语言、hash/span、译本同split和分别统计只证明机制；真实中英v4运行、外部真实回传和质量仍独立验收。未接真实模型的产品位置显示“等待模型接入”，事实规则显示“规则核实”；注册输出仅advisory，真实调用及外层恢复均零自动重试。

当前工程能力：

- 登记四种产物：W01 ModelBundle、负责方线性回传、编码器回传 v3，以及由两个已登记回传组成的概率融合（见[线性回传与融合注册](#线性回传与融合注册)、[本地编码器回传注册](#本地编码器回传注册)）。
- 正常 API 与 worker 按服务端配置，对 R2.support 逐句给出关系建议，原 v4 反馈页显示身份、逐句结果与证据（见[服务消费与回退边界](#服务消费与回退边界)）；ROLES／JUDGE／SUPPORT／ASSISTANT 四个模型槽各自配置（见[模型槽配置](#模型槽配置)）。
- 正式回传复核 CLI：dev 复核、按容差重载比对、融合选择复算、封存 test 一次性打开（见[正式回传复核 CLI](#正式回传复核-cli2026-10-09)）。
- 授权导出可附带作品单句关系记录（见 [W07 手册](expansion-v3-w07.md#研究授权与真实会话导出)）。

完整候选门禁与历史fixture兼容由总协调核验；契约不匹配不能自动归因为现行安装包需要切换。本手册不把局部测试作为整包放行。负责方真实数据、checkpoint、训练执行、分语言质量和E1/E2实验结论仍待交付。历史c5及各轮训练记录保留其原时点范围。

所有候选输出固定为advisory、affects_score=false。G2v只代表模型复核标签；独立人工语义校准与正式scoring采用不由本模块自动开启。

## 043 M3：冻结模型注册、调用回执与回传复算（2026-10-07）

本节规定注册、服务端调用回执与回传复算。正常 API 与 worker 已按服务端配置消费注册（见[服务消费与回退边界](#服务消费与回退边界)）。负责方真实训练模型尚未交回；仓库测试只用固定synthetic权重或构造权重，不调用fit、不训练、不下载、不访问线上provider。既有v2-r1交接包不重包。

### 注册与冻结身份

`models/v3/registry.py`现接四种产物：

- W01 ModelBundle（`model-bundle.json`：NumPy线性、attention、旧MLP与概率融合），经原load_bundle校验任务、固定标签顺序、权重/预处理/训练来源/依赖引用与允许的推理入口，只复制实际引用的文件；
- 负责方编码器回传（`checkpoint-manifest.json`，[编码器回传 v3](return-v3/encoder-return.md)，见[本地编码器回传注册](#本地编码器回传注册)）；
- 负责方线性回传`rolecraft-linear-return-v1`（[线性回传](return-v3/linear-return.md)）；
- 由两个已登记回传与dev选择记录组成的融合注册（[融合选择记录](return-v3/fusion-selection.md)）。

后三种见[线性回传与融合注册](#线性回传与融合注册)。注册项按内容命名且不可覆盖，移动registry目录仍可重载。

注册身份只锁推理闭包：`src/career_lab/models/**`、`contracts/v2/core.py`、`contracts/v2/data.py`的源码hash，以及numpy、scikit-learn、pydantic版本；编码器注册另锁torch、transformers、tokenizers、safetensors的已安装版本。这些任一变化，旧注册在加载时拒绝（`registered_inference_runtime_changed`），对同一回传重新登记即可；其他产品文件改动不影响已登记模型。闭包含模型目录下全部代码（含注册与复核工具），所以任何改动`models/**`的提交合入后，部署机上的注册都要重新登记。权重或注册文件变化同样拒绝；不改旧manifest、不补hash。

来源标记为`synthetic_fixture`或`external_candidate`，由操作者按产物实际来源选择。以下情形登记为`external_candidate`时拒绝（`fixture_cannot_be_registered_as_external`）：W01 bundle的训练release标`fixture=true`；回传的数据身份名含`fixture`；线性回传的数据manifest是冻结fixture v2那份。机制不能识别其余合成数据，scope如实填写是操作规则。`external_candidate`只表示待复核外部候选，不能自动升级质量、正式scoring或整体验收。SFT/GRPO/Jev产物及上列以外的格式没有加载器，不承诺任意checkpoint可加载。

### 单次调用与产品接线

`RegisteredAdvisory.predict`只读取checked ModelInput，输出已有Prediction及W01 ModelPrediction公共投影、登记版本、输入hash、工作语言与实际状态；不把gold/annotation送入推理。`registry_cli predict`默认拒绝synthetic注册（`synthetic_model_not_product_ready`）；加`--allow-synthetic`可算出预测，但输出里的`public_prediction`仍为unavailable。正常反馈对synthetic注册另按机制演示投影：显示标签与证据，状态固定`synthetic_mechanism_only`，界面标「合成机制演示」，不是模型判断、不计分。

调用前持久化同一真实模型尝试ID及输入/注册/语言绑定；同ID再次请求只恢复已有结果。中断pending保持unconfirmed，失败不自动重调，不自动转INSUFFICIENT。确需重试时由上游明确用户动作给新尝试ID和`retry_of`，保留旧失败及关联；编程、协议、基础设施失败分开。

这些文件是**服务端模型调用回执**，不是第二套用户Command或客户端恢复流程。032的公共host/Gateway仍负责唯一会话、授权、Command和用户恢复；模块不会创建token、UI恢复按钮或前端日志。公共装配把既有真实模型attempt ID传给适配器，并将回执接回同一任务结果；正常worker的反馈作业按句各落一条回执（见[服务消费与回退边界](#服务消费与回退边界)）。负责方真实模型尚未在产品里调用过。

原v4反馈页读取反馈里的`model_advice`（显示方式见[反馈页显示](#反馈页显示)）：没有注册建议时按反馈的语义状态标「等待模型接入」或「模型建议待核验」，synthetic注册标「合成机制演示」，外部候选标「模型建议（不计分）」。真实规则事实使用自身规则结果和“规则核实”，不能从本模型scope推断规则有效性。结果始终advisory、affects_score=false；质量验证和采用由独立总验收决定。

### 回传复算

`experiments/v3/training/review.py`独立重载两份同注册产物，对相同输入重新预测并核重载一致；从独立提供的Example/标签重算固定标签顺序、macro-F1、证据F1、joint及分母，中英分别报告，缺一语明确缺失。可对负责方逐条预测做身份/标签顺序校验及差异报告，不直接相信其汇总指标。既有生产者用null保留格式失败的记录：复核将其单列missing_prediction_record_ids并标incomplete，不算一致，也不补成INSUFFICIENT。技术失败单列，不重试或伪造INSUFFICIENT；首次失败不再做第二次推理冒充恢复。

`registry_cli review`只读train或dev分区（缺省dev），不打开test；负责方回传的封存test只能经[正式回传复核 CLI](#正式回传复核-cli2026-10-09)的一次性打开读取。CLI复用ReleaseReader权限、来源与split门槛，不能用--fixture祝福真实数据；正式源缺metadata/source authority仍拒绝，后续由固定live适配器提供。指标复算与外部数据/标签的语义真实性、真实模型质量分别报告。

### 可复现入口

从本W08工作区使用自身`.venv`；参数中的hash来自实际已固定产物，不手写补造。以下入口不包含训练：

```sh
.venv/bin/python -m career_lab.models.v3.registry_cli --help
.venv/bin/python -m career_lab.models.v3.registry_cli register --registry <独立注册目录> --bundle-root <已回传或明确fixture的ModelBundle目录> --bundle-hash <真实sha256> --scope synthetic_fixture
.venv/bin/python -m career_lab.models.v3.registry_cli predict --registry <注册目录> --registration-path <注册返回相对路径> --registration-hash <真实sha256> --journal <服务端调用证据目录> --request-id <真实尝试ID> --language en --input <允许的ModelInput文件> --allow-synthetic
.venv/bin/python -m career_lab.models.v3.registry_cli recover --registry <注册目录> --registration-path <原相对路径> --registration-hash <原sha256> --journal <原调用证据目录> --request-id <原尝试ID>
.venv/bin/python -m career_lab.models.v3.registry_cli review --registry <注册目录> --registration-path <原相对路径> --registration-hash <原sha256> --release-root <冻结release> --release-hash <真实sha256> --split-hash <真实sha256> --partition dev --task relation --fixture
```

真实候选register使用`external_candidate`且predict不传`--allow-synthetic`。参数只是本机服务器/审核者入口，不直接暴露为学员授权能力；真实产品仍走已鉴权的公共Gateway。实际测试日志与命令在本包`runs/local/expansion-v3/W08/20261007-043-registry/`。13项定向检查通过，包括真实CLI注册/调用/只读恢复、篡改拒绝、模型零隐式重调、重载与中英指标；不等于正式v4或模型质量通过。

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
| 预训练编码器 | 显式固定revision、仅本地权重的Hugging Face适配，带监督fit/predict/checkpoint重载接口 | 可选CPU依赖下已实跑本地随机微型BERT的pack/pair/pair_aggregate保存、注册与重载；XLM-R base真实权重配未训练头已做接收端冒烟（见[XLM-R 接收端冒烟](#xlm-r-接收端冒烟)），只证明加载、切句、计长与弃权；负责方训练的XLM-R产物和语义质量仍待交付 |
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

开发机为ARM64、16GiB内存、10CPU核心。默认产品安装（`uv sync --locked`）含NumPy/scikit-learn，不含torch/transformers；编码器推理依赖是锁文件里的可选extra `encoder`（见[可选CPU加载环境](#可选cpu加载环境)）。XLM-R base权重经用户2026-10-12确认下载到仓库与iCloud之外，只作接收端冒烟；没有购买资源或付费调用。

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


最低joint门槛与候选自身的训练条件分别生效。LR证据选择头要求正、负两类证据pair；例如唯一可评行为INSUFFICIENT且合法目标为空时，所有pair都为负，仍以evidence_selector_class_coverage_missing拒绝。当前pipeline保留候选失败即中止的fail-closed行为，不用dev补齐、不降低LR覆盖、不新增分类模式；至少一条可评记录不保证每个候选都能训练，更不保证质量。本节原轮次仅核对HF源码，未安装依赖或运行HF。后续已通过可选CPU依赖实跑随机微型BERT的双输出、保存与重载（见下方本地编码器回传注册），并用XLM-R base真实权重配未训练头做了接收端冒烟（见下方XLM-R 接收端冒烟）；负责方的实际训练交付和语义质量仍blocked，没有调用付费模型。


## 线性回传与融合注册

线性回传与编码器回传共用`register`命令，按外层清单的`artifact_kind`分派；融合用`register-fusion`。格式规格见[线性回传](return-v3/linear-return.md)与[融合选择记录](return-v3/fusion-selection.md)。负责方用`docs/data/return-v3/reference/export_sklearn_linear.py`导出线性回传，用`reference/linear_text_v1.py`与`linear-text-v1.golden.jsonl`自检特征文本；我方不运行负责方的命令。

### 登记一份回传

从仓库根目录运行。`RETURN`是回传目录（含`checkpoint-manifest.json`），`REGISTRY`是注册目录，`OUT`是保存登记输出的目录（放在git忽略的`runs/`下或仓库之外）；路径可以含空格。合成或fixture数据改用`--scope synthetic_fixture`。编码器回传要在装有encoder extra的环境登记（见[本地编码器回传注册](#本地编码器回传注册)）。

```sh
RETURN='/path/to/return'
REGISTRY='/path/to/registry'
OUT='runs/local/registration-left'
mkdir -p "$OUT"
uv run --locked python -m career_lab.models.v3.registry_cli register \
  --registry "$REGISTRY" --bundle-root "$RETURN" \
  --bundle-path checkpoint-manifest.json \
  --bundle-hash "$(shasum -a 256 "$RETURN/checkpoint-manifest.json" | cut -d ' ' -f 1)" \
  --scope external_candidate > "$OUT/register-output.json"
uv run --locked python -c 'import json, sys; print(json.dumps(json.load(sys.stdin)["registration"]))' \
  < "$OUT/register-output.json" > "$OUT/registration-ref.json"
```

`register-output.json`形如`{"registration": <FileRef>, "mode": "advisory", "quality_validated": false, "training_performed": false}`。`registration-ref.json`只含其中的FileRef：`path`是注册目录内的相对路径，`sha256`是注册文件的hash。后续`describe`、`register-fusion`、`verify-return`与服务端配置都用这一对，两者必须一起保存。相同产物重复登记回读同一身份，输出逐字节相同。

### 查看公开身份

```sh
uv run --locked python -m career_lab.models.v3.registry_cli describe --registry "$REGISTRY" \
  --registration-path '<registration-ref.json 里的 path>' \
  --registration-hash '<registration-ref.json 里的 sha256>'
```

输出公开身份：`id`、`model_revision`、`scope`、`quality_validated=false`；线性回传、编码器回传与融合另有`kind`（`linear`、`huggingface_encoder`、`probability_fusion`）和`dataset`（数据集名、数据manifest hash、标签等级`label_tiers`），编码器另有`weights_stage`，融合另有`components`（左右分量的注册id、类型、`model_revision`与该分量在融合概率中的权重：左为1−alpha，右为alpha）与`fusion`（`alpha`、`evidence_threshold`、`fusion_gain_observed`）。W01 bundle注册只有前四项。

### 登记融合

两个分量先各自登记到同一注册目录，再：

```sh
uv run --locked python -m career_lab.models.v3.registry_cli register-fusion --registry "$REGISTRY" \
  --left-path '<左分量注册相对路径>' --left-hash '<左分量注册 SHA-256>' \
  --right-path '<右分量注册相对路径>' --right-hash '<右分量注册 SHA-256>' \
  --selection /path/to/fusion-selection.json \
  --scope external_candidate > "$OUT/register-output.json"
uv run --locked python -c 'import json, sys; print(json.dumps(json.load(sys.stdin)["registration"]))' \
  < "$OUT/register-output.json" > "$OUT/registration-ref.json"
```

`OUT`换成融合自己的新目录（例如`runs/local/registration-fusion`）。输出格式与`register`相同。选择记录须按`joint-first-dev-v1`在dev上选点（[融合选择记录 §3](return-v3/fusion-selection.md)；融合预测在证据可评记录上出现无证据的支持或矛盾成功行的点没有资格，与回传格式检查同一判定），两分量须来自同一数据身份。登记只核选择记录的结构与身份，逐点指标由`verify-return --fusion-selection`复算（见[正式回传复核 CLI](#正式回传复核-cli2026-10-09)）。融合不复制分量权重，注册目录只多存一份选择记录副本；每次加载都重核两个分量的注册与文件，任一分量漂移、被删或推理闭包变化，融合即加载失败。任一分量为合成登记时，融合只能`--scope synthetic_fixture`（否则`fusion_scope_exceeds_components`）。

## 本地编码器回传注册

注册接收负责方回传的编码器`checkpoint-manifest.json`，格式见[编码器回传 v3](return-v3/encoder-return.md)：

- v3 `checkpoint.json`写明`variant`（pack／pair／pair_aggregate）、`pooling=mean`、`evidence_threshold`（pair_aggregate不低于0.5）、`max_tokens`；fixture v2时代的布局仍收（阈值固定0.5）。
- 目录里每个文件（清单本身除外）都要列进`checkpoint_files`，后缀只许白名单。交付前删去`.DS_Store`等隐藏文件，否则整份回传被拒（`checkpoint_member_set_mismatch`或`checkpoint_file_type_not_allowed`）。
- 负责方用`docs/data/return-v3/reference/export_hf_return.py export`写布局、`seal`写外层清单。我方不执行清单里的`load_and_predict_command`或生产者Python代码。
- 大权重不进NumPy的64MB加载器：登记流式校验并复制清单文件，在独立副本全部校验后发布不可变注册；注册后不依赖生产者目录。

登记命令与[登记一份回传](#登记一份回传)相同，只是要在装有encoder extra的环境运行。登记不导入torch，但要求torch、transformers、tokenizers、safetensors已安装，并把它们的版本写进注册；缺任一包时拒绝（`encoder_runtime_unavailable`，退出2，不建注册目录）。

```sh
uv run --locked --extra encoder python -m career_lab.models.v3.registry_cli register \
  --registry "$REGISTRY" --bundle-root "$RETURN" \
  --bundle-path checkpoint-manifest.json \
  --bundle-hash "$(shasum -a 256 "$RETURN/checkpoint-manifest.json" | cut -d ' ' -f 1)" \
  --scope external_candidate > "$OUT/register-output.json"
```

`registration-ref.json`的取法同上。

`uv run --extra encoder`会把这些包装进项目`.venv`；要保持默认环境不变，改用独立环境（见下节）。

- **登记成功不等于能加载**。登记只核文件、hash、清单、推理设置与头的名字、形状、类型；`after_weights`要到加载时重算。负责方交付前应在锁定版本下自行加载一次。加载失败时`registry_cli predict`以退出2给出异常类别（不回显文件内容），正常反馈里该建议显示「模型建议失败」（`model_load_failed`），不切换到其他模型。
- 注册记录的依赖版本含平台本地标签（例如Linux的`2.8.0+cpu`），不能跨平台或跨环境搬用，按部署机重新登记。已安装版本与注册不同时，`describe`与加载都拒绝（`registered_inference_runtime_changed`）；对同一回传重新登记即可。
- `weights_stage=supervised_finetuned`可登记external或synthetic；`pretrained_untrained_heads`只能`--scope synthetic_fixture`（否则`untrained_heads_require_synthetic_scope`），界面只作「合成机制演示」并标「预训练权重 · 分类头未训练」。
- 旧协议`advisory-encoder-registration-v1`的注册不再产生新建议，新反馈报`model_reference_invalid`；用它产生过的反馈照原样可读。对同一回传重新登记即得到现行注册。
- 文件漂移、标签顺序/任务域错误、模板或未完成声明、test参与选型均拒绝；`quality_validated`和`affects_score`始终为false。负责方能触发的拒绝码见[编码器回传 v3 §13](return-v3/encoder-return.md)。运维中还可能见到：注册目录内部的`model_registration_drift`、`model_registration_busy`、`registration_scope_required`；加载时的完整性码`model_registration_identity_mismatch`、`registered_model_identity_mismatch`；预测时的逐条弃权码`evidence_span_missing_or_truncated`、`pack_evidence_spans_require_fast_tokenizer`。

### 可选CPU加载环境

默认`uv sync --locked`不安装encoder依赖。encoder extra固定torch 2.8.0、transformers 4.57.1、tokenizers 0.22.2、safetensors 0.6.2；Linux/Windows使用CPU wheel源，本地适配始终把模型放在CPU，加载只用本地文件、禁用remote code（参见[Transformers 4.57.1本地加载说明](https://huggingface.co/docs/transformers/v4.57.1/installation)与[PyTorch安装说明](https://pytorch.org/get-started/locally/)）。

缺这些依赖时：登记拒绝（`encoder_runtime_unavailable`）；`describe`仍打印已有注册的身份；加载与产品推理返回`pretrained_encoder_dependencies_unavailable`（协议状态503），CLI以非零退出，不自动安装、下载或换模型。

建议把encoder extra装进git忽略目录下的独立环境，项目`.venv`保持默认产品依赖：

```sh
export UV_PROJECT_ENVIRONMENT="$PWD/runs/local/venv-encoder"
uv sync --locked --python 3.12 --extra encoder
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --extra encoder python -m pytest -q \
  tests/optional_encoder/check_encoder_v3.py \
  tests/optional_encoder/check_local_encoder.py \
  tests/optional_encoder/check_fusion_registration.py \
  --basetemp=.pytest_cache/tmp-encoder-check
unset UV_PROJECT_ENVIRONMENT
```

也可以直接在项目`.venv`里`uv sync --locked --python 3.12 --extra encoder`，用完以`uv sync --locked --python 3.12`回到默认产品依赖；`uv run`不会删掉已装的extra，默认环境里残留torch会改变缺依赖相关测试的结果。

可选检查采用显式运行的`check_`文件名，不进入默认pytest发现：

- `check_local_encoder.py`、`check_encoder_v3.py`：测试自己随机初始化小于200KB的微型BERT，用现有数值fixture做最小优化步骤，再保存、登记、重载和比较预测，同时阻断socket连接；pack、pair、pair_aggregate都实跑。公开预测仍是`synthetic_mechanism_only`／unavailable。
- `check_fusion_registration.py`：在CPU上登记、加载、预测线性回传×微型v3编码器回传的异构融合，结果与两分量按alpha混合一致。

这些只验证实际加载与双输出机制，不是预训练模型、英文质量、真实XLM-R或融合增益的证据。

默认环境的编码器登记测试靠`tests/unit/encoder_runtime_metadata/`下的包元数据声明（只有METADATA，没有代码）模拟已安装依赖，有三处已知限制：声明在进程内追加到`sys.path`且不还原；发布包不含这4个METADATA文件，在无extra环境跑发布包里的这些测试会失败；缺依赖的拒绝（RT-03）是进程内模拟，真实无extra进程里的CLI行为以上面「缺这些依赖时」为准。

### XLM-R 接收端冒烟

用真实`FacebookAI/xlm-roberta-base`权重走一遍负责方回传的同一路径：`export_hf_return.py export --weights-stage pretrained_untrained_heads`（头按seed初始化，未训练）→`seal`→`register --scope synthetic_fixture`；再用该注册跑正常运行时（HTTP＋worker，进程内），对场景自带的中英作品各评两次，从逐句journal统计token数、超限弃权与每句耗时。权重放在仓库与iCloud之外（本机`/Users/jefmacmini/Projects/rolecraft-models/xlm-roberta-base/<40 位 revision>/`），不进git。

```sh
uv run --locked --extra encoder python -m scripts.smoke.xlmr_base \
  --model-dir '/path/to/xlm-roberta-base/<40 位 revision>' --revision '<40 位 revision>' \
  --out /path/to/new-dir --variants pair pack
ROLECRAFT_XLMR_DIR='/path/to/xlm-roberta-base/<40 位 revision>' HF_HUB_OFFLINE=1 \
  uv run --locked --extra encoder python -m pytest -q tests/optional_encoder/check_xlmr_smoke.py
```

`--variants`缺省即`pair pack`。可选检查未给`ROLECRAFT_XLMR_DIR`时失败而不是跳过。手工做同一登记时：`python docs/data/return-v3/reference/export_hf_return.py export --encoder-dir <下载目录> --weights-stage pretrained_untrained_heads --variant pair --source-revision <40 位> --max-tokens 512 --out <新目录>`，再`seal --root <新目录> --dataset-manifest <dataset-manifest.json>`，然后按[登记一份回传](#登记一份回传)以`--scope synthetic_fixture`登记。

这种注册只能`synthetic_fixture`、`weights_stage=pretrained_untrained_heads`；界面标「预训练权重 · 分类头未训练」与「合成机制演示」。头是随机的，每个标签都只是机制样例。

本机（Apple Silicon CPU）实测：

| 项 | 结果 |
|---|---|
| 加载 | 约2.3–4秒；峰值RSS约2.6–3.2 GB |
| 每句推理p50 | pair 0.12–0.16秒（3个候选）、0.26–0.31秒（8个候选）；pack 0.08–0.09秒（3个候选） |
| 一次评审 | 首评（含加载）2.8–4.8秒；二评（缓存命中）1.4–3.3秒 |
| 作品句token数 | 中文140–156（pair）、英文170–194 |
| 引用整篇材料 | pair每对529–578、pack 1317–1532，全部超512，如实弃权；pack引用8个片段（622–700）也全部弃权 |
| 正常入口默认候选 | XLM-R pair 391–474，未超限；微型编码器（上限256）全部弃权 |

这是机制证据，不是质量或训练证据。

句数上限`MAX_UNITS`现为24（`src/career_lab/models/v3/units.py`常量）。按本机pair、8个候选的p95约0.34秒每句计，24句约8秒，可以保持24。若部署CPU慢3倍以上（推断，未实测），或一次评审含多个R2.support包，建议降到12，或改为同包句子合批前向。更大的风险是候选材料长度：引用整篇材料即全部超限弃权，建议负责方优先pair／pair_aggregate；候选按引用片段或分块送入属后续待定事项。真实作品的超限弃权率可从journal结果的`input_size`统计。

### 服务消费与回退边界

正常API与worker的默认反馈工厂消费服务端注册配置。原规则、评分和14项定义保持；R2.support单独追加关系建议，公开字段带实际注册身份、正式request/job、输入hash和建议状态，所有建议固定advisory、affects_score=false。

R2.support按规则切句后逐句推理（策略`r2-support-units-v1`，按规则切句，不是陈述抽取）：

- 空行分段；`-`、`*`、`•`、`1.`开头的行各成一句，只占该行，所以折行列表项的续行自成一句；以`2024. `这类「数字加点加空格」开头的行也按编号项处理，编号不进原句。
- `。！？；!?;`与「英文句点后接空白或结尾、前一字符不是数字、且不是e.g./i.e./vs./etc.」为句界；小数不切，`12. Next`与`etc. Done.`不切。
- 每句一个关系输入：claim为该句，候选、用途、时点与整篇相同，作品自身及其局部自引不充当证据。
- 去空白后少于4个非空白字符（标点计入）的句子计`skipped_short`，如`OK.`、`Mr.`；`Yes.`照常判断。每包最多24句，其余计`over_budget`，都在`aggregation.counts`列出。
- 每句先`measure()`，超过注册模型token上限的记`abstained`／`unit_exceeds_encoder_limit`，不截断。
- 作品级保守聚合：任一句矛盾为CONTRADICTED；全部计入句都成功且支持、且无弃权、失败、超额为SUPPORTED；其余为INSUFFICIENT；全部弃权写`all_units_abstained`。作品级证据为支持与矛盾句证据的并集，逐句结果在`model_advice[].units`，策略与七项计数在`aggregation`。
- 合成注册（`synthetic_fixture`）可显示标签与证据，状态固定`synthetic_mechanism_only`，不是模型判断、不计分。
- 模型建议的任何失败只表现为该建议的失败状态，规则反馈照常写出。场景材料只在被建议引用时进入其读取依赖。

API与worker应继承同一数据库、注册引用及journal配置。`CAREER_LAB_MODEL_REGISTRATION`的值是[登记一份回传](#登记一份回传)保存的`registration-ref.json`内容（FileRef对象，不含外层`registration`键），可以指向任一种注册（W01 bundle、线性回传、编码器回传、融合）；建议里的`registration`相应带`kind`、`dataset`，融合另带`components`与`fusion`。`CAREER_LAB_MODEL_JOURNAL`缺省为`<注册目录>/journal`。以下路径换成该次真实登记结果：

```sh
export CAREER_LAB_MODEL_REGISTRY=/path/to/registry
export CAREER_LAB_MODEL_REGISTRATION="$(cat /path/to/registration-ref.json)"
export CAREER_LAB_MODEL_JOURNAL=/path/to/persistent-model-journal
uv run --locked career-lab serve --host 127.0.0.1 --port 19812 \
  --database-url sqlite:///runs/local/model-session.db --provider local
# 从相同环境另开worker进程
uv run --locked career-lab worker \
  --database-url sqlite:///runs/local/model-session.db --provider local
```

按任务配置多个注册时改用`CAREER_LAB_MODEL_REGISTRATIONS`，两个键都可以省略，`CAREER_LAB_MODEL_REGISTRY`是共用根目录：

```sh
export CAREER_LAB_MODEL_REGISTRATIONS="{\"relation\": $(cat /path/to/registration-ref.json)}"
```

- 与`CAREER_LAB_MODEL_REGISTRATION`二选一，两者都设时拒绝启动（`model_registration_config_ambiguous`）；值不是`{"relation": FileRef, "criterion": FileRef}`形状时拒绝启动（`model_registration_config_invalid`）。
- `criterion`键目前只校验格式，不加载模型，不产生建议。

切换前后这样核对：

1. 用同一份`registration-ref.json`跑一次[`describe`](#查看公开身份)，确认身份就是要切换的注册。格式正确但指向不存在或已漂移的注册时，服务照常启动，问题只出现在新反馈的模型建议里（失败状态），所以要先核。
2. 用同一组环境变量对一个临时空数据库试启动worker（`--once`遇到排队作业会真的执行一个，所以不要指向正式数据库）：

   ```sh
   uv run --locked career-lab worker --once --database-url sqlite:///runs/local/startup-check.db --provider local
   ```

   stderr逐行打印四个模型槽的provider、model与指纹（见[模型槽配置](#模型槽配置)），退出0；配置错误时只打印`career-lab: startup refused: <错误码>`并以2退出，不回显路径、取值或key。
3. 核对无误后重启serve与worker两个进程。

PR #17之后，签发或恢复委托等凭据另需部署环境提供`CAREER_LAB_CREDENTIAL_KEY_ID`与`CAREER_LAB_CREDENTIAL_KEY`，API/worker保持一致；密钥不写入本手册、模型配置文件或运行回执。本地验收使用临时随机测试密钥，生产没有默认密钥。

装配时解析一次并固定服务实例的注册引用，运行中改环境变量不会切换它；新配置需要重启API/worker。该范围不包含跨重启后旧会话新请求的持久模型绑定。旧反馈保存原身份与内容；同一正式请求的已有模型收据优先回读，即使此时权重漂移、加载不可用也不重新推理。并发重试共享原job和收据；显式新尝试由既有job/request机制区分。

- 每句是一条独立journal请求（request_id由作品请求、句序号与`unit_hash`派生）。恢复只读已记录的句子，只对没有记录的句子推理。
- 服务进程缓存已全量核验的模型。每次调用复核那次全量核验实际读过的每个文件（融合包括分量的注册与权重）：大小、mtime_ns、ctime_ns、inode，1 MiB以内的文件另重算sha256。有变化即全量复核，漂移在新反馈里显示`model_files_changed`（界面：「模型文件或推理环境已变化，需重新核验注册。」）。轻量复核只看上次核验读过的文件，缓存生效后往注册目录新增的文件要到下一次全量核验才会被注意到。
- 源码或依赖版本的变化不在轻量复核里，服务重启后由全量核验拒绝（`registered_inference_runtime_changed`）。
- 超上限弃权的句子在journal结果里带`input_size{tokens, limit}`；`elapsed_seconds`逐句记录。
- 退役的编码器注册（`advisory-encoder-registration-v1`）报`model_reference_invalid`，须用现行协议重新登记。

缺引用、文件/运行时漂移、缺可选依赖、超时、基础设施失败和无效推理结果分别给出安全状态，已核实规则与作品保留。完整输入的任一依赖失去权限时，对应建议清除标签、证据和输入hash，保留公开注册身份；不重算旧反馈。关闭新建议时清除模型注册变量并重启两进程；切换候选时指定已登记的准确引用并重启，保留原模型、反馈及journal，不覆盖旧登记。

#### 反馈页显示

原v4反馈页「理由与证据的支持关系」显示R2.support的注册建议：

- 折叠时一行标题加三行短结果。标题按状态为「合成机制演示」（合成注册，下一行写「合成或未训练权重，不是模型判断，不计分。」）、「模型建议（不计分）」（外部候选）、「模型建议失败」「模型调用超时」「模型未判断任何句子」。接着是逐句计数，只列非零项（支持、矛盾、证据不足、超长未核、模型弃权、失败、过短未核、超出句数上限）。有结论时最后用较浅字色写「作品整体：存在矛盾／全部有支持／部分证据不足」。
- 展开后逐句列出原句、结果与证据按钮（按钮写材料ID与版本，如「材料 policy · 第 1 版」，点开对应材料原文），再写切句说明与注册身份：模型、类型、版本、训练数据与标签等级、权重阶段、融合左右分量与权重、alpha、dev上有无融合收益。
- 失败、超时、全部未判断不显示任何标签，写明未采用任何模型建议，原作品与已核实规则结果保留。
- 区块上方「评价模型：{provider} · {model}」读这份反馈provenance记下的JUDGE槽（另配支持核验模型时追加「 · 支持核验模型：…」），未配置写「未接入」。
- 界面只读，不发起推理。合成结果不计入模型覆盖率，分数区间与覆盖率不读这些字段。criterion建议条目读取时跳过，不影响整块显示。

前端结构与本地复验见[模型建议前端](../modules/expansion-v3/W08.md)。

### 模型槽配置

serve与worker启动时各读一次四个模型槽：ROLES（三位同事）、JUDGE（语义Judge）、SUPPORT（支持核验）、ASSISTANT（知识助手生成）。每槽变量：

- `CAREER_LAB_<SLOT>_PROVIDER`：`local`、`deepseek`、`openai`、`openai_compatible`；
- `CAREER_LAB_<SLOT>_KEY_FILE`、`_BASE_URL`、`_MODEL`；
- `_MAX_TOKENS`（缺省512）、`_TIMEOUT`（缺省45秒）；JUDGE、SUPPORT另有`_INPUT_BYTES`（缺省64000）。

一层原则：每个槽的provider、key文件、base URL、model只来自一层，key只发往与它一同配置的端点。

- 槽设了自己的`_PROVIDER`：只用本槽的`_KEY_FILE`、`_BASE_URL`、`_MODEL`；没设的只用该provider自带的缺省（DeepSeek为`ds.txt`／`https://api.deepseek.com`／`deepseek-chat`，OpenAI为`openai.txt`／`https://api.openai.com/v1`／`gpt-4.1-mini`）。共用的`CAREER_LAB_KEY_FILE`不会带到设了自己provider的槽。
- SUPPORT没设provider：整体沿用JUDGE槽；自己没设的预算也沿用JUDGE。
- 其他槽没设provider：整体沿用共用的`--provider`、`CAREER_LAB_KEY_FILE`、`CAREER_LAB_BASE_URL`、`CAREER_LAB_MODEL`。槽变量都不设时，模型、请求与provenance与单一共用配置完全相同。
- 槽没设provider却设了key文件、base URL或model：拒绝启动（`model_slot_provider_required`）。
- 预算变量可以按槽单独设置；取值非法时拒绝启动（`model_slot_value_invalid`）。

本地Qwen示例（经vLLM或llama.cpp server的OpenAI兼容接口提供，产品不内置）：

```sh
export CAREER_LAB_JUDGE_PROVIDER=openai_compatible
export CAREER_LAB_JUDGE_BASE_URL=http://127.0.0.1:8000/v1
export CAREER_LAB_JUDGE_MODEL='<含 adapter 版本的模型名>'
export CAREER_LAB_JUDGE_MAX_TOKENS=256
```

- 回环地址（127.0.0.1、localhost、::1）可以不配key，此时请求不带Authorization头。服务在别的主机上时必须给本槽配`_KEY_FILE`，否则拒绝启动（`model_slot_key_required`）。
- 没设SUPPORT时，支持核验同样发到这个Judge服务；provenance记录它的provider、model和base_url（只记由槽变量配置的端点，去掉URL中的用户信息、查询串和片段）。

切换与回退：serve与worker必须使用同一组变量，改完两个都重启。worker启动时stderr打印每槽一行`career-lab model slot <SLOT>: provider=… model=… fingerprint=…`，核对后再放流量；serve的stderr只留HTTP白名单日志，不打印这些行。回退时删掉槽变量后重启，即回到共用配置。真实provider适配器零自动重试。

key文件读法：

1. 文件中任何位置（包括`#`注释行里）出现独立的`sk-…`令牌，就用它。
2. 否则取第一个非空、不以`#`开头的行，去掉首尾空白，要求不少于8个字符且不含空白。
3. 紧贴在字母、数字、`_`或`-`后面的`sk-…`（例如`x_sk-abc`）不算独立令牌，按第2条取整行。
4. key不入库、不入日志、不进provenance；报错只给错误码。

### 正常入口浏览器流程（model-flows）

`model-flows`以带注册的独立serve＋worker＋vite preview驱动正常v4入口，中英各走一遍：提交→反馈→模型块（身份、训练数据、逐句结果、证据按钮打开原文、「合成机制演示」）→刷新不重跑（journal条数不变）→改动注册文件后新反馈显示「模型文件或推理环境已变化，需重新核验注册。」。同一业务事实中英逐句结论相同。先在`apps/web`完成`npm ci`与`npm run build`（vite preview读取构建产物）。

```sh
CHROME_BIN=/path/to/chrome-headless-shell uv run --locked python -m scripts.regression.browser \
  --suite model-flows --output /path/to/new-dir
```

默认三段：

| 段 | 注册与配置 | 额外断言 |
|---|---|---|
| `linear` | 关键词构造的线性回传（词表只含业务词、不含数字） | 中英逐句结论相同 |
| `fusion` | 两个关键词线性回传的融合，alpha 0.75 | 左右分量与权重 |
| `slots` | 线性回传＋回环脚本化JUDGE、ASSISTANT槽（模型名`qa-loopback-judge`、`qa-loopback-assistant`） | 助手生成标「模型生成 · 回答待核验」，回环调用记录只来自ASSISTANT槽；反馈区「评价模型：openai_compatible · qa-loopback-judge」 |

可选三段需encoder extra：`encoder`（微型pair_aggregate编码器回传）、`hetero`（线性×微型编码器）、`xlmr`（另需`ROLECRAFT_XLMR_DIR`指向XLM-R下载目录）。

```sh
CHROME_BIN=/path/to/chrome-headless-shell ROLECRAFT_XLMR_DIR='/path/to/xlm-roberta-base/<40 位 revision>' \
  uv run --locked --extra encoder python -m scripts.regression.browser \
  --suite model-flows --output /path/to/new-dir --optional-encoder
```

`--phases`可只跑指定段（例如`--phases linear slots`）；`--api-port`、`--web-port`缺省19662、19660。输出目录须是新目录；截图在`<输出目录>/<段>/screenshots/`，各段结果汇总在`model-flows.json`。所有注册都是`synthetic_fixture`，只证明接收端在正常入口可用，不是模型判断或质量结论。

## 正式回传复核 CLI（2026-10-09）

`verify-return`只读接收负责方的label/evidence回传，不训练、不下载、不执行清单中的生产者命令。数据包须由`dataset-manifest.json`逐文件绑定，支持两种布局；负责方若采用其他布局，须先明确格式，不能按文件名猜测。

- fixture v2可移植布局：`data/dev.inputs.jsonl`、`data/dev.labels.jsonl`、`audit/original-annotations.jsonl`与`audit/metadata.jsonl`。该布局共用一份annotations，只收train/dev：先核manifest和全量metadata分区，再读取标签；含test或未知分区明确拒绝。
- 含封存test的数据包用`rolecraft-dataset-split-sealed-v1`（[按split冻结的数据包](return-v3/dataset-split-sealed-v1.md)）：每个split自带输入、标签、注释与metadata，dev复核只读dev的4个文件，不打开任何test文件；test只能按[封存test一次性打开](#封存test一次性打开)读取。

预测行v2与v3（`return_schema_version=3`、`task_type=relation`）同收；未知`task_type`或缺版本逐条拒绝（[预测行 v3](return-v3/predictions-v3.md)）。

先核对回传格式与分语言指标：

```sh
uv run --locked python -m career_lab.models.v3.registry_cli verify-return \
  --dataset-root /path/to/frozen-dataset \
  --dataset-hash '<dataset-manifest.json 的 SHA-256>' \
  --predictions /path/to/predictions.dev.jsonl
```

再加入[登记一份回传](#登记一份回传)保存的准确引用，执行两次独立重载及逐条比较：

```sh
uv run --locked python -m career_lab.models.v3.registry_cli verify-return \
  --dataset-root /path/to/frozen-dataset \
  --dataset-hash '<固定 dataset manifest SHA-256>' \
  --predictions /path/to/predictions.dev.jsonl \
  --checkpoint-manifest /path/to/checkpoint-manifest.json \
  --registry /path/to/registry \
  --registration-path '<注册返回的相对路径>' \
  --registration-hash '<注册返回的 SHA-256>'
```

融合注册另加`--fusion-selection /path/to/fusion-selection.json`：在dev上按`joint-first-dev-v1`复算全部网格点，与负责方选择记录逐点比较（[预测行 v3 §4](return-v3/predictions-v3.md)）。选中点不同、端点声称收益、注册alpha或收益声明不符、分量身份不符、网格或协议不合规、用了test分区，都判`rejected`。

输入以外层`record_id/input_hash`对齐，标签仍与推理输入分离。接收器拒绝重复JSON键、错误schema版本、概率顺序/形状、选中证据的候选hash错误和test选型；概率和误差上限为`1e-6`；可评的正／反关系成功行必须带证据选择（`return_evidence_selection_required`）。

- 重载比对按概率绝对差容差（线性1e-6、编码器1e-4），标签与证据集合完全一致。报告顶层`tolerance`（未重载时为null），`reload`下有`max_probability_deviation`、`mismatches`与`comparison=probabilities_within_absolute_tolerance_labels_and_evidence_sets_exact`。
- 每语分别报告macro-F1、逐类P/R/F1、混淆、证据F1、联合正确率，另报`counts`（格式失败、弃权、覆盖率）；`evaluation_setting=given_evidence_only`，只评给定证据。label-only从证据与联合分母排除，错误行保留在所属语言的分类分母中。证据F1取可接受集合最大值，额外引用不能得到joint正确。

退出码0表示完成所提供材料的检查，报告仍可能为`partial`，不表示训练或质量通过，也不等于重载已核：只有`reload.status=matched`表示重载逐条一致。无注册引用是`blocked_missing_registration`，缺语言是`blocked_missing_language`；本机缺encoder依赖时，只有合成未训练头注册报`blocked_encoder_runtime_unavailable`，其余注册退出2（`pretrained_encoder_dependencies_unavailable`），见[预测行 v3 §3](return-v3/predictions-v3.md)。格式错误、身份/文件漂移、test污染、回传与模型预测不一致或重载不一致返回非零。原件不改写，原始错误保留。`checkpoint.candidate_eligible`不会仅凭完成声明或任意文件清单变成true；静态声明缺checkpoint验证或训练执行证据时逐项报告待补。训练始终区分`not_verified`与`mechanism_only`。

### 封存test一次性打开

封存test只在模型冻结之后、经用户批准打开一次，只用来报告一次性的test指标；看过的test只能作回归用，不能再参与任何选择。冻结记录由总调度准备（[test打开 §2](return-v3/test-opening-v1.md)）；批准是同一冻结目录里的`campaign.json`，每次打开前由用户在对话里确认（同上§3）。打开：

```sh
uv run --locked python -m career_lab.models.v3.registry_cli verify-return \
  --dataset-root /path/to/dataset-package --dataset-hash '<数据 manifest SHA-256>' \
  --predictions /path/to/predictions.test.jsonl --partition test \
  --checkpoint-manifest /path/to/checkpoint-manifest.json \
  --registry /path/to/registry --registration-path '<注册相对路径>' --registration-hash '<注册 SHA-256>' \
  --freeze /path/to/freeze-dir/freeze.json --freeze-hash '<freeze.json SHA-256>' \
  --campaign /path/to/freeze-dir/campaign.json --campaign-hash '<campaign.json SHA-256>' \
  --operator '<操作者标识>'
```

- 缺批准参数时拒绝（`held_out_test_authorization_required`，403，列出缺项），不留记录、不读test。能事先查出的回传错误（revision对清单与注册、record_id与input_hash、metadata的split、注册在本机能否加载）都在留痕前拒绝，这次打开不会用掉。
- 打开记录以独占创建写在冻结目录`held-out/<数据 manifest sha256>/test.json`，之后才读test的输入与标签；位置只由冻结记录决定，命令行与环境变量都不能改变。报告`held_out_test_opened=true`，`opened`等于这份记录。记录创建后复核失败也保留记录、不重试。
- 同一批准第二次打开在读任何test内容之前拒绝（`held_out_test_already_opened`，403）；换工作目录、设环境变量、经符号链接访问，或把已打开的冻结目录整个拷到别处（记录随之拷走）都同样拒绝。CLI没有确认、强制、重开或换账本参数。

操作规则：

1. 冻结目录只存放一处，只在该处打开；
2. 打开后立即把冻结目录（含`campaign.json`与`held-out/…/test.json`）一并提交进git，由总调度在用户确认后提交；
3. 打开前复制冻结目录、删除或改动打开记录，都属于篡改冻结目录，git历史可以追到。打开之前另存的副本里没有记录，机制本身挡不住它再开一次，这一点由上面三条规则保证。

实跑fixture v2格式样例：英文6条、证据/联合分母5，中文0；样例由gold构造，其满分只说明格式与指标机制。另用既有固定synthetic权重完成真实注册、两次加载及匹配预测，低分类结果和全引文导致的joint零分保留。把格式样例直接与这组权重比较会如实失败。负责方真实checkpoint、训练执行与双语质量仍待交；不因命令可运行关闭真实实验验收。
