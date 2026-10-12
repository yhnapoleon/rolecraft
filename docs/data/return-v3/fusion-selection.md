# 融合选择记录 `rolecraft-fusion-selection-v1` 与融合登记

融合模型由我方登记：负责方交回两个分量（线性回传、编码器回传任意组合，各自按其格式回传）和一份在 dev 上做出的选择记录，我方用两个已登记的分量加这份记录构建融合注册，不需要负责方另交融合权重。负责方自己的融合 dev 逐条预测可以照常回传，供复核比对。

**范围**：只收关系任务。融合不能嵌套（分量不能是融合），我方旧的 W01 ModelBundle 之间的融合仍走原 `save_fusion_bundle` 路径。登记只核身份与结构，不重算指标；dev 网格复算由回传复核（`verify-return --fusion-selection`）负责；**该参数由回传复核 v3（147）提供，本分支尚未包含**。

## 1. 融合怎样计算

左右分量各对同一输入给出关系概率 `p_left`、`p_right` 与逐候选证据分 `e_left`、`e_right`：

```
p = (1 − alpha) · p_left + alpha · p_right
e = (1 − alpha) · e_left + alpha · e_right
选中证据 = { 候选 | e ≥ evidence_threshold }
标签 = p 的首个最大值（固定标签顺序）
```

任一分量弃权或失败时融合弃权（`fusion_component_unavailable`）。`alpha=0` 只用左分量、`alpha=1` 只用右分量，结果照原样转出（阈值用记录选中的阈值）。

## 2. 选择记录字段

```json
{
  "protocol": "rolecraft-fusion-selection-v1",
  "task_type": "relation",
  "dataset_id": "<与两个分量相同>",
  "dataset_manifest_sha256": "<与两个分量相同>",
  "selection_split": "dev",
  "test_used_for_selection": false,
  "components": {
    "left": {"model_revision": "<左分量 model_revision>", "artifact_kind": "linear"},
    "right": {"model_revision": "<右分量 model_revision>", "artifact_kind": "huggingface_encoder"}
  },
  "alpha_grid": [0, 0.25, 0.5, 0.75, 1],
  "evidence_threshold_grid": [0.25, 0.5, 0.75],
  "selected": {"alpha": 0.25, "evidence_threshold": 0.5},
  "points": [
    {
      "alpha": 0, "evidence_threshold": 0.25,
      "metrics": {
        "count": 288, "macro_f1": 0.61, "mean_evidence_f1": 0.42, "joint_correctness": 0.30,
        "evidence_denominator": 240, "joint_denominator": 240
      }
    }
  ],
  "fusion_gain_observed": true,
  "dev_input_hashes": ["<dev 每条记录的外层 input_hash>"]
}
```

| 字段 | 规则 |
|---|---|
| `protocol`、`task_type` | 固定值；不认识的键一律拒绝 |
| `dataset_id`、`dataset_manifest_sha256` | 与两个分量登记的数据身份相同 |
| `selection_split`、`test_used_for_selection` | 只能是 `"dev"` 与 `false`；test 不参与任何选择 |
| `components` | 左右分量的 `model_revision` 与类型（`linear`、`huggingface_encoder`），须与登记时所给的两个注册一致 |
| `alpha_grid` | 恰为 `[0, 0.25, 0.5, 0.75, 1]` |
| `evidence_threshold_grid` | 非空、互不相同、每项在 [0,1] |
| `points` | alpha 网格 × 阈值网格的每个点恰好一条；`metrics` 六个键：比例项 `macro_f1`、`mean_evidence_f1`、`joint_correctness` 为 [0,1] 或 `null`，计数项 `count`、`evidence_denominator`、`joint_denominator` 为非负整数（label-only 记录不进证据与联合分母） |
| `selected` | 网格中的一个点 |
| `fusion_gain_observed` | 布尔；选中端点（alpha 为 0 或 1）时必须为 `false`，即「无融合收益」照实写 |
| `dev_input_hashes` | 参与选择的 dev 记录外层 `input_hash`，非空、互不相同 |

指标名与我方指标实现（`summarize`）一致，便于逐点复算比对。

