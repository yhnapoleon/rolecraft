# 按 split 独立冻结的数据包 `rolecraft-dataset-split-sealed-v1`

fixture v2 的可移植布局把全部记录的注释与 metadata 放在一份共用文件里，所以只能装 train/dev。含封存 test 的数据包改用本布局：每个 split 自带输入、标签、注释与 metadata，各自逐文件绑定 SHA-256。读 train/dev 时不打开任何 test 文件；test 只在冻结与批准之后经[一次性打开](test-opening-v1.md)读取。fixture v2 包、v2-r1 ZIP 与其 hash 一字节不变，仍按原布局读。

## 1. 目录

```
dataset-manifest.json
data_card.md
data/<split>.inputs.jsonl          模型输入（record_id、外层 input_hash、model_input）
data/<split>.labels.jsonl          标签（与输入分文件，按 record_id + input_hash 对齐）
audit/<split>/annotations.jsonl    每条记录的标注原件（AnnotationV2）
audit/<split>/metadata.jsonl       语言、来源、谱系、split 与包内来源映射
audit/<split>/labels/passes/…      该 split 的标注调用原件（如有）
audit/<split>/sources/…            该 split 的来源快照（如有）
```

`<split>` 取 `train`、`dev`、`test`。每行格式沿 fixture v2：输入行与标签行字段相同，metadata 行字段见第 5 节。包目录里只能有 manifest 列出的文件（各 split 的 `files` 与顶层 `files`），以及 `SHA256SUMS`（可选，`shasum -a 256` 格式）完整枚举并校验的补充文件。多出或缺少的文件（`handoff_file_set_mismatch`）、任何符号链接（`handoff_symlink_forbidden`）、hash 或大小与 manifest 不符（`file_hash_mismatch`、`handoff_file_size_mismatch`）都整包拒绝；JSON 与 JSONL 不能有重复键（`handoff_duplicate_json_key`）或 NaN／Infinity（`handoff_nonfinite_json_number`）。

## 2. manifest

```json
{
  "schema_version": 1,
  "layout": "rolecraft-dataset-split-sealed-v1",
  "dataset_id": "<新的数据身份>",
  "status": "<数据状态>",
  "annotation_version": "<标注版本>",
  "task_type": "relation",
  "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
  "label_orders": {"relation": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]},
  "test_sealed": true,
  "splits": {
    "train": {
      "records": 600, "labels": {"SUPPORTED": 220, "CONTRADICTED": 180, "INSUFFICIENT": 200},
      "language": {"zh": 300, "en": 300}, "evidence_evaluable": 560, "label_only": 40,
      "label_tiers": {"G0": 120, "G2v": 480},
      "files": {
        "data/train.inputs.jsonl": {"sha256": "<64 位>", "size": 123},
        "data/train.labels.jsonl": {"sha256": "…", "size": 0},
        "audit/train/annotations.jsonl": {"sha256": "…", "size": 0},
        "audit/train/metadata.jsonl": {"sha256": "…", "size": 0}
      }
    },
    "dev": {"…": "同上"},
    "test": {"…": "同上"}
  },
  "files": {"data_card.md": {"sha256": "…", "size": 0}}
}
```

| 字段 | 规则 |
|---|---|
| `layout` | 固定为 `rolecraft-dataset-split-sealed-v1`；没有这个字段即按 fixture v2 布局读 |
| `status` | `FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA` 表示交接 fixture，不能批准 test 打开；`SYNTHETIC_MECHANISM_SAMPLE_NOT_TRAINING_DATA` 表示我方构造的机制样例，报告标 `synthetic_fixture`；其余值是负责方对数据的说明 |
| `test_sealed` | 有 test 必须为 `true`，没有 test 必须为 `false` |
| `splits.<s>` | 计数字段同 fixture v2，另须 `label_tiers`；`files` 列出该 split 拥有的全部文件 |
| `splits.<s>.files` | 必须含上面 4 个固定文件；所有路径只能在 `data/<s>.` 或 `audit/<s>/` 下；同一路径不能出现在两个 split |
| `files` | 只放共用文件（数据卡等）；不能放任何 `data/` 或 `audit/<split>/` 下的文件 |

