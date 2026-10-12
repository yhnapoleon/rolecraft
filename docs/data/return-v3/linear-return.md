# 线性模型回传 `rolecraft-linear-return-v1`

负责方用自己的训练环境拟合 TF-IDF＋逻辑回归（关系三分类与证据选择），按本页格式回传后，RoleCraft 用自己的加载器登记进模型注册表，在正常反馈里给 R2.support 出「模型建议（不计分）」。负责方的训练环境不需要安装本仓库；我们不运行负责方的命令或 Python，只读本页规定的文件。

**范围**：只收关系任务（`task_type=relation`，标签顺序 `SUPPORTED, CONTRADICTED, INSUFFICIENT`）。评价项五分类（criterion）的线性回传格式本版不发布，待负责方确定五分类走 Judge 还是独立 head 后再定。登记只说明文件与声明身份可核、可加载，不证明训练质量；合成数据或交接 fixture 上的登记只能是 `synthetic_fixture`，界面标机制演示。

## 1. 目录

```
<回传目录>/
  checkpoint-manifest.json   外层清单（fixture v2 模板＋三个新字段）
  linear/model.json          特征器、分类器与证据头的声明
  linear/arrays.npz          权重数组（NumPy，无 pickle）
  predictions.dev.jsonl      dev 逐条预测（fixture v2 行格式；不登记，供复核）
  <训练说明文件>             见外层清单 training_notes_file
```

`checkpoint_files` 恰为 `linear/model.json` 与 `linear/arrays.npz` 两项及其 SHA-256；多一项、少一项都拒绝。登记时这三个文件（含外层清单）复制进注册表，之后不依赖回传目录。

## 2. 外层清单 `checkpoint-manifest.json`

沿用交接包 fixture-20261007-v2 中 `return/checkpoint-manifest.template.json` 的全部字段与取值规则（`template=false`、`completed=true`、`return_protocol=rolecraft-label-evidence-v2`、`task_type=relation`、固定 `label_order`、`training_partitions=["train"]`、`selection_partition="dev"`、`test_used_for_selection=false`、`evidence_selection_implemented=true`、`evidence_selection_required=true`，以及非空的 `model_revision`、`framework`、`framework_version`、`dataset_id`、`load_and_predict_command`、`training_notes_file`、`predictions_file` 与 64 位十六进制 `dataset_manifest_sha256`），另加：

| 字段 | 取值 |
|---|---|
| `artifact_kind` | `"linear"`（注册按它分派；编码器回传不写或另行规定） |
| `artifact_protocol` | `"rolecraft-linear-return-v1"` |
| `label_tiers` | 可选；训练数据的标签等级，`G0`、`G1`、`G2`、`G2v` 的不重复子集，界面显示为训练数据说明 |

`dataset_manifest_sha256` 是负责方新数据包 `dataset-manifest.json` 文件字节的 SHA-256，不要沿用交接 fixture 的 hash。数据集名含 `fixture` 或数据 hash 为交接 fixture v2（`5c8f0d5b…`）的回传不能登记成外部候选。

## 3. `linear/model.json`

```json
{
  "text_template": "rolecraft-linear-text-v1",
  "vectorizer": {
    "analyzer": "char_wb",
    "ngram_range": [1, 3],
    "lowercase": true,
    "sublinear_tf": true,
    "norm": "l2",
    "smooth_idf": true,
    "use_idf": true,
    "vocabulary": {"a": 0, "ab": 1, "…": 2}
  },
  "classifier": {"kind": "multinomial_logistic", "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]},
  "evidence_head": {"kind": "pair_logistic", "vectorizer": "shared", "threshold": 0.5},
  "training": {"seed": 5002, "C": 1.0, "class_weight": "balanced"}
}
```

