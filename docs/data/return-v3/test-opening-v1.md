# 封存 test 的一次性打开 `rolecraft-held-out-test-opening-v1`

封存 test 只在模型冻结之后、经用户批准打开一次，用来报告一次性的 test 指标；看过的 test 只能作回归用，不能再参与任何选择。打开由 `verify-return --partition test` 完成：先核冻结记录与批准，再以独占创建写下打开记录，之后才读 test 文件。同一数据包的第二次打开在读任何 test 内容之前被拒绝。CLI 没有确认、强制、重开或绕过参数；批准只存在于 campaign 文件。

学员界面不显示 test；结果只出现在复核报告与打开记录里。

## 1. 前置

- 数据包为[按 split 冻结的布局](dataset-split-sealed-v1.md)，含 test 且 `test_sealed=true`；状态为 `FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA` 的包不能打开（`fixture_cannot_authorize_confirmatory`）。
- 被测模型已登记（线性回传、编码器回传或融合），并已用 dev 完成复核。
- 负责方清单（`checkpoint-manifest.json`）显式写 `training_partitions=["train"]`、`selection_partition="dev"`、`test_used_for_selection=false`，数据身份与数据包一致；缺任一项 `held_out_selection_declaration_required`，取值不符 `model_return_selection_contaminated`。
- 负责方在冻结后对 test 逐条预测一次，交回 `predictions.test.jsonl`（[预测行](predictions-v3.md)）。

## 2. 冻结（准备，不是批准）

由总调度在单独目录准备冻结记录。`prepare_test_freeze` 把数据 manifest、注册项、复核策略、负责方清单与负责方冻结的源码身份文件拷进新目录，再调用既有冻结协议 `expansion-v3-w08-freeze-v1`（协议不改）：

```sh
uv run --locked python - <<'PYTHON'
from pathlib import Path
from career_lab.contracts.v2 import Budget, FileRef, SourceIdentity
from career_lab.models.v3.held_out import prepare_test_freeze
from career_lab.models.v3.bundle import sha

lock = Path('/path/to/producer/requirements.lock').read_bytes()       # 负责方训练依赖锁定
record = Path('/path/to/producer/freeze-record.json').read_bytes()    # 负责方冻结记录
prepared = prepare_test_freeze(
    Path('/path/to/new-freeze-dir'),
    dataset_root=Path('/path/to/dataset-package'),
    dataset_hash='<dataset-manifest.json 的 SHA-256>',
    registry_root=Path('/path/to/registry'),
    registration=FileRef(path='<注册相对路径>', sha256='<注册 SHA-256>'),
    checkpoint_manifest=Path('/path/to/checkpoint-manifest.json'),
    source=SourceIdentity(
        base_commit='<负责方训练代码 commit，40 位>',
        source_digest='<负责方冻结记录里的源码 digest>',
        overlay=FileRef(path='source/freeze-record.json', sha256=sha(record)),
        dependency_locks=(FileRef(path='source/requirements.lock', sha256=sha(lock)),),
    ),
    source_files={'source/freeze-record.json': record, 'source/requirements.lock': lock},
    candidate_id='<候选标识>',
    budget=Budget(model_calls=0, actions=0, wall_seconds=600),
)
print(prepared.freeze.model_dump_json(), prepared.candidate.model_dump_json())
PYTHON
```

冻结目录里：`dataset-manifest.json`（绑定数据身份）、注册项（与注册目录中的相对路径相同，即候选的 `runtime`）、`review-policy.json`（候选的 `evaluation`，内容由数据身份唯一确定，见第 5 节）、`checkpoint-manifest.json`、源码身份文件与 `freeze.json`。fixture 数据包得到的冻结记录 `fixture=true`，不能批准。

## 3. 批准（每次打开前由用户确认）

用户在对话里确认这一次打开后，总调度在**同一冻结目录**写 `campaign.json`（`TestCampaign`，契约不改）并单独提交：

```json
{"schema_version": 2, "id": "<campaign 标识>", "candidates": [<prepare 打印的候选>],
 "split_manifest": {"path": "dataset-manifest.json", "sha256": "<数据 manifest SHA-256>", "media_type": "application/json"},
 "frozen_at": "<冻结时间>", "opened_at": "<用户确认的时间>", "output_audience": ["coordinator"]}
```

