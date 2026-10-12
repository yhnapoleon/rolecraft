# 预测行 v3 与回传复核

`verify-return` 独立复核负责方交回的关系预测：格式、分语言指标、按注册重载后的逐条比对，以及融合选择的 dev 复算。不训练、不下载、不执行清单里的命令；只评给定证据设置，不做含检索的设置。

## 1. 预测行

v3 行与 fixture v2 行字段相同，只把版本写成 3：

```json
{"return_schema_version": 3, "record_id": "…", "input_hash": "<外层 input_hash>",
 "model_revision": "…", "task_type": "relation", "status": "ok",
 "probabilities": [0.7, 0.2, 0.1], "label": "SUPPORTED",
 "evidence_ids": ["e1"], "evidence_bindings": [{"candidate_id": "e1", "candidate_sha256": "…"}],
 "reason": null}
```

- 同一文件可以混用 v2 与 v3 行，解析结果相同；全文件只能有一个 `model_revision`。
- 每行逐条报格式错误，错误行仍计入所属语言的分类分母：缺 `return_schema_version` → `return_schema_version_required`；版本不是整数 2 或 3 → `return_schema_version_unsupported`；`task_type` 不是 `relation`（含 `criterion`，本版不收）→ `return_task_type_unsupported`；其余规则同 fixture v2（概率 3 维有限、和为 1 的误差不超过 1e-6、标签为最大概率项、证据绑定当前记录候选的完整对象 hash、可评的支持／矛盾成功行不能空证据、失败或弃权不带概率与标签）。
- `validate-handoff --checkpoint-manifest` 的回传核对同样接受 v2 与 v3 行；外层清单可带 v3 字段 `artifact_kind`、`artifact_protocol`、`label_tiers`（不认识的键仍拒绝）。`artifact_kind=linear` 时角色由格式固定：checkpoint＝`linear/arrays.npz`，config 与 tokenizer＝`linear/model.json`，`checkpoint_files` 必须恰为这两项、`artifact_protocol` 必须为 `rolecraft-linear-return-v1`，负责方不必写 `artifact_roles`（写了就必须与固定映射相同，否则 `handoff_model_artifact_roles_conflict`）；其他回传仍须用 `artifact_roles` 列出三种角色。`label_tiers` 只能是 `G0`、`G1`、`G2`、`G2v` 的不重复子集（`handoff_model_label_tiers_invalid`）。

## 2. 报告

沿用既有字段，另加：

| 字段 | 内容 |
|---|---|
| `task_type` | `relation` |
| `layout`、`split` | 数据包布局与所评分区 |
| `evaluation_setting`、`retrieval_setting` | `given_evidence_only`、`not_evaluated` |
| `languages.<zh|en>.counts` | `format_failures`、`abstentions`、`coverage`；该语言没有记录时 `status=blocked_missing_language` |
| `tolerance` | 重载比对所用容差（见下）；无注册、或因格式错误未做重载时为 `null` |
| `reload.mismatches`、`reload.max_probability_deviation` | 每条不符记录及其不符字段；全部比对记录中概率的最大绝对差 |
| `fusion_selection` | 融合选择复算结果，未给记录时为 `null` |
| `opened`、`held_out_test_opened` | test 打开记录与 `true`；dev 复核为 `null` 与 `false` |

`scope` 在数据包是 fixture／合成样例或注册为 `synthetic_fixture` 时写 `synthetic_fixture`；`quality_validated` 恒为 false。

## 3. 重载比对与容差

给出注册引用时，我方用自己的加载器把注册模型加载两次，逐条与回传比较（负责方命令只作参考，不执行）：

- `input_hash`、`model_revision`、`task_type`、`status`、`label` 完全相同；证据集合完全相同；
- 概率同为空，或逐项绝对差不超过容差：线性 1e-6，编码器 1e-4。按实际加载的模型种类定：模型或融合任一分量是编码器（`huggingface_encoder`、`numpy_attention`）用 1e-4，其余用 1e-6（未知种类按严格档）。