- `vectorizer`：只接受这 8 个键（可另带取缺省值 `(?u)\b\w\w+\b` 的 `token_pattern`）。`analyzer` 限 `char`、`char_wb`、`word`；`ngram_range` 为 `[最小, 最大]` 整数，1 ≤ 最小 ≤ 最大 ≤ 16；`norm` 为 `l1`、`l2` 或 `null`；四个开关为布尔；`vocabulary` 为非空词表，索引恰为 `0..n-1`。不接受自定义 analyzer、tokenizer、preprocessor、stop_words、accent 处理、二值计数或任何可调用对象。
- `classifier`：多项逻辑回归（softmax），`label_order` 固定为关系标签顺序。One-vs-rest 或其他概率语义不支持。
- `evidence_head`：`pair_logistic` 二分类，对每个候选的 pair 文本给「该候选是否属于证据」的概率，`≥ threshold` 即选中；`threshold` 在 dev 上选定，取值 [0,1]。`vectorizer` 为 `"shared"` 时复用上面的特征器；否则写一个同样格式的独立特征器对象。**证据头必填**：缺了直接拒绝。
- `training`：可选，只记录（seed、C、类别权重、耗时等），加载器不解释。其余键一律拒绝。

## 4. `linear/arrays.npz`

用 `numpy.savez` 写，不含 object 数组（加载用 `allow_pickle=False`）。全部为有限浮点数，按 float64 读。k=3 为标签数，n 为主词表大小，n_e 为证据头词表大小（共用时 n_e=n）。

| 数组 | 形状 | 何时出现 |
|---|---|---|
| `coef` | (k, n) | 必有；行顺序按 `label_order` |
| `intercept` | (k,) | 必有 |
| `evidence_coef` | (n_e,) | 必有；二分类正类（1）的系数 |
| `evidence_intercept` | (1,) | 必有 |
| `idf` | (n,) | 主特征器 `use_idf=true` 时必有，否则不得出现 |
| `evidence_idf` | (n_e,) | 独立证据特征器且 `use_idf=true` 时必有，否则不得出现 |

键集合、形状与有限值逐项核对，多余或缺少的数组都拒绝。

## 5. 特征文本 `rolecraft-linear-text-v1`

加载器把每条输入（数据包 `*.inputs.jsonl` 里的 `model_input`）变成两种文本再向量化，负责方必须在同样的文本上拟合：

- 关系文本：`purpose`、`claim`、参照时点行、再逐个候选写「候选原文」与「候选有效期行」，以换行连接。
- pair 文本（每个候选一条）：`claim`、参照时点行、`[EVIDENCE]`、候选原文、候选有效期行。
- 参照时点行：`reference time <as_of.business_seq>; temporal scope <rule_context.evidence_time_context.status，缺省为 undetermined>`。
- 候选有效期行：`observed <observed_at_seq>; valid from <valid_from_seq>; valid until <valid_until_seq，空为 open>`。

标签、审计文件与外层 `input_hash` 从不进入文本。[`reference/linear_text_v1.py`](reference/linear_text_v1.py) 只用 Python 标准库给出这两个函数（`relation_text`、`pair_text`）。[`linear-text-v1.golden.jsonl`](linear-text-v1.golden.jsonl) 覆盖 fixture v2 的全部 12 条输入和中英合成样例（含空候选、无时点上下文、换行与非 ASCII 字符），每行给 `input_hash`、`model_input`、关系文本与各候选 pair 文本的 UTF-8 SHA-256。自检：

```sh
python3 reference/linear_text_v1.py linear-text-v1.golden.jsonl   # 每行应为 ok
```

我方测试保证产品函数、参考实现与金标逐条一致。

## 6. `model_revision`