## 3. 融合预测的 `model_revision`

负责方的融合 dev 预测行用同一公式：

```python
import hashlib, json
identity = {"left": 左分量 model_revision, "right": 右分量 model_revision,
            "alpha": float(alpha), "evidence_threshold": float(evidence_threshold)}
canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
model_revision = "fusion-return:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

## 4. 我方怎样登记

先分别登记两个分量（见[线性回传](linear-return.md)与编码器回传规格），再：

```sh
uv run --locked python -m career_lab.models.v3.registry_cli register-fusion \
  --registry <同一注册目录> \
  --left-path <左分量注册相对路径> --left-hash <左分量注册 SHA-256> \
  --right-path <右分量注册相对路径> --right-hash <右分量注册 SHA-256> \
  --selection <选择记录文件> --scope external_candidate   # 任一分量为合成登记时只能 synthetic_fixture
uv run --locked python -m career_lab.models.v3.registry_cli describe \
  --registry <注册目录> --registration-path <返回的相对路径> --registration-hash <返回的 SHA-256>
```

注册项协议 `advisory-fusion-registration-v1`：按分量注册文件的路径与 SHA-256 引用分量，不复制权重；注册目录只多存一份选择记录副本。公开身份：`kind=probability_fusion`、`dataset`（标签等级取两分量的并集）、`components`（左右各一：注册 id、类型、`model_revision`、该分量在融合概率中的权重 `alpha`——左为 1−alpha，右为 alpha）、`fusion`（`alpha`、`evidence_threshold`、`fusion_gain_observed`）。每次加载都重新核对两个分量的注册与文件，任一分量漂移、被删或运行环境变化，融合即加载失败，新反馈的模型建议显示「模型文件或推理环境已变化，需重新核验注册。」；旧反馈不变。

## 5. 拒绝与错误码

| 情形 | 错误码 |
|---|---|
| 分量不是线性回传或编码器回传（含 W01 ModelBundle 注册、融合注册） | `fusion_component_kind_unsupported` |
| 左右是同一注册 | `fusion_components_identical` |
| 分量不是关系任务或标签顺序不同 | `fusion_component_task_mismatch` |
| 两分量数据集名或数据 hash 不同 | `fusion_component_data_mismatch` |
| 分量没有可核的数据身份 | `fusion_component_dataset_unknown` |
| 外部候选融合含合成分量 | `fusion_scope_exceeds_components` |
| 选择不在 dev 上做，或用了 test、未声明 | `fusion_selection_contaminated` |
| 协议名、键集合、`fusion_gain_observed` 类型或 `dev_input_hashes` 不合规定 | `fusion_selection_protocol_invalid` |
| 记录的数据身份与分量不同 | `fusion_selection_dataset_mismatch` |
| 记录的分量 revision 或类型与所给注册不同 | `fusion_selection_component_mismatch` |
| alpha 网格不是规定网格、阈值网格不合法或逐点未恰好覆盖网格 | `fusion_selection_grid_invalid` |
| 逐点指标缺键或越界 | `fusion_selection_metrics_invalid` |
| 选中点不在网格内 | `fusion_selection_alpha_invalid` |
| 端点 alpha 却声称有融合收益 | `fusion_selection_gain_claim_invalid` |
| 分量注册文件被改、被删 | `file_hash_mismatch`、`file_missing` |
| `--scope` 不是 `synthetic_fixture` 或 `external_candidate` | `registration_scope_required` |
| 加载时：注册项协议或 scope 不认识 | `model_registration_protocol_invalid` |
| 加载时：注册项被改成计分或已验证质量 | `registration_cannot_promote_scoring_or_quality` |
| 加载时：注册 id、路径与内容不符 | `model_registration_identity_mismatch` |
| 加载时：推理闭包源码或依赖版本已变 | `registered_inference_runtime_changed` |
| 加载时：分量的 id、类型或 revision 与登记时不同 | `fusion_component_identity_mismatch` |
| 加载时：按现存分量与选择记录重建的注册项与登记时不同 | `registered_model_identity_mismatch` |
