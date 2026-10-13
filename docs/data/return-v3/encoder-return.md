# 编码器回传 v3 规格（关系三分类＋证据选择）

本页规定负责方把微调好的关系编码器交回 RoleCraft 时的目录、文件与计算方法。按本页交回的回传可以直接登记进产品、在 CPU 上重新加载并进入正常反馈；不按本页的结构，登记时会被明确拒绝，不会「猜着」加载。登记只确认所交文件与声明的身份，不证明训练真实发生，也不代表模型质量；模型建议在产品里一律「模型建议（不计分）」。

- 适用任务：关系三分类 `SUPPORTED / CONTRADICTED / INSUFFICIENT`，必须同时输出证据选择（原稿 §11.2）。评价项五分类（criterion head）本版不发布，待负责方确定路线后另定格式。
- 外层格式沿用冻结交接包 fixture v2 的 `checkpoint-manifest.json` 模板与 `predictions.dev.jsonl` 行格式，不改动 v2；本页只新增 v3 的 checkpoint 内部布局与可选字段。
- 参考实现：[`reference/export_hf_return.py`](reference/export_hf_return.py)（只需 torch、transformers、numpy、safetensors，不依赖本仓库）；聚合规则样例：[`encoder-pair-aggregate.examples.json`](encoder-pair-aggregate.examples.json)。
- 产品推理环境：CPU，torch 2.8.0、transformers 4.57.1、tokenizers 0.22.2、safetensors 0.6.2。训练环境可以不同，但 checkpoint 必须能在这组版本下用 `AutoModel.from_pretrained(..., local_files_only=True, trust_remote_code=False, use_safetensors=True)` 加载；需要别的版本请训练前告知。

## 1. 目录

```
<回传目录>/
  checkpoint-manifest.json     外层清单（§2），列出下面每个文件的 SHA-256
  checkpoint.json              推理设置与身份（§3）
  heads.npz                    分类头与证据头（§4）
  encoder/
    local-files.json           encoder 目录的文件清单（§6）
    config.json                save_pretrained 写出的配置
    model.safetensors          编码器权重（只收 safetensors）
    tokenizer.json 等          分词器文件
  training-notes.md            训练说明（外层清单 training_notes_file）
  predictions.dev.jsonl        dev 逐条预测（外层清单 predictions_file）
```

目录里每个文件（清单本身除外）都必须列在 `checkpoint_files`，多一个、少一个都拒绝。后缀：`encoder/` 下只允许 `.json .safetensors .model .txt .md`，其余位置只允许 `.json .npz .jsonl .md .txt`；不允许符号链接、`pytorch_model.bin`、`.pt`、自定义 Python 代码。`encoder/` 下的实际文件集合必须与 `local-files.json` 完全一致。

交付前删去隐藏文件（如 macOS 的 `.DS_Store`），否则整份回传被拒（`checkpoint_member_set_mismatch` 或 `checkpoint_file_type_not_allowed`）。

## 2. 外层清单 `checkpoint-manifest.json`

字段与 fixture v2 模板相同（`return_protocol=rolecraft-label-evidence-v2`、`task_type=relation`、固定 `label_order`、`dataset_id`、`dataset_manifest_sha256`、`checkpoint_files`、`load_and_predict_command`、`training_notes_file`、`predictions_file` 等）。`checkpoint_files` 列出目录内除清单本身以外的每个文件及其 SHA-256，且只能列这些文件（§1）。

v3 新增的可选字段：

| 字段 | 取值 | 说明 |
|---|---|---|
| `artifact_kind` | `huggingface_encoder` | 写了就必须是这个值 |
| `artifact_protocol` | `rolecraft-encoder-return-v3` | 写了就必须是这个值 |
| `label_tiers` | `G0`、`G1`、`G2`、`G2v` 的子集 | 训练标签的等级，进入注册身份，界面显示为训练数据的一部分 |
| `weights_stage` | `supervised_finetuned`（缺省）或 `pretrained_untrained_heads` | 见 §10 |

按阶段的声明规则（不符即拒绝）：

| 字段 | `supervised_finetuned` | `pretrained_untrained_heads` |
|---|---|---|
| `template` | `false` | `false` |
| `completed` | `true` | `false`（没有训练，不是完成交付） |
| `evidence_selection_implemented`、`evidence_selection_required` | `true` | `true` |
| `training_partitions` | `["train"]` | `[]` |
| `selection_partition` | `"dev"` | `null` |
| `test_used_for_selection` | `false` | `false` |

注册项的训练数据身份 `dataset={dataset_id, dataset_manifest_sha256, label_tiers}` 取自本清单。

