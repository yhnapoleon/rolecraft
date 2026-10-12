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

`<split>` 取 `train`、`dev`、`test`。每行格式沿 fixture v2：输入行与标签行字段相同，metadata 行字段同 W07 手册「负责方回传」节（含 `connected_component_id`、`lineage`、`provenance`、`packaged_sources`）。

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

结构规则在读任何 split 文件之前全部核完，违反时的错误码：`dataset_split_unknown`、`dataset_split_file_not_isolated`（403）、`dataset_split_files_incomplete`、`dataset_split_file_outside_partition`（403）、`dataset_test_split_must_be_sealed`（403）、`dataset_test_sealed_without_test`。

## 3. 数据卡

`data_card.md` 里放一个 JSON 块，`splits` 与 manifest 各 split 的计数逐项相同（不含 `files`）：

```json
{"protocol": "dataset-card-v1", "splits": {"train": {"records": 600, "labels": {}, "language": {}, "evidence_evaluable": 560, "label_only": 40, "label_tiers": {}}}}
```

## 4. validate-handoff 怎样核

```sh
uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package /path/to/dataset-package --output /path/to/new-review
```

- **train、dev**：逐条审阅同 W07 手册（输入 hash、标签投影、适用性、证据集合、来源映射、双遍调用原件），另核：输入、标签、注释、metadata 四个文件按 record_id 与 input_hash 逐条对齐，metadata 的 `split` 等于所在分区；来源快照与调用原件只能在本 split 的 `audit/<s>/` 下（`handoff_source_outside_split`）；连通组件不跨 split；每个 split 的计数（含 `label_tiers`，缺即 `handoff_label_tiers_required`）与实际一致，数据卡与 manifest 一致。
- **封存的 test**：只核文件 SHA-256 与大小、非空行数（inputs、labels、metadata 等于 `records`，annotations 不多于 `records`；不符 `handoff_sealed_count_mismatch`）；只解析 test metadata，核 `split=test`、语言计数，以及 record_id、input_hash、`connected_component_id`、`lineage.structure_id` 与 train/dev 都不相交（`handoff_record_cross_split`、`handoff_component_cross_split`、`handoff_structure_cross_split`），来源映射只指向 `audit/test/`。test 的输入、标签、注释与调用原件不解析；标签分布、`label_tiers`、可评与 label-only 计数只作声明记录。与 train/dev 的近似重复筛查需要读 test 输入，封存期间不做。
- `--split test --checkpoint-manifest …` 在封存包上拒绝（`held_out_test_sealed`，403）：test 的逐条核验只能经一次性打开。

报告在 v2 字段之外加（仅本布局）：

| 字段 | 内容 |
|---|---|
| `layout` | `rolecraft-dataset-split-sealed-v1` |
| `sealed_test` | `null`（无 test）或 `{split, records, files{路径: sha256}, labels_parsed=false, inputs_parsed=false, verified[…], declared_only[…]}` |
| `annotation_trace` | `{"zh": […], "en": […]}`：每条 train/dev 记录的 record_id、input_hash、split、语言、审阅状态、标签等级、裁决引用，以及每遍调用的 id、状态、input_hash、invocation_id、model_revision、prompt_revision、证据顺序、原始输出 SHA-256、调用原件路径与 SHA-256 |

退出码、恢复与只读边界同 W07 手册；training_ready 恒为 false。