另外，不同 split 的 4 个固定文件不能字节相同（同一份内容不能挂两个分区名）。读某个分区时，所读文件路径上不能有符号链接（`dataset_symlink_forbidden`，403）；validate-handoff 拒绝包内任何符号链接。

结构规则在读任何 split 文件之前全部核完，违反时的错误码：`dataset_split_unknown`、`dataset_split_file_not_isolated`（403）、`dataset_split_files_incomplete`、`dataset_split_file_outside_partition`（403）、`dataset_test_split_must_be_sealed`（403）、`dataset_test_sealed_without_test`。

## 3. 数据卡

`data_card.md` 里放一个 JSON 块，`splits` 与 manifest 各 split 的计数逐项相同（不含 `files`）：

```json
{"protocol": "dataset-card-v1", "splits": {"train": {"records": 600, "labels": {}, "language": {}, "evidence_evaluable": 560, "label_only": 40, "label_tiers": {}}}}
```

## 4. validate-handoff 怎样核

`validate-handoff` 由我方在 RoleCraft 仓库里运行，负责方不需要运行它；交付前按本页第 1–3、5 节自查即可。两种调用：

```sh
# 只核数据包
uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package /path/to/dataset-package --output /path/to/new-review

# 数据包连同模型回传的外层清单，按 dev 逐行对齐预测
uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package /path/to/dataset-package \
  --checkpoint-manifest /path/to/model-return/checkpoint-manifest.json \
  --split dev --output /path/to/new-model-review
```

命令只读交回的文件：不导入包内 Python、不运行 `load_and_predict_command`、不调用或注册模型、不发布训练数据。`--split` 只选择与预测逐行对齐的分区（缺省 `dev`），不做评测，也不打开封存的 test。`--output` 不能与数据包目录或模型回传目录重叠（`handoff_output_overlaps_package`）。模型的登记、重载与 dev 复核另由 `verify-return` 完成（[预测行 v3](predictions-v3.md)）。

- **train、dev**：逐条审阅见第 5 节（输入 hash、标签投影、适用性、证据集合、来源映射、双遍调用原件），另核：输入、标签、注释、metadata 四个文件按 record_id 与 input_hash 逐条对齐，metadata 的 `split` 等于所在分区；来源快照与调用原件只能在本 split 的 `audit/<s>/` 下（`handoff_source_outside_split`）；连通组件不跨 split；每个 split 的计数（含 `label_tiers`，缺即 `handoff_label_tiers_required`）与实际一致，数据卡与 manifest 一致。
- **封存的 test**：只核文件 SHA-256 与大小、非空行数（inputs、labels、metadata 等于 `records`，annotations 不多于 `records`；不符 `handoff_sealed_count_mismatch`）；只解析 test metadata，核 `split=test`、语言计数，以及 record_id、input_hash、`connected_component_id`、`lineage.structure_id` 与 train/dev 都不相交（`handoff_record_cross_split`、`handoff_component_cross_split`、`handoff_structure_cross_split`），来源映射只指向 `audit/test/`。test 的输入、标签、注释与调用原件不解析；标签分布、`label_tiers`、可评与 label-only 计数只作声明记录。与 train/dev 的近似重复筛查需要读 test 输入，封存期间不做。
- `--split test --checkpoint-manifest …` 在封存包上拒绝（`held_out_test_sealed`，403）：test 的逐条核验只能经一次性打开。

报告在第 6 节的通用字段之外加（仅本布局）：

| 字段 | 内容 |
|---|---|
| `layout` | `rolecraft-dataset-split-sealed-v1` |
| `sealed_test` | `null`（无 test）或 `{split, records, files{路径: sha256}, labels_parsed=false, inputs_parsed=false, verified[…], declared_only[…]}` |
| `annotation_trace` | `{"zh": […], "en": […]}`：每条 train/dev 记录的 record_id、input_hash、split、语言、审阅状态、标签等级、裁决引用，以及每遍调用的 id、状态、input_hash、invocation_id、model_revision、prompt_revision、证据顺序、原始输出 SHA-256、调用原件路径与 SHA-256 |

