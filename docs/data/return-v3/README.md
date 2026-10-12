# RoleCraft 回传格式 v3 补充包

本包写给负责数据、标注与训练的同学，2026-10-12 版。它规定把线性模型、编码器、融合选择和含封存 test 的数据包交回 RoleCraft 时的格式，以及我方收到后怎样登记和复核。冻结交接包 fixture v2 一字节不变（第 9 节），本包只做增量补充。

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
| [dataset-split-sealed-v1.md](dataset-split-sealed-v1.md) | 按 split 冻结的数据包 `rolecraft-dataset-split-sealed-v1`：每个 split 自带文件并逐文件绑定 hash，读 train/dev 不打开 test | 交含 test 的数据包 |
| [test-opening-v1.md](test-opening-v1.md) | 封存 test 的一次性打开：冻结、用户批准、只打开一次、留痕 | 冻结模型、交 test 预测前 |
| [reference/linear_text_v1.py](reference/linear_text_v1.py)、[linear-text-v1.golden.jsonl](linear-text-v1.golden.jsonl) | 线性特征文本 `rolecraft-linear-text-v1` 的参考实现（标准库）与金标 | 拟合 TF-IDF 前 |
| [reference/export_sklearn_linear.py](reference/export_sklearn_linear.py) | 把拟合好的 scikit-learn 对象写成线性回传，并用你方对象写 dev 预测 | 导出线性回传 |
| [reference/export_hf_return.py](reference/export_hf_return.py)、[encoder-pair-aggregate.examples.json](encoder-pair-aggregate.examples.json) | 编码器回传导出（`export`）与外层清单封装（`seal`）；聚合规则样例 | 导出编码器回传 |
| [check_package.py](check_package.py)、`SHA256SUMS`、本页 | 自检与 hash 清单 | 收到后 |

几处取舍：外层清单与预测行沿 fixture v2 模板，v3 只加字段，v2 行照收；融合只需交两个分量和一份 dev 选择记录，融合注册由我方用已登记的分量构建，不必另交融合权重；编码器超过 token 上限时整条如实弃权，产品不截断。

## 3. 我方怎样复核，参考脚本怎么用

我方不运行你方的命令或 Python，清单里的 `load_and_predict_command` 只作参考。我方用自己的加载器登记、重载并逐条比对你方的 `predictions.dev.jsonl`：

- `input_hash`、`model_revision`、状态、标签与证据集合完全一致；
- 概率逐项绝对差：线性不超过 1e-6，编码器不超过 1e-4（融合任一分量是编码器即按 1e-4）；
- dev 全量参与，label-only 记录不进证据与联合分母；只评给定证据的设置，不做含检索的设置。

参考脚本的用途是让你方在自己的环境里写出与我方加载器一致的文件与预测；金标与样例就是我方测试用的同一份，产品函数、参考实现与它们逐条一致：

- **线性**：特征文本必须用 `relation_text`、`pair_text` 生成。在本目录运行 `python3 -B reference/linear_text_v1.py linear-text-v1.golden.jsonl`，每行应为 `ok`。导出用 `export_sklearn_linear.export_linear_return(...)`（用法见脚本开头），它拒绝我方加载器不能精确重建的对象。
- **编码器**：`export_hf_return.py export` 写布局并打印 `model_revision`，dev 预测每行都写它；`seal` 写外层清单。输入文本用 `encoder_inputs`，`pair_aggregate` 的 dev 预测用 `aggregate_pairs`，可用样例文件逐条自测（其中两条低阈值样例应被拒绝）。登记成功不等于能加载：交付前请在第 4 节的版本下自行加载一次并核对 `after_weights`。
- **融合**：按 `joint-first-dev-v1` 在 dev 上选点；我方用已登记的两个分量重算整张 alpha × 阈值网格，逐点、逐项比对你方记录。

## 4. 推理环境

产品在 CPU 上推理。编码器依赖 torch 2.8.0、transformers 4.57.1、tokenizers 0.22.2、safetensors 0.6.2；checkpoint 必须能在这组版本下用 `AutoModel.from_pretrained(..., local_files_only=True, trust_remote_code=False, use_safetensors=True)` 加载。训练环境可以不同；需要别的版本请训练前告知。