## 3. `checkpoint.json`

| 字段 | 要求 |
|---|---|
| `checkpoint_schema_version` | `3` |
| `source_revision` | 底座模型的 40 位 hex revision（例如 Hugging Face 上 `FacebookAI/xlm-roberta-base` 的提交号） |
| `task_type` | `relation` |
| `variant` | `pack`、`pair`、`pair_aggregate`（§5） |
| `pooling` | `mean`（按 attention mask 求平均） |
| `max_tokens` | 整数，≥4，且不超过分词器 `model_max_length` 与 `max_position_embeddings`（XLM-R base 为 512） |
| `evidence_threshold` | 数值，0 < τ < 1；`pair_aggregate` 须 0.5 ≤ τ < 1 |
| `seed` | 整数，加载前 `torch.manual_seed(seed)` |
| `pair_label_order` | 只在 `pair_aggregate`：`["SUPPORTS", "CONTRADICTS", "UNRELATED"]` |
| `model_revision` | §8 公式；必须与外层清单和每行预测一致 |
| `training_report` | `source_revision`、`after_weights`（§7）及训练说明；`supervised_finetuned` 须 `fit_split="train"`、`training_kind` 为非空且不是 `none`；`pretrained_untrained_heads` 须 `training_kind="none"`、不得有 `fit_split` |
| `files` | `heads.npz`、`encoder/local-files.json` 与 `encoder/` 下每个文件的 SHA-256（不含 `checkpoint.json` 自身） |

参考脚本与产品都以规范 JSON 写出（键排序、无空格、UTF-8、末尾换行）；登记不要求这种写法，只按清单 hash 校验。

**旧回传照旧加载**：没有 `checkpoint_schema_version` 的 fixture v2 时代 checkpoint 仍可登记与加载：只允许 `pack`、`pair`，证据阈值固定 0.5，`model_revision="hf-finetuned:<source_revision>:<after_weights>"`，不得出现 v3 才有的字段（`pooling`、`evidence_threshold`、`pair_label_order`）。

## 4. `heads.npz`

numpy `.npz`，`allow_pickle=False` 可读，浮点数组。`d` 为 `encoder/config.json` 的 `hidden_size`。

| variant | 数组与形状 |
|---|---|
| `pack`、`pair` | `relation.weight [3, d]`、`relation.bias [3]`、`selector.weight [1, 2d]`、`selector.bias [1]` |
| `pair_aggregate` | `pair.weight [3, d]`、`pair.bias [3]` |

数组名集合必须恰好如上，形状逐个相符，类型为 float32；多一个、少一个、形状或类型不对都返回 `encoder_architecture_unsupported`。`pair_label_order` 只在 `pair_aggregate` 出现，`pack`、`pair` 带上即拒。参考脚本按名字排序、固定时间戳与属性、不压缩地写出，同一组数组逐字节相同。

## 5. 编码器输入与三种结构

**输入文本 `rolecraft-encoder-text-v1`**（只读 `model_input`，不读标签、gold、规则界）：

```
query  = purpose + "\n" + claim + "\n" + "reference time {as_of.business_seq}; temporal scope {rule_context.evidence_time_context.status，缺省 undetermined}"
body_i = candidate_i.text + "\n" + "observed {ref.observed_at_seq}; valid from {ref.valid_from_seq}; valid until {ref.valid_until_seq，为空写 open}"
```

候选按 `candidate_evidence` 原顺序。参考脚本 `encoder_inputs(model_input)` 给出同一字符串，训练与 dev 预测请直接用它。

| variant | 编码 | 输出 |
|---|---|---|
| `pack` | 一条序列：`tokenizer(query, text_pair=body_1+"\n"+…+body_N+"\n")`，须 fast tokenizer | 全局表示＝整条序列的 mask 平均；候选表示＝第二段中与 body_i 字符区间重叠的 token 的隐藏状态平均；关系概率＝softmax(relation(全局))；证据分数＝sigmoid(selector([候选; 全局])) |
| `pair` | N 条序列 `(query, body_i)`，补齐到最长 | 每条 mask 平均得 p_i；全局＝p_i 的平均；关系与证据同上，候选表示为 p_i |
| `pair_aggregate` | 同 `pair` | 每对 softmax(pair(p_i)) 得 (s_i, c_i, u_i)＝(支持, 矛盾, 无关)，再按下面的规则确定性聚合 |

`pack`、`pair` 的证据集合＝证据分数 ≥ `evidence_threshold` 的候选。

**pair_aggregate 聚合规则（v1）**，τ＝`evidence_threshold`：