```python
import hashlib, json
identity = {
    "model_json_sha256": sha256(linear/model.json 的字节),
    "arrays_npz_sha256": sha256(linear/arrays.npz 的字节),
    "dataset_manifest_sha256": 外层清单里的值,
}
canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
model_revision = "linear-return:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

外层清单与 `predictions.dev.jsonl` 每一行都写这个值；加载时重算，不一致即拒绝。

## 7. 推理口径（加载器）

1. 输入不完整、`claim` 为空、时点上下文未定或候选有效期未知时，弃权（`status=abstained`，原因与 fixture v2 行的 `reason` 相同取值，如 `temporal_scope_undetermined`），不出概率。
2. 关系概率＝softmax(关系文本特征 · `coef`ᵀ ＋ `intercept`)，标签取首个最大值。
3. 证据分＝sigmoid(pair 文本特征 · `evidence_coef` ＋ `evidence_intercept`)，`≥ threshold` 的候选按原顺序选中；可以为空（空选择须在预测行写 `reason`）。
4. 线性模型没有 token 上限（输入大小度量返回无上限），长输入不因长度弃权。

## 8. 导出脚本

[`reference/export_sklearn_linear.py`](reference/export_sklearn_linear.py)（numpy、scikit-learn、标准库与同目录 `linear_text_v1.py`；不依赖本仓库）把拟合好的 `TfidfVectorizer`、多项 `LogisticRegression`（关系）与二分类 `LogisticRegression`（证据）写成本页格式，并用**负责方自己的对象**对 dev 输入逐条预测写出 `predictions.dev.jsonl`。用法见脚本开头。它拒绝加载器不能精确重建的对象：自定义 analyzer／tokenizer／preprocessor、非缺省 token_pattern、accent 处理、停用词、二值计数、非 float64 输出、类别不是三类关系标签、证据分类器不是 {0,1}、以及概率与 softmax／sigmoid(线性分数) 不符（例如 one-vs-rest）。目标目录已存在时不覆盖。`training_partitions`、`test_used_for_selection` 与训练说明须如实填写。

## 9. 我方怎样登记与复核

```sh
uv run --locked python -m career_lab.models.v3.registry_cli register \
  --registry <注册目录> --bundle-root <回传目录> \
  --bundle-path checkpoint-manifest.json --bundle-hash <清单 SHA-256> \
  --scope external_candidate          # 合成或 fixture 数据用 synthetic_fixture
uv run --locked python -m career_lab.models.v3.registry_cli describe \
  --registry <注册目录> --registration-path <返回的相对路径> --registration-hash <返回的 SHA-256>
```

`describe` 输出公开身份（`kind=linear`、`dataset`：数据集名、数据 hash、标签等级）。注册项协议为 `advisory-linear-registration-v1`，按内容命名、不可覆盖，固定 `mode=advisory`、`affects_score=false`、`quality_validated=false`；推理闭包源码（`models/v3/**`、`contracts/v2/{core,data}.py`）或 numpy、scikit-learn、pydantic 版本变化时旧注册拒绝加载，须重新登记。回传复核（`verify-return`）的口径：用我方加载器重载并与 `predictions.dev.jsonl` 比较，线性模型概率逐项绝对差 ≤ 1e-6，标签、状态与证据集合完全一致；负责方的加载命令只作参考。

## 10. 拒绝与错误码

| 情形 | 错误码 |
|---|---|
| 标签顺序错、任务不是 relation | `model_return_task_or_labels_invalid` |
| 模板未完成、证据选择未声明 | `model_return_incomplete` |
| `artifact_protocol` 不符 | `linear_return_protocol_invalid` |
| `checkpoint_files` 不是恰好两项 | `linear_return_member_set_mismatch` |
| 文件 hash 不符 | `file_hash_mismatch` |
| `text_template` 不是 `rolecraft-linear-text-v1` | `linear_text_template_unsupported` |
| 特征器参数或键不受支持（含自定义 analyzer、非缺省 token_pattern） | `linear_vectorizer_unsupported` |
| 词表为空或索引不连续 | `linear_vocabulary_invalid` |
| 分类器不是多项逻辑回归或标签顺序不符 | `linear_return_labels_invalid` |
| 缺 `evidence_head` | `linear_return_evidence_head_required` |
| 证据头类型、阈值或键不符 | `linear_evidence_head_unsupported` |
| `model.json` 有未知键或不是对象 | `linear_return_model_invalid` |
| 数组缺失、多余、非浮点或含 pickle | `linear_return_arrays_invalid` |
| 数组形状不符 | `linear_return_array_shape_invalid` |
| 数组含 NaN／Inf | `linear_return_array_values_invalid` |
| `model_revision` 与公式不符 | `linear_return_revision_mismatch` |
| `label_tiers` 不合法 | `linear_return_label_tiers_invalid` |
| 文件超过 64 MiB | `linear_return_too_large` |
| fixture 数据登记为外部候选 | `fixture_cannot_be_registered_as_external` |