参考脚本的依赖：`export_hf_return.py` 需要 Python 3.10+、torch、transformers、numpy、safetensors；`export_sklearn_linear.py` 需要 numpy、scikit-learn；`linear_text_v1.py` 与 `check_package.py` 只用标准库。三个脚本都不依赖 RoleCraft 仓库，也不联网。

## 5. R2.support 的推理单元是作品单句

产品把每份提交作品按 `r2-support-units-v1` 规则切句（空行分段，列表项各成一句，`。！？；!?;` 与英文句末句点为句界，小数与 e.g. 等缩写不切；少于 4 个非空白字符的句子不判，每个证据包最多 24 句）。每句是一条关系输入：claim 为该句，候选材料、用途与时点与整篇相同，作品自身不充当证据。作品级结论由逐句结果保守聚合，任一句矛盾即为矛盾。因此训练与 dev 的 claim 宜包含作品单句，分布才与产品一致。

作品单句的关系记录由我方的授权导出提供（我方执行）：

```sh
python -m career_lab.datasets.v3 export --live <连接参数> --key-file … --authorization … \
  --output <新目录> --relation-units
```

加 `--relation-units` 后，除助手回答的关系记录外，每份提交作品的 R2.support 证据包每句导出一条关系记录：claim 为该句，候选为同一证据包的候选材料（作品自身除外），不带 gold 与 rule_bound，标签需你方标注。模型输入文件 `data/<split>.inputs.jsonl` 的键不变；来源在 `audit/source-map.json` 的每条记录里区分：`relation_source` 为 `work_unit` 或 `assistant_answer`，作品句另有 `unit_policy`、`unit_index`、`unit_hash`，其中 `unit_hash` 与产品反馈里 `model_advice.units[].unit_hash` 逐条相同，可以对回产品里的同一句。导出的句子集合与推理相同：过短的句子和超过每包句数上限的句子不导出。不加该参数时导出与以前相同，只是助手回答记录多了 `relation_source`。

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
- 引用整篇材料时 `pair` 也会超限。我方后续考虑把候选按引用片段或分块传入，尚未决定，定了另行告知。
- 每包 24 句的上限暂不变；部署机若明显更慢，由我方调整这一配置。

## 7. 交付前

- **删去隐藏文件**（如 `.DS_Store`）。编码器回传目录里每个文件都要列进清单、后缀有白名单，多一个文件整份被拒（`checkpoint_member_set_mismatch` 或 `checkpoint_file_type_not_allowed`）；数据包与回传清单经 `validate-handoff` 时同样按文件集合核对（`handoff_file_set_mismatch`、`handoff_model_file_set_mismatch`）。
- 外层清单显式写选择声明 `training_partitions=["train"]`、`selection_partition="dev"`、`test_used_for_selection=false`（编码器的未训练头阶段除外，见编码器规格第 2 节）。
- `dataset_manifest_sha256` 写你方新数据包 `dataset-manifest.json` 的 hash，不要沿用 fixture 的；fixture 数据不能登记成外部候选。
- test 只在模型冻结后预测一次；预测的 `model_revision` 必须与冻结的清单和登记的模型一致，record_id 与 input_hash 恰为封存 test 的记录，否则在打开前就被拒。

## 8. 本次不发布

- **评价项五分类（criterion）的回传格式**：线性与编码器都只收关系任务，criterion 预测行现在会被拒（`return_task_type_unsupported`）。等你方答复五分类走 Judge 还是独立 head 后再定格式（我方后续清单，143 任务书 §8 第 1 项）；若走独立 head，训练前先与我方对格式，标签以 10-09 定稿 rubric 为准。
- **Judge 训练格式（SFT 输入导出）**：若做 SFT，请先向我方索取线上 Judge 的输入格式导出再开始训练（同清单第 2 项）。
- 含检索的评测设置。

## 9. 与 v2 冻结包的关系

- `fixture-20261007-v2/` 与 `RoleCraft-fixture-20261007-v2-r1.zip`（`073e4139…`）一字节不变。
- v2 预测行照收，同一文件可与 v3 行混用；fixture v2 时代的编码器 checkpoint 仍可登记与加载（只限 `pack`、`pair`，证据阈值固定 0.5）。
- v2 可移植布局仍只收 train/dev；含封存 test 的数据包改用 split-sealed 布局。
- fixture 只用来核格式与机制，不是训练数据。