0. τ 必须 ≥ 0.5（更低的阈值登记时拒绝 `checkpoint_inference_settings_invalid`）。记支持强度 σ_i＝s_i（若 s_i > u_i）否则 0：支持不胜过无关的一对不算支持。
1. 任一 c_i ≥ τ → `CONTRADICTED`，证据＝所有 c_i ≥ τ 的候选，置信 m＝max c_i，逐候选分数取 c_i。
2. 否则任一 σ_i ≥ τ（即 s_i ≥ τ 且 s_i > u_i）→ `SUPPORTED`，证据＝所有 σ_i ≥ τ 的候选，m＝max σ_i，分数取 σ_i。
3. 否则 → `INSUFFICIENT`，证据为空，m＝1 − max(max s_i, max c_i)，分数取 max(σ_i, c_i)。
4. 关系概率：判定类 (1+m)/2，其余两类各 (1−m)/4（和为 1，判定类严格最大）。

无关永远不会升为支持：支持须过阈值且胜过无关，阈值不低于 0.5；矛盾优先于支持（矛盾与无关持平时仍记矛盾，宁可提醒）。[样例](encoder-pair-aggregate.examples.json)覆盖矛盾优先、支持与无关并存、全部无关、低于阈值、多处矛盾、支持与无关持平、最可能无关的一对、多处支持、矛盾与无关持平、较高阈值，以及两个被拒的低阈值；产品与参考脚本都逐条按样例测试。负责方的 dev 预测必须用同一规则（参考脚本 `aggregate_pairs`）。

## 6. `encoder/local-files.json`

```json
{"protocol": "w08-hf-local-files-v1", "source_revision": "<40 hex>", "weights_stage": "supervised_finetuned", "files": {"config.json": "<sha256>", "model.safetensors": "<sha256>", "tokenizer.json": "<sha256>"}, "derived_from": "<可选 sha256>"}
```

`source_revision` 与 `checkpoint.json` 相同；`weights_stage` 与外层清单声明相同；`files` 列 `encoder/` 下除本文件外的每个文件。`config.json` 必须有正整数 `hidden_size` 与 `model_type`，不得含 `auto_map`（远程代码）；须包含至少一个分词器文件（文件名含 `tokenizer`，或 `vocab.txt`、`sentencepiece.bpe.model`）。微调回传的 encoder 目录须是完整权重（加载时没有缺失参数），参考脚本发现缺失会拒绝导出。

## 7. `after_weights`

SHA-256，依次喂入模块 `("encoder.", 编码器)`，再 `("relation.", relation)`、`("selector.", selector)`（`pair_aggregate` 为 `("pair.", pair)`）。每个模块的 `state_dict()` 按名字排序，逐张量喂：

1. `前缀 + 名字 + str(tensor.dtype) + str(tuple(tensor.shape))` 的 UTF-8 字节（如 `encoder.embeddings.word_embeddings.weighttorch.float32(250002, 768)`）；
2. 张量转 float32、C 连续后的原生（小端）字节。

编码器按 `torch.manual_seed(seed)` 后 `AutoModel.from_pretrained` 的结果计算；产品加载后重算，与 `training_report.after_weights` 不同即拒绝（`checkpoint_parameter_identity_mismatch`）。参考脚本 `after_weights(modules)` 即此定义。

## 8. `model_revision`

```
model_revision = "hf-encoder-v3:" + sha256(canonical_json({
  "after_weights", "evidence_threshold", "max_tokens", "pooling",
  "source_revision", "task_type", "variant", "weights_stage"
}))
canonical_json = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
```

权重、阈值、上限、结构或阶段任何一项变化都会得到新的 revision。样例：`after_weights="c"*64, evidence_threshold=0.5, max_tokens=256, pooling="mean", source_revision="a"*40, task_type="relation", variant="pair_aggregate", weights_stage="supervised_finetuned"` → `hf-encoder-v3:1b5a82c83e864c135fa05fc149f50ef04e26f26cc24ad2d6bab38e160dfddc4f`。参考脚本 `export` 会打印本次的 revision，dev 预测每行的 `model_revision` 都要写它。

## 9. 阈值与上限怎样生效

- `evidence_threshold`：§5 的证据集合与聚合都用它；产品不再使用固定 0.5（旧布局除外）。
- `max_tokens`：按实际编码长度（`pair` 类为补齐后的最长一条）比较；超过即该条弃权 `encoder_input_truncated`，**不截断**。产品的 `measure()` 只分词、不前向，给出同一长度，供按句切分时先判断。

## 10. 权重阶段