任一条不符即 `reload.status=producer_mismatch`，报告 `rejected`、退出码 2；在容差内的概率差只记进 `max_probability_deviation`。`reload.comparison` 取值为 `probabilities_within_absolute_tolerance_labels_and_evidence_sets_exact`（旧版为逐位相等的 `exact_probabilities_labels_and_evidence_sets`）。

负责方清单的选择声明须为 `training_partitions=["train"]`、`selection_partition="dev"`、`test_used_for_selection=false`。唯一例外：注册为 `synthetic_fixture` 且 `weights_stage=pretrained_untrained_heads`（编码器回传的「预训练权重、头未训练」阶段）时，清单必须写 `weights_stage=pretrained_untrained_heads`（否则 `return_checkpoint_identity_mismatch`），并由编码器回传规格的同一检查（`validate_encoder_return_identity`）核对：`completed=false`、`training_partitions=[]`、`selection_partition=null`、`test_used_for_selection=false`，不符为 `untrained_heads_declaration_invalid`；报告 `checkpoint.status=untrained_heads_declared`。其他注册与不给注册时，这样的清单照旧判 `model_return_selection_contaminated`。

本机没有编码器可选依赖时：只有注册为 `synthetic_fixture` 的未训练头机制样例，dev 复核照常给出格式与指标，并报 `reload.status=blocked_encoder_runtime_unavailable`、`tolerance=null`；external 或任何已训练的编码器注册照旧报 `pretrained_encoder_dependencies_unavailable`、退出 2；test 打开在留痕前就因此拒绝。**退出 0 不等于重载已核**：看 `reload.status`，只有 `matched` 表示重载逐条一致；`blocked_*` 只对合成的未训练头出现。

## 4. 融合选择复算（`--fusion-selection`）

```sh
uv run --locked python -m career_lab.models.v3.registry_cli verify-return \
  --dataset-root <数据包> --dataset-hash <manifest SHA-256> \
  --predictions <融合的 dev 逐条预测> \
  --registry <注册目录> --registration-path <融合注册路径> --registration-hash <融合注册 SHA-256> \
  --fusion-selection <rolecraft-fusion-selection-v1 记录>
```

记录格式见[融合选择记录](fusion-selection.md)。只收 dev（`fusion_selection_dev_only`），必须给融合注册（`fusion_selection_requires_registration`、`fusion_selection_requires_fusion_registration`）。我方用注册里的两个分量在 dev 上按产品同一融合公式与同一选择规则重算整张 alpha × 阈值网格，然后逐项比对：

- **选择规则 `joint-first-dev-v1`**：只在联合正确率大于 0 的点里选；依次比联合正确率、覆盖率、macro-F1、成本（端点 alpha 只算一个分量，成本低于混合点）、固定顺序（alpha 从小到大；阈值按与 0.5 的距离、再按数值）。负责方须按同一规则选点。
- 逐点指标：`macro_f1`、`mean_evidence_f1`、`joint_correctness` 差不超过 1e-9（同为 null 亦可），`count`、`evidence_denominator`、`joint_denominator` 整数相等。

| 不符 | 原因码 |
|---|---|
| 记录与登记时的副本不同 | `fusion_selection_not_registered` |
| 不是在 dev 上选，或用了 test | `fusion_selection_contaminated` |
| 数据身份不同 | `fusion_selection_dataset_mismatch` |
| `dev_input_hashes` 与复核的 dev 记录不同 | `fusion_selection_dev_inputs_mismatch` |
| 分量 revision 或类型与注册不同 | `fusion_selection_component_mismatch` |
| 网格不是规定网格或逐点未恰好覆盖 | `fusion_selection_grid_invalid` |
| 某点指标或分母不同（`mismatched_points` 给出点与字段） | `fusion_selection_point_mismatch` |
| 选中点不是复算选出的点 | `fusion_selection_selected_mismatch` |
| 端点 alpha 却声称有融合收益 | `fusion_gain_claimed_at_endpoint` |
| `fusion_gain_observed` 与选中点的复算结果不同 | `fusion_gain_observed_mismatch` |
| 注册里的 alpha 与阈值不是选中点 | `fusion_selection_registration_mismatch` |

有任一原因即 `fusion_selection.status=rejected`，整份报告 `rejected`。复算只确认负责方的 dev 选择可以复现，不评模型质量，也不替负责方选点。