数据卡、`label_orders` 与 `label_tiers` 的一致性只由 validate-handoff 核对；verify-return 只核它所读分区的文件绑定、逐条对齐与语言计数。

## 5. metadata 行与 train/dev 的逐条审阅

本节与第 6 节摘自我方数据接收规则，负责方不需要另读其他文件。字段写法可对照 fixture v2 的 `audit/metadata.jsonl`（嵌套对象都带 `"schema_version": 2`），但新数据的 `bucket` 不能是 `fixture`。

`audit/<split>/metadata.jsonl` 每条记录恰一行，只允许下列键：

| 键 | 内容 |
|---|---|
| `record_id`、`input_hash` | 与输入行相同 |
| `language` | 语言代码，如 `zh`、`en` |
| `bucket` | 来源类别：`env_run`、`human_session`、`public_aux`、`business_synth`（`fixture` 只用于交接 fixture） |
| `split` | 等于所在分区 |
| `connected_component_id` | 连通组件标识；同一组件只能在一个 split |
| `lineage` | 谱系：必填 `structure_id`、`component_id`；可选 `fact_root_ids`、`run_id`、`session_id`、`branch_id`、`decision_id`、`candidate_id`、`source_record_ids`、`derivation_ids`。同一 `structure_id` 只能在一个 split |
| `provenance` | 来源说明：`command`、`source`（`base_commit` 40 位、`source_digest` 64 位、可选 `overlay` 与 `dependency_locks`）、`executor`（`id`、`kind` 取 `human`／`external_agent`／`reference_agent`／`system`）、`actual_sources`（原始相对路径与 SHA-256）、`transformations`、`license`、`captured_at`（带时区） |
| `packaged_sources` | 与 `actual_sources` 同顺序、同数量，映射到包内路径（本布局只能在 `audit/<split>/` 下）与 SHA-256 |

每条 train/dev 记录按下面的顺序核，任一不过即 `quarantine`，缺证明为 `pending`：

1. **输入**：`input_hash` 等于 `model_input` 规范 JSON 的 SHA-256（`handoff_input_hash_mismatch`）；输入、标签、注释、metadata 按 `record_id + input_hash` 对齐，重复、缺行、多行都拒绝。模型只读 `model_input`；标签、gold、角色提示词与审计材料不能放进模型输入。
2. **标签投影**：`label` 与 `label_index` 符合 manifest 冻结的列序（`handoff_label_order_mismatch`）；关系三类与评价项五类分别处理，不混成一个标签域。
3. **适用性**：`applicability=not_applicable` 时标签必须为 `NOT_APPLICABLE`（`annotation_applicability_mismatch`）；`INSUFFICIENT` 必须写 `missing_reason`。
4. **证据集合**：选中证据与可接受集合只能引用本记录的候选 ID（`annotation_invalid_reference`）；可评的正／反关系必须有证据选择（`annotation_evidence_required`），且选择属于某个可接受集合（`final_evidence_not_an_acceptable_target`）。合法的多证据联合目标保留；包含更小合法集合的超集在审阅时去掉，原件字节不改。
5. **来源映射**：`packaged_sources` 与 `actual_sources` 数量、顺序、SHA-256 与实际字节一致，不按同名文件猜来源（`handoff_source_mapping_invalid`）。非 fixture 来源一律 `pending`，原因 `authoritative_source_reader_required`：包内的授权声明不算独立证明，需我方另行读取权威来源（怎样转为 `accept` 见第 7 节）；真实数据中非 G0 的 label-only 记录另列 `label_only_semantic_review_required`。G0 标签会重新经过受限数值验证，开放语义不能自报为 G0。
6. **双遍调用原件**（`audit/<split>/labels/passes/`）：两遍各有自己的 request／invocation／context 身份、模型 revision 与不同的 prompt revision，证据顺序适当，不能复制一次调用的身份充数；语义仍有分歧需要真实的第三遍。调用失败、空输出、缺原件或绑定错误返回 `pending`，不升级为 G1。这些只能核记录内部一致，调用是否真实发生仍需独立审阅。