| `weights_stage` | 含义 | 登记 |
|---|---|---|
| `supervised_finetuned` | 编码器与头都经训练（负责方的正式交付） | `synthetic_fixture` 或 `external_candidate`；fixture 数据不能登记成 external |
| `pretrained_untrained_heads` | 预训练底座、头按 `seed` 初始化未训练 | 只许 `synthetic_fixture`，否则 `untrained_heads_require_synthetic_scope`；用于我方接收端冒烟，界面只作「合成机制演示」 |

只有声明了 `pretrained_untrained_heads` 的 checkpoint 才允许未训练头预测；公开注册身份带 `weights_stage`。

## 11. 登记、依赖锁与协议

- 登记只做不需要 torch 的检查（文件、hash、清单、设置、头的名字形状类型、架构声明）；`after_weights` 要到加载时重算。**登记成功不等于能加载**：交付前请在锁定版本下用 `AutoModel.from_pretrained` 加头自行加载一次并核对 `after_weights`。
- 登记命令：`python -m career_lab.models.v3.registry_cli register --registry <目录> --bundle-root <回传目录> --bundle-path checkpoint-manifest.json --bundle-hash <清单 SHA-256> --scope external_candidate|synthetic_fixture`。登记复制所钉文件、不执行清单里的任何命令或代码。
- 注册协议 `advisory-encoder-registration-v2`：注册项记录 torch、transformers、tokenizers、safetensors 的已安装版本（读包元数据，不导入 torch）。登记环境缺任一包 → `encoder_runtime_unavailable`；加载或描述时版本不同 → `registered_inference_runtime_changed`；加载时缺包 → `pretrained_encoder_dependencies_unavailable`。
- 注册项公开身份：`id`、`model_revision`、`scope`、`kind=huggingface_encoder`、`dataset`、`weights_stage`，以及 `quality_validated=false`；另记 `variant`、`evidence_threshold`、`max_tokens`。
- 旧协议 `advisory-encoder-registration-v1` 的注册不再产生新建议（`encoder_registration_retired`）；用它产生过的反馈照原样可读。同一回传重新登记即得到 v2 注册。

## 12. 参考脚本

```sh
# 1. 微调回传：encoder 目录（save_pretrained 输出）＋头 state_dict（.pt/.safetensors/.npz）＋训练报告 JSON
python export_hf_return.py export --encoder-dir ENC --heads heads.pt --training-report report.json \
  --variant pair --source-revision <底座 40 位 revision> --max-tokens 256 --evidence-threshold 0.5 --out RETURN
# 2. 用打印出的 model_revision 写 dev 预测（fixture v2 行格式），放入 RETURN/predictions.dev.jsonl，并写 RETURN/training-notes.md
# 3. 生成外层清单
python export_hf_return.py seal --root RETURN --dataset-manifest dataset-manifest.json --label-tier G2v
```

头 state_dict 的键与 §4 数组名相同（如 `relation.weight`）。`--weights-stage pretrained_untrained_heads` 时不给头与报告，头由 `--seed` 初始化、encoder 按加载结果重新保存。脚本拒绝缺参数的 encoder 目录、非 safetensors 权重、键不符的头、与交付权重不一致的报告。

## 13. 拒绝码

登记（`register`）时：