`opened_at` 为空即未批准（`campaign_not_authorized`）。

## 4. 打开

```sh
uv run --locked python -m career_lab.models.v3.registry_cli verify-return \
  --dataset-root /path/to/dataset-package --dataset-hash '<数据 manifest SHA-256>' \
  --predictions /path/to/predictions.test.jsonl --partition test \
  --checkpoint-manifest /path/to/checkpoint-manifest.json \
  --registry /path/to/registry --registration-path '<注册相对路径>' --registration-hash '<注册 SHA-256>' \
  --freeze /path/to/new-freeze-dir/freeze.json --freeze-hash '<freeze.json SHA-256>' \
  --campaign /path/to/new-freeze-dir/campaign.json --campaign-hash '<campaign.json SHA-256>' \
  --ledger /path/to/held-out-ledger --operator '<操作者标识>'
```

按顺序核，任一不过即拒绝、不留记录、不读 test 文件：

1. 预测文件可读、每行是对象、record_id 不重复、全文件只有一个 `model_revision`（坏文件不会用掉这次打开）；参数齐全（冻结、campaign、账本、操作者、注册、负责方清单）→ 否则 `held_out_test_authorization_required`（403，报错列出缺项）。
2. `<ledger>/<数据 manifest SHA-256>/test.json` 不存在 → 否则 `held_out_test_already_opened`（403）。
3. 数据包为封存布局（`held_out_layout_required`）、非 fixture；负责方清单的选择声明与数据身份（第 1 节）。
4. campaign 在冻结目录内（`held_out_campaign_outside_freeze_root`），其中恰有一个候选的 `runtime` 等于所给注册引用（`held_out_campaign_candidate_mismatch`）。
5. 既有 `validate_campaign`：冻结记录未漂移且非 fixture、campaign 已批准、候选同时在 campaign 与冻结记录里、`runtime` 与 `evaluation` 被钉住、split manifest 即数据 manifest。
6. 所给负责方清单就是冻结时钉住的那份（`held_out_checkpoint_manifest_not_frozen`）；候选 `evaluation` 就是本数据包的复核策略（`held_out_review_policy_mismatch`）；注册可核。
7. 以独占创建写打开记录；随后才读 test 的 4 个文件，按 dev 同样的规则复核（格式、分语言指标、两次重载与容差比对）。

打开记录（`<ledger>/<数据 manifest SHA-256>/test.json`，创建后不改、不删）：

```json
{"protocol": "rolecraft-held-out-test-opening-v1",
 "dataset_id": "…", "dataset_manifest_sha256": "…",
 "campaign": {"id": "…", "path": "campaign.json", "sha256": "…"},
 "candidate_id": "…", "freeze": {"id": "…", "path": "freeze.json", "sha256": "…"},
 "registration": {"id": "…", "path": "…", "sha256": "…"},
 "review_policy_sha256": "…", "verifier_source_digest": "<复核时全部产品源码的 digest>",
 "operator": "…", "opened_at": "<UTC 时间>"}
```

报告的 `split=test`、`held_out_test_opened=true`、`opened` 等于这份记录。记录创建之后复核失败（例如某行格式错误）也保留记录，报告照实 `rejected`，不重试；同一数据包换操作者或换 campaign 都不能再次打开。

## 5. 复核策略 `rolecraft-return-review-policy-v1`

```json
{"protocol": "rolecraft-return-review-policy-v1", "dataset_id": "…", "dataset_manifest_sha256": "…",
 "partition": "test", "task_type": "relation", "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
 "metric_version": "w08-evidence-metrics-v2", "evaluation_setting": "given_evidence_only",
 "reload_comparison": {"probabilities": "absolute_difference", "tolerance": {"linear": 1e-06, "encoder": 0.0001},
                       "labels": "exact", "evidence_sets": "exact"}}
```

规范 JSON（键排序、无多余空白）加换行写出；`career_lab.models.v3.held_out.review_policy_bytes` 给出准确字节。

## 6. 边界

只证明打开受控、只发生一次、留下可追溯身份；不证明模型质量，不把 test 结果用于任何选择，也不改变评分。负责方命令不执行；真实打开每次都要用户在对话里确认。
