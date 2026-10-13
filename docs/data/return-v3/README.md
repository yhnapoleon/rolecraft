# RoleCraft 回传格式 v3 补充包

这个包规定把训练好的模型、预测与含封存 test 的数据包交回 RoleCraft 时的文件格式，附参考导出脚本、金标样例与自检脚本，是你方已有的 fixture v2 交接包的增量补充。先读本页第 2 节的表，按你要交的东西（线性、编码器、融合、含 test 的数据包）找到对应规格；不论交哪种都要读 [predictions-v3.md](predictions-v3.md)。收到后在本目录运行 `python3 -I check_package.py`，输出 `"status": "ok"` 即包完整无多余文件（第 1 节）。相对 v2，本包有三处收紧，请先读[第 10 节](#10-相对-v2-的三处收紧请确认)并确认。

本包写给负责数据、标注与训练的同学，2026-10-13 版。它规定把线性模型、编码器、融合选择和含封存 test 的数据包交回 RoleCraft 时的格式，以及我方收到后怎样登记和复核。冻结交接包 fixture v2 一字节不变（第 9 节）；本包在它之上补充格式，其中复核方式、线性证据头与编码器结构三处比 v2 收紧（第 10 节）。

登记与复核只确认文件、声明的身份和预测能否复现，不证明训练真实发生，也不代表模型质量。产品里的模型输出一律显示为「模型建议（不计分）」；合成或未训练权重的登记只作「合成机制演示」。

## 1. 收到后先自检

```sh
python3 -I check_package.py <本目录>        # 不给目录时检查脚本所在目录
```

只用 Python 标准库（3.9 及以上），只读文件，不导入、不运行包内任何代码。输出一份 JSON 摘要：全部通过时 `status=ok`、退出码 0；否则 `status=failed`、退出码 1，`errors` 逐条列出问题与路径。规则：

1. `SHA256SUMS` 每行为 64 位小写 hex、两个空格、相对路径（`sha256sum`／`shasum -a 256` 的文本格式），路径用 `/`，不能含 `.`、`..` 或空段，不重复，不列它自己。
2. 清单里的每个文件都存在、是普通文件、SHA-256 相符（`file_missing`、`file_hash_mismatch`）。
3. **清单外不允许任何文件**。只有 `SHA256SUMS` 本身不在清单里（它无法包含自己的 hash）；`check_package.py` 与本页都在清单里，改动它们同样报 hash 不符。隐藏文件（如 macOS 的 `.DS_Store`）、`__pycache__`、编辑器备份都算多余文件（`unlisted_file`）；任何位置的符号链接都拒绝（`symlink_not_allowed`）；空目录不查。
4. 清单里的 `.json` 文件与 `.jsonl` 的每一行都能解析：UTF-8、无 NaN／Infinity、无重复键（`json_invalid`）。

也可以用 `shasum -a 256 -c SHA256SUMS`（或 `sha256sum -c SHA256SUMS`）独立核对 hash，但这两个命令不查多余文件。`SHA256SUMS` 自身的 hash 以我方发送时另给的为准。

在本目录里导入参考脚本（例如 `export_sklearn_linear.py` 会导入同目录的 `linear_text_v1.py`）会生成 `reference/__pycache__/`，之后自检会报多余文件。请先自检，再把参考脚本复制到训练工程里使用，或用 `python3 -B` 运行。

## 2. 包里有什么

| 文件 | 解决什么 | 什么时候读 |
|---|---|---|
| [linear-return.md](linear-return.md) | 线性回传 `rolecraft-linear-return-v1`：TF-IDF＋逻辑回归（关系三分类与证据头）的目录、`linear/model.json`、`linear/arrays.npz`、`model_revision` 公式与拒绝码 | 交线性模型 |
| [encoder-return.md](encoder-return.md) | 编码器回传 v3：`checkpoint.json`＋`heads.npz`＋`encoder/`，`pack`／`pair`／`pair_aggregate` 三种结构，`after_weights` 与 `model_revision` 公式，权重阶段与拒绝码 | 交编码器 |
| [fusion-selection.md](fusion-selection.md) | 融合选择记录 `rolecraft-fusion-selection-v1` 与 dev 选点规则 `joint-first-dev-v1` | 交融合 |
| [predictions-v3.md](predictions-v3.md) | 预测行 v3（`return_schema_version=3`）与回传复核 `verify-return`：格式、分语言指标、重载容差、融合选择复算 | 每种回传都读 |
| [dataset-split-sealed-v1.md](dataset-split-sealed-v1.md) | 按 split 冻结的数据包 `rolecraft-dataset-split-sealed-v1`：每个 split 自带文件并逐文件绑定 hash，读 train/dev 不打开 test；metadata 字段、逐条审阅规则与 `validate-handoff` 的调用、退出码 | 交含 test 的数据包 |
| [test-opening-v1.md](test-opening-v1.md) | 封存 test 的一次性打开：冻结、用户批准、每个候选一个冻结目录只打开一次、留痕；你方要交的训练说明 `freeze-record.json` 与我方生成的冻结记录 `freeze.json` 的字段 | 冻结模型、交 test 预测前 |
| [reference/linear_text_v1.py](reference/linear_text_v1.py)、[linear-text-v1.golden.jsonl](linear-text-v1.golden.jsonl) | 线性特征文本 `rolecraft-linear-text-v1` 的参考实现（标准库）与金标 | 拟合 TF-IDF 前 |
| [reference/export_sklearn_linear.py](reference/export_sklearn_linear.py) | 把拟合好的 scikit-learn 对象写成线性回传、写训练说明模板，并用你方对象写 dev 预测；冻结后用 `write_predictions` 写 test 预测 | 导出线性回传、写 test 预测 |
| [reference/export_hf_return.py](reference/export_hf_return.py)、[encoder-pair-aggregate.examples.json](encoder-pair-aggregate.examples.json) | 编码器回传导出（`export`）、按我方加载器同一规则的参考推理（`predict`，dev 与 test 预测都用它）与外层清单封装（`seal`，含 `artifact_roles`）；聚合规则样例 | 导出编码器回传、写预测 |
| [check_package.py](check_package.py)、`SHA256SUMS`、本页 | 自检与 hash 清单 | 收到后 |

几处取舍：外层清单与预测行沿 fixture v2 模板，v3 只加字段，v2 行照收；融合只需交两个分量和一份 dev 选择记录，融合注册由我方用已登记的分量构建，不必另交融合权重；编码器超过 token 上限时整条如实弃权，产品不截断。

## 3. 我方怎样复核，参考脚本怎么用

我方不运行你方的命令或 Python，清单里的 `load_and_predict_command` 只作参考。我方用自己的加载器登记、重载并逐条比对你方的 `predictions.dev.jsonl`：

- `input_hash`、`model_revision`、状态、标签与证据集合完全一致；
- 概率逐项绝对差：线性不超过 1e-6，编码器不超过 1e-4（融合任一分量是编码器即按 1e-4）；
- dev 全量参与，label-only 记录不进证据与联合分母；只评给定证据的设置，不做含检索的设置。

参考脚本的用途是让你方在自己的环境里写出与我方加载器一致的文件与预测；金标与样例就是我方测试用的同一份，产品函数、参考实现与它们逐条一致：

- **线性**：特征文本必须用 `relation_text`、`pair_text` 生成。在本目录运行 `python3 -B reference/linear_text_v1.py linear-text-v1.golden.jsonl`，每行应为 `ok`。导出用 `export_sklearn_linear.export_linear_return(...)`（用法见脚本开头），它拒绝我方加载器不能精确重建的对象，并写出训练说明模板（交付前填写）；冻结后用 `write_predictions(...)` 写 test 预测，格式与 dev 相同。
- **编码器**：`export_hf_return.py export` 写布局并打印 `model_revision`（`--max-tokens` 缺省 512）；`predict` 按我方加载器的同一规则写 dev 或 test 预测行：弃权条件（输入不完整、claim 为空、时点或有效期未定、无候选、超过 token 上限）、mean pooling、`pair_aggregate` 聚合与证据阈值都相同，加 `--labels` 还会列出会被我方格式检查拒绝的行；`seal` 写外层清单（含 `artifact_roles`）。`predict` 加载时重算 `after_weights`，对不上即停。聚合规则可用样例文件逐条自测（其中两条低阈值样例应被拒绝）。
- **自查边界**：fixture v2 包里的 `validate_predictions.py` 只收版本 2 的行、只核 fixture 自带的数据，不能用于新数据或 v3 行。新数据上请用上面的参考推理写行；最终以我方 `verify-return` 为准。
- **融合**：按 `joint-first-dev-v1` 在 dev 上选点；我方用已登记的两个分量重算整张 alpha × 阈值网格，逐点、逐项比对你方记录。

## 4. 推理环境

产品在 CPU 上、float32 推理。编码器依赖 torch 2.8.0、transformers 4.57.1、tokenizers 0.22.2、safetensors 0.6.2；checkpoint 必须能在这组版本下用 `AutoModel.from_pretrained(..., local_files_only=True, trust_remote_code=False, use_safetensors=True)` 加载。训练环境可以不同（版本、GPU 都可以），**但 `export_hf_return.py export` 与 `predict` 必须在这组版本下、在 CPU 上运行**：`after_weights` 在导出环境里算，预测概率按 1e-4 比对。两个命令都输出 `runtime.matches_product`，不一致时告警。需要别的版本请训练前告知。

参考脚本的依赖：`export_hf_return.py` 需要 Python 3.10+、torch、transformers、numpy、safetensors；`export_sklearn_linear.py` 需要 numpy、scikit-learn；`linear_text_v1.py` 与 `check_package.py` 只用标准库。三个脚本都不依赖 RoleCraft 仓库，也不联网。

## 5. R2.support 的推理单元是作品单句

产品把每份提交作品按 `r2-support-units-v1` 规则切句（空行分段，列表项各成一句，`。！？；!?;` 与英文句末句点为句界，小数与 e.g. 等缩写不切；少于 4 个非空白字符的句子不判，每个证据包最多 24 句）。每句是一条关系输入：claim 为该句，候选材料、用途与时点与整篇相同，作品自身不充当证据。作品级结论由逐句结果保守聚合，任一句矛盾即为矛盾。因此训练与 dev 的 claim 宜包含作品单句，分布才与产品一致。

作品单句的关系记录由我方的授权导出提供（我方执行）：

```sh
python -m career_lab.datasets.v3 export --live <连接参数> --key-file … --authorization … \
  --output <新目录> --relation-units
```

加 `--relation-units` 后，除助手回答的关系记录外，每份提交作品的 R2.support 证据包每句导出一条关系记录：claim 为该句，候选为同一证据包的候选材料（作品自身除外），不带 gold 与 rule_bound，标签需你方标注。模型输入文件 `data/<split>.inputs.jsonl` 的键不变；来源在 `audit/source-map.json` 的每条记录里区分：`relation_source` 为 `work_unit` 或 `assistant_answer`，作品句另有 `unit_policy`、`unit_index`、`unit_hash`，其中 `unit_hash` 与产品反馈里 `model_advice.units[].unit_hash` 逐条相同，可以对回产品里的同一句。导出的句子集合与推理相同：过短的句子和超过每包句数上限的句子不导出。不加该参数时导出与以前相同（source-map 条目的键集合不变，`relation_source` 只在加参数时写）。

## 6. 候选材料长度与 512 上限（我方实测，非质量证据）

以下数字来自我方在 Apple Silicon CPU 上用 `FacebookAI/xlm-roberta-base` 预训练权重、分类头未训练（`pretrained_untrained_heads`，合成登记）做的接收端冒烟，只说明长度与耗时的机制，不是质量或训练证据。

| 情形 | 变体 | 编码长度（token） | 结果 |
|---|---|---|---|
| 冒烟样例的作品句，中文／英文 | pair | 140–156／170–194 | 未超 512 |
| 正常入口的默认候选 | pair | 391–474 | 未超 512 |
| 引用整篇材料 | pair（每对） | 529–578 | 全部超 512，如实弃权 |
| 引用整篇材料 | pack | 1317–1532 | 全部弃权 |
| 引用 8 个片段 | pack | 622–700 | 全部弃权 |
| 正常入口，测试用微型编码器（上限 256） | pair_aggregate | — | 全部弃权 |

耗时：加载约 2.3–4 秒，峰值内存（RSS）约 2.6–3.2 GB；每句 p50，pair 3 个候选 0.12–0.16 秒、8 个候选 0.26–0.31 秒，pack 3 个候选 0.08–0.09 秒；一次评审首次（含加载）2.8–4.8 秒，第二次（缓存命中）1.4–3.3 秒。按每包 24 句、pair 8 个候选每句 p95 约 0.34 秒，一个证据包约 8 秒。

对你方的含义：

- `pack` 把全部候选拼成一条序列，候选一多或引用整篇材料就超限；`pair`／`pair_aggregate` 每对只含 claim 与一个候选，建议优先选用。`max_tokens` 最多 512（XLM-R base 的位置上限）。
- 引用整篇材料时 `pair` 也会超限。推理单元为作品单句，候选材料长度上限与分块方式待双方确认。
- 每包 24 句的上限暂不变；部署机若明显更慢，由我方调整这一配置。

## 7. 交付前

- **删去隐藏文件**（如 `.DS_Store`）。编码器回传目录里每个文件都要列进清单、后缀有白名单，多一个文件整份被拒（`checkpoint_member_set_mismatch` 或 `checkpoint_file_type_not_allowed`）；数据包与回传清单经 `validate-handoff` 时同样按文件集合核对（`handoff_file_set_mismatch`、`handoff_model_file_set_mismatch`）。
- 外层清单显式写选择声明 `training_partitions=["train"]`、`selection_partition="dev"`、`test_used_for_selection=false`（编码器的未训练头阶段除外，见编码器规格第 2 节）。
- `dataset_manifest_sha256` 写你方新数据包 `dataset-manifest.json` 的 hash，不要沿用 fixture 的；fixture 数据不能登记成外部候选。
- test 只在模型冻结后预测一次；预测的 `model_revision` 必须与冻结的清单和登记的模型一致，record_id 与 input_hash 恰为封存 test 的记录，否则在打开前就被拒。`predictions.test.jsonl` 放在回传目录之外。每个候选（线性、编码器、融合）各打开一次，全部候选的 test 预测在第一次打开前一次交齐；融合另交一份声明清单（[test 打开](test-opening-v1.md)第 2.3、3.1 节）。
- 编码器 `max_tokens` 用 512：按第 6 节实测，正常入口一句作品 pair 391–474 token，用 256 会全部弃权。

## 8. 本次不发布，等你方决定后再做

以下三项要等你方的路线选择，本包都不包含；你方答复后，我方再补对应的接收工作。

1. **评价项五分类（criterion）的接收**：线性与编码器回传现在都只收关系任务，criterion 预测行会被拒（`return_task_type_unsupported`）。请答复五分类走 Judge 还是训练独立的 head。若走独立 head，训练前先与我方对齐回传格式，标签以 2026-10-09 定稿的 14 项评价标准为准；我方随后补 criterion 的注册、分语言复核与预测行格式，反馈页逐项显示「模型建议（不计分）」。
2. **Judge SFT 的训练输入格式**：若做 SFT，请先向我方索取线上 Judge 实际输入格式的导出，拿到后再开始训练，以免训练输入与产品推理不一致。训练好的模型以 OpenAI 兼容接口（如 vLLM）提供服务，我方在 Judge 槽配置地址与模型名即可接入。
3. **GRPO**：是否执行由你方决定。我方没有额外的接收工作，接入方式与 SFT 相同；若未执行，报告如实写「未执行」。

含检索的评测设置本次也不发布。

## 9. 与 v2 冻结包的关系

- `fixture-20261007-v2/` 与 `RoleCraft-fixture-20261007-v2-r1.zip`（`073e4139…`）一字节不变。
- v2 预测行照收，同一文件可与 v3 行混用；fixture v2 时代的编码器 checkpoint 仍可登记与加载（只限 `pack`、`pair`，证据阈值固定 0.5）。
- v2 可移植布局仍只收 train/dev；含封存 test 的数据包改用 split-sealed 布局。
- fixture 只用来核格式与机制，不是训练数据。

## 10. 相对 v2 的三处收紧（请确认）

fixture v2 包与准备事项 v2 的大部分约定照旧：v2、v3 预测行混收；fixture 数据不能登记成外部候选；不沿用 fixture 的数据 hash；test 在冻结后只打开一次（现在写明为每个候选各一次）。下面三处比 v2 收紧，请确认可以接受；需要别的做法请在训练前告知。

1. **复核方式**：准备事项 v2 写的是按回传命令重新加载、交回推理代码。v3 改为**我方不运行你方的命令或 Python**，用我方加载器按公开格式重载，逐条比对你方预测（标签、状态、证据集合完全一致，概率差线性不超过 1e-6、编码器不超过 1e-4）。因此回传只收白名单里的数据文件：编码器目录不能放 `.py`、`pytorch_model.bin`、`.pt`，线性只收 `linear/model.json` 与无 pickle 的 `linear/arrays.npz`。推理代码可以写进训练说明供追溯，但不会被执行；参考推理（`predict`、`write_predictions`）给出与我方加载器一致的写法。
2. **线性证据头必填**：v2 允许把只做三分类的 LR 当作基线另报。v3 的线性回传缺证据头即拒绝（`linear_return_evidence_head_required`）。纯分类 LR 仍可以作为离线基线写进你方报告，但不登记、不进产品。
3. **编码器结构、阈值、依赖版本限定，融合选点规则内置**：v2 README 写的是整包分类头加多标签证据头、或逐条判断后确定性聚合，方法由接手者选择。v3 只收 mean pooling 上的线性头，结构限 `pack`、`pair`、`pair_aggregate` 三种；`pair_aggregate` 的聚合规则固定、阈值不低于 0.5；`max_tokens` 缺省 512，不得超过所用 tokenizer 的上限（XLM-R base 为 512），超长如实弃权、不截断；推理依赖锁定 torch 2.8.0、transformers 4.57.1、tokenizers 0.22.2、safetensors 0.6.2；融合必须按 `joint-first-dev-v1` 在 dev 上选点（v2 未规定），证据必选的资格规则内置在我方复算里。