| 码 | 含义 |
|---|---|
| `encoder_runtime_unavailable` | 登记环境缺 torch、transformers、tokenizers、safetensors 中任一包（§11） |
| `file_missing`、`file_outside_root`、`file_hash_mismatch` | 文件不存在、越出回传目录、SHA-256 与清单不符 |
| `model_return_protocol_invalid` | `return_protocol` 不是 `rolecraft-label-evidence-v2`，或 `artifact_kind`／`artifact_protocol` 写的不是编码器（线性、融合回传走各自的登记） |
| `model_return_task_or_labels_invalid` | 外层清单或 `checkpoint.json` 的任务不是 relation；标签顺序或 `pair_label_order` 不符 |
| `model_return_weights_stage_invalid` | 外层清单 `weights_stage` 不是 §10 的两个值之一 |
| `untrained_heads_require_synthetic_scope`、`untrained_heads_declaration_invalid` | 未训练头登记成 external；未训练头的声明不如实（§2） |
| `model_return_incomplete`、`model_return_selection_contaminated` | 沿 fixture v2：模板、未完成或未实现证据选择；训练不只用 train、选择不只用 dev 或用了 test |
| `model_return_identity_incomplete` | 模型版本、框架、数据集、命令、训练说明、预测文件名等身份字段为空 |
| `model_return_dataset_identity_invalid` | `dataset_manifest_sha256` 不是 64 位 hex，或 `label_tiers` 不是 G0／G1／G2／G2v 的子集 |
| `fixture_cannot_be_registered_as_external` | 数据集是 fixture，却要登记成 external |
| `checkpoint_files_required`、`checkpoint_path_not_canonical`、`checkpoint_manifest_self_reference` | `checkpoint_files` 为空、路径不规范、列了清单本身 |
| `checkpoint_member_set_mismatch` | 目录实际文件、`checkpoint_files`、`checkpoint.json` 的 `files` 三者不一致 |
| `checkpoint_file_type_not_allowed` | 文件后缀不在 §1 的白名单 |
| `checkpoint_files_incomplete`、`checkpoint_metadata_invalid` | 缺 `checkpoint.json`、`heads.npz` 或 `encoder/local-files.json`；JSON 不是对象 |
| `checkpoint_manifest_disagreement` | 外层清单、`checkpoint.json`、`local-files.json` 对同一文件给出不同 hash |
| `checkpoint_schema_version_required`／`checkpoint_schema_version_unsupported` | 无版本号却有 v3 字段／版本号不是 3 |
| `encoder_architecture_unsupported` | variant／pooling 不在支持集；`pack`、`pair` 带了 `pair_label_order`；头数组名、形状或类型（非 float32）不符；config 无 `hidden_size`、无 `model_type` 或要求远程代码；旧布局用了 `pair_aggregate` |
| `checkpoint_inference_settings_invalid` | 阈值不在 (0,1)（`pair_aggregate` 低于 0.5）、上限 <4、seed 非整数 |
| `local_checkpoint_revision_or_stage_invalid` | `local-files.json` 的协议、revision 或阶段与 checkpoint／清单不一致 |
| `checkpoint_training_identity_mismatch` | 训练报告与阶段不符，或 `model_revision` 不符合 §8 |
| `checkpoint_model_identity_mismatch` | `checkpoint.json` 与外层清单的 `model_revision` 不同 |
| `checkpoint_tokenizer_missing` | `encoder/` 下没有分词器文件 |
| `local_checkpoint_files_incomplete`、`local_checkpoint_member_set_mismatch` | `encoder/` 缺 `config.json` 或 safetensors；实际文件与 `local-files.json` 不一致 |
| `checkpoint_symlink_not_allowed` | 回传里有符号链接 |
| `tokenizer_capacity_exceeded` | `max_tokens` 超过分词器或位置上限 |
| `checkpoint_heads_invalid` | `heads.npz` 读不出或含非有限值 |

加载与预测时：

| 码 | 含义 |
|---|---|
| `checkpoint_parameter_identity_mismatch` | 重算的 `after_weights` 与训练报告不同（例如头不是 float32 原值、encoder 缺参数） |
| `pretrained_encoder_dependencies_unavailable` | 服务环境缺 encoder 依赖 |
| `registered_inference_runtime_changed` | 依赖版本或推理源码与登记时不同（§11） |
| `encoder_registration_retired` | v1 注册，不再产生新建议（§11） |

预测期逐条弃权（该条记 `status=abstained`，原因为下列码，不出概率与标签；其余记录照常预测）：

| 码 | 含义 |
|---|---|
| `encoder_input_truncated` | 编码长度超过 `max_tokens`（§9） |
| `evidence_span_missing_or_truncated` | `pack`：某个候选在编码后的第二段里没有对应的 token，取不到候选表示 |
| `pack_evidence_spans_require_fast_tokenizer` | `pack`：分词器不是 fast tokenizer，无法按字符区间取候选表示（§5）；产品按 `use_fast=True` 加载，回传带 `tokenizer.json` 时得到 fast tokenizer |

运维类／注册目录内部（由我方的注册目录与登记操作触发，负责方的回传不会单独触发，列出供排查）：

| 码 | 含义 |
|---|---|
| `registration_scope_required` | 登记时 `--scope` 不是 `synthetic_fixture` 或 `external_candidate` |
| `model_registration_busy` | 同一注册正在另一进程发布 |
| `model_registration_drift` | 注册目录里已有同 id 的注册但内容不同，或复制进注册目录的文件与登记时核过的不一致 |
| `model_registration_protocol_invalid` | 加载时注册项的协议或 scope 不认识 |
| `model_registration_identity_mismatch` | 加载时注册 id、注册文件路径与注册内容不符 |
| `registered_model_identity_mismatch` | 加载时已登记副本与注册项记录不符（重核的文件身份，或加载出的 `model_revision`、任务与注册项不同） |

## 14. 本版不支持

评价项五分类 head（待路线确定）；CLS 或其他池化、多层 MLP 头、非 safetensors 权重、远程代码；含检索的设置。需要其他结构请训练前商定，否则登记返回 `encoder_architecture_unsupported`。