## 6. 结果、退出码与重跑

- 报告 `report.json`（`protocol=data-handoff-review-v1`）按 record_id 给 `accept`（机制核验通过）、`quarantine`（身份、格式或引用不符）或 `pending`（需补证明或独立核验）及稳定原因码，另有 `counts`、`data_card_check` 与第 4 节的本布局字段；`training_ready`、`quality_verified`、`call_authenticity_verified` 恒为 `false`。
- 退出码：`0` 表示全部记录 `accept` 且模型回传格式通过（只代表本次机械核验范围）。带 `--checkpoint-manifest` 时，validate-handoff 会把正当的弃权或失败预测行（例如编码器超过 `max_tokens` 的 `encoder_input_truncated`）记为 `pending`（`prediction_abstained`、`prediction_failed`），`format_valid=false`、退出 2；这是既有口径，不表示回传有错，联核时由我方逐条确认；任一记录 `pending`／`quarantine` 或模型回传不通过时为 `2`；包级错误（如文件集合不符）不写报告，只输出 `{"error": <错误码>, "message": …}`，同样以 `2` 退出，不回显私有正文。
- 同一份包对同一输出目录可重跑，报告字节相同；包或版本有变化时拒绝覆盖已有报告（`handoff_review_conflict`），用新的输出目录保存新版本。
- 核验不重新标注、不发起模型调用；所有 hash 校验只证明对应字节，不证明来源授权或事实真实。

## 7. 真实数据的 `pending` 怎样转为 `accept`

**现状**：

- `bucket` 不是 `fixture` 的每条 train/dev 记录，validate-handoff 都给 `pending`（`authoritative_source_reader_required`）。包里的来源文件与授权声明是包自己带的，不能证明自己；现在的命令还没有接入权威来源读取器，所以真实数据在这一步**全部是 `pending`、退出码 2**，这不表示你方的包有错。非 G0 的 label-only 记录另有 `label_only_semantic_review_required`，同样要独立审阅。
- 这份报告不是登记、`verify-return` 的 dev 复核和 test 打开的输入，三者都不读它，`pending` 不会在机制上卡住它们。但来源没有核过，复核报告只能说明格式、身份与预测可以复现，说明不了数据从哪里来；报告的 `training_ready` 保持 `false`。
- **谁提供读取器**：权威来源在哪一方，就由哪一方的系统读取。`env_run`、`human_session` 记录来自我方产品（经授权导出 `datasets.v3 export --live`），权威来源是我方保存的导出，读取器由我方提供；`public_aux`、`business_synth` 等你方自产的来源，请在数据计划里写明原始来源、取法与许可，我方据此商定读取方式。
- **现在没有现成机制，我方在收到你方的数据计划（来源类别、各类条数、来源从哪里取）后提供读取器与命令。**

**接口草案**（未实现，以我方之后发布的命令为准）：

```sh
uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package <数据包> --output <新目录> \
  --source-authority <我方保存的授权导出目录，或双方商定的来源登记文件>
```

- 读取器按 `record_id`＋`input_hash` 在权威来源里找到这条记录，给出它的来源绑定（沿用我方已有的 `w07-source-origin-v1`：record_id、来源类别、session、谱系 hash、源码 digest、每个来源文件的 path 与 SHA-256）。
- 与包里 metadata 的 `bucket`、`lineage`、`provenance.source.source_digest`、`provenance.actual_sources` 逐项相同：去掉 `authoritative_source_reader_required`，其余规则都通过即 `accept`；不同：`quarantine`（`authoritative_source_binding_mismatch`）；权威来源里找不到：仍是 `pending`。
- 你方现在就能做的准备：`provenance.actual_sources` 写原始来源的相对路径与 SHA-256（不改写、不重新序列化原文件），`packaged_sources` 一一映射到包内副本；我方导出的记录保持导出时的 `record_id`、`input_hash`、`lineage`、`provenance` 不变。
