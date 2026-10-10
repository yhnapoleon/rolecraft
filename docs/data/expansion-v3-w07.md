# 数据运行导出与负责方回传核验

本模块负责导出获准的产品运行、核对负责方交回的数据及保留核验结果。数据采集、清洗、标注、划分、训练和模型效果实验由技术负责方完成。合成 fixture、受控调用回执和脚本化会话只证明机制；真实负责方数据、真实双遍调用与中英文质量尚待交付，`training_ready` 保持 `false`。

## 研究授权与真实会话导出

从本工作区运行命令，固定 Python 3.12。以下参数结构已通过真实 HTTP 创建的中文、英文会话实跑。会话中完成作品、测试、分享、提交与反馈后，每种语言导出 1 条关系记录、14 条评价项；没有分支或信息获取动作时，相应切面为零并保留原因。

运行前由操作者在进程环境配置 `CAREER_LAB_CREDENTIAL_KEY_ID` 与 `CAREER_LAB_CREDENTIAL_KEY`，serve、worker 与 CLI 使用同一有效配置。生产没有默认密钥；不能从数据库摘要派生秘密，也不要把 key 写入命令正文、源码、数据库或回执。测试使用 conftest 注入的虚构 key，仅供机制验证。这组环境变量用于工作区凭据；下方 `--key-file` 是另一套研究授权签名密钥。

研究用途同意独立于会话所有权。操作者使用当前有效的人类学员凭据，明确指定单会话、用途、完整历史版本点与到期时间。令牌和独立签名密钥通过本机权限受限文件提供，不能填入命令行正文或结果文档。`point.json` 包含实际读取所得的 `business_seq`、`workspace_revision`、`storage_revision`，不能按当前时间猜测历史版本。

```sh
UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 authorize \
  --database-url sqlite:///path/to/session.db --session SESSION_ID \
  --token-file /path/to/owner-token --scenario-root /path/to/installed/scenario \
  --point /path/to/point.json --key-file /path/to/research-key \
  --purpose dataset_export --consent --expires-at EXPIRY_WITH_TIMEZONE \
  --output /path/to/new-authorization.json

UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 export --live \
  --database-url sqlite:///path/to/session.db --session SESSION_ID \
  --token-file /path/to/owner-token --scenario-root /path/to/installed/scenario \
  --point /path/to/point.json --key-file /path/to/research-key \
  --authorization /path/to/new-authorization.json --output /path/to/export

UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 validate-data \
  --export /path/to/export
```

路径与身份须替换为实际本机值；上述占位符不是现成会话。签发文件只创建一次，不覆盖旧凭证。签名密钥由操作者安全持有；公开授权投影不包含签名或凭据 ID。`issue`、`validate`、`public_identity` 供其他研究入口复用，消费端仍检查当前权限。CLI 默认从起点授权到指定点；模块 `issue` 支持窄窗口。没有明确授权、到期、用途不符、会话或读取凭据不匹配均拒绝。

授权仍有效且当前权限允许时，相同源码、授权、会话与历史窗口重复导出，规范内容、ID 和 hash 相同，业务状态及事件数不增加。已存在输出只在全部文件字节一致时恢复；内容冲突或 symlink 拒绝。离线 `export --snapshot` 只接受明确 fixture，不能把 JSON 中自报的 `env_run` 视为真实运行。

来源必须在授权窗口内且当前仍可读。父记录本身可读、在窗内而依赖不可读时，隔离项保留父引用和安全原因；父记录越界或不可读时不披露其身份、正文或受保护依赖。合法记录继续保留。失败或空测试另列执行失败，不生成语义标签。

## 导出产物

```text
export/
├── dataset-manifest.json
├── data/
│   ├── train.inputs.jsonl
│   └── train.labels.jsonl
└── audit/
    ├── authorization.json
    ├── export/                 固定快照与记录身份
    ├── metadata.jsonl
    ├── source-map.json
    ├── source-index.json
    └── sources/                获准来源文本、hash 与语言位置
```

模型只读取 `model_input`；标签、gold、隐藏探针、角色提示词及审计材料不能作为模型特征。输入和标签按外层 `record_id + input_hash` 对齐。manifest 列出实际四切面数量、空量原因、隔离项、执行失败、语言和逐文件身份。`validate-data --export` 复核清单、目录边界、输入白名单、来源索引和完整谱系；跨语言翻译或派生同组跨 split 时拒绝。

## 负责方回传

正式数据沿 fixture v2 的目录组织方式：输入与标签分开为 JSONL，另交新的 manifest、逐文件 SHA-256、split、来源谱系和数据卡。文件有变化就必须重算对应 hash；不能用旧交接包的身份指代新数据。

核对范围与《模型与数据准备事项》一致：文件 hash、记录对齐、标签顺序、分组隔离、语言、标签等级、可评与 label-only 数量、数据卡一致性及模型输入隔离。关系三类与评价项五类分别处理，不混成单一标签域。

正式回传核验入口：

```sh
UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package /path/to/dataset-package --output /path/to/new-review

UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 validate-handoff \
  --package /path/to/dataset-package \
  --checkpoint-manifest /path/to/model-return/checkpoint-manifest.json \
  --split dev --output /path/to/new-model-review
```

命令只读交回的文件，不导入包内 Python、不运行加载命令、不调用模型、不注册模型、不发布训练数据。`--split` 只选择逐行对齐的分区，不执行评测或授权打开封存 test。模型加载／注册与真实质量由 W08 在后续获准条件下独立验证。

### 数据包与来源映射

`dataset-manifest.json` 沿 fixture v2：`schema_version=1`、数据身份、状态、分区计数、逐文件 SHA-256 和大小。单任务沿 `task_type`／`label_order`；多任务可用 `label_orders` 显式映射。输入和标签每个记录恰好一行；重复、缺行、多行、错 hash、错列序、同事实／结构跨 split 都拒绝。

`audit/metadata.jsonl` 中的 `provenance.actual_sources` 保留原始相对路径；`packaged_sources` 按相同顺序映射到包内路径。数量、hash 和实际字节必须一致，不按同名文件猜来源。`audit/original-annotations.jsonl` 保存注解原件；模型标注原始请求／回执在 `audit/labels/passes/`。缺证明的记录返回 pending。G0 重新经过受限数值验证器，不能把开放语义自报为 G0。非 fixture 来源仍须独立权威读取；此 CLI 不把包内授权声明当作独立证明，返回 `authoritative_source_reader_required`。真实非 G0 的 label-only 还列 `label_only_semantic_review_required`。

完整目录只能含 manifest 列出的文件，以及 `SHA256SUMS` 完整枚举并校验的补充文件（冻结 v2 的 README、数据卡等沿此清单读取）。拒绝未列文件、软链接、路径逃逸和输出目录与输入包重叠。分区文件默认 `audit/original-release/split-manifest.json`，也可在 manifest 的 `split_manifest` 显式指定 record_id→split 映射。公共 SplitManifest 另核组件与结构身份。

数据卡的分区计数要与实际输入、标签、语言和可评范围一致。新包可在 `data_card.md` 放一个 JSON 摘要块，`splits` 与 manifest 的同名字段一致；这是本接收工具支持的机器核对方式，不修改已冻结的 v2 交接规格。旧 v2 Markdown 表格可直接读取，自动核对条数、标签分布、可评／label-only；报告明确 `legacy_table_counts`，其语言说明与其他自然语言内容仍需人工复核。所有 hash 校验只证明对应字节，不能证明来源授权或事实真实性。

### 双遍与证据集合

每条决策先核任务标签域、适用性、候选所属、参照时点及选中证据是否属于可接受集合。合法多证据联合目标保留。集合去重并移除包含更小合法集合的冗余超集；公共 `semantic_decision_key` 比较归一化后的独立决策。原始回执、旧注解与公共契约字节保持不变。

两遍必须有各自的 request／invocation／context 身份、模型 revision、不同 prompt revision 和适当的证据顺序；不能复制一次调用身份充数。语义仍分歧需真实第三遍；失败、空输出、缺原件、错绑定返回 pending，不升级为 G1。核验能检查记录内部一致性，真实 provider 调用的真实性仍需独立审阅，受控测试响应只证明机制。

### 模型回传

沿 fixture v2 的 checkpoint manifest 与 `return_schema_version=2` 双输出字段。核对完成声明、模型 revision、数据 manifest 身份、冻结标签列序、训练／选择分区、逐条概率（有限、归一化、argmax）、当前记录候选 ID 和完整候选对象 hash。失败／弃权必须保留行、空概率与标签以及原因，不可编造结果。可评的正／反关系成功行不得省略证据选择。

`checkpoint_files` 中每个文件都实际核 SHA-256。为避免按文件名猜模型，此接收工具另需 `artifact_roles` 明确列出 `checkpoint`、`config`、`tokenizer` 各自的文件路径，路径须在 `checkpoint_files` 内；缺该映射明确退补。这是机械接收的补充清单，不改变冻结 fixture README，不表示任意文件具备相应模型能力。`training_notes_file`、`predictions_file` 与 manifest 均绑定进回传摘要。回传目录只放声明的文件；checkpoint 文件身份通过不等于可加载、已训练或证据选择正确。

### 结果、退出码与恢复

`report.json` 按 record_id 给 `accept`（机制核验通过）、`quarantine`（身份／格式／引用不符）、`pending`（需补证明／独立核验）与稳定原因码。训练就绪恒为 false，模型质量和真实调用不由该命令背书。CLI 任一记录待补／隔离或模型回传失败时退出 2；包级损坏同样以安全 JSON 错误非零退出，不回显私有正文。退出 0 只表示本次机械核验范围通过。

相同包与相同输出可重跑，report 字节保持一致；任一文件／版本变化与既有报告冲突时拒绝覆盖，使用新的输出目录保存新版本。核验不会重新标注或接收模型调用；原 `label receive` 按记录、版本、phase 与 attempt 恢复，已完成调用不重发。未知结果只查询：

```sh
UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 label status --batch /path/to/batch
# 仅在操作者明确决定另记一次尝试时：
UV_PYTHON=3.12 uv run --locked python -m career_lab.datasets.v3 label issue \
  --batch /path/to/batch --record-id RECORD_ID --phase 1 --retry-unknown
```

`--retry-failed` 仅显式重试已失败记录，`--retry-unknown` 为未确认结果另记 attempt；均不会自动联网。成功 attempt 仍不重新签发。

## 实跑证据与下一步

- `runs/local/095/runbook-merged/export-evidence.json`：基线 `a432b1b` 上中英真实 HTTP 会话→正式签发／导出／校验。每语 1 条关系、14 条评价项，另外两切面零量有原因。该会话由脚本操作，未证明真人质量。
- `runs/local/109/runbook/{zh,en}/`：本次中英回传机制样例，`evidence-final.json`／`review-final/report.json` 保存正式 CLI 核验及恢复的命令、报告与 hash。模型文件为明确合成字节，无实际训练。
- `runs/local/109/runbook/fixture-v2-final/report.json`：直接只读消费未改动的冻结 v2 包，12 条数值 fixture 接受；数据卡只核表格字段，training_ready=false。
- `runs/local/109/063-13/`：逐 DATA 红绿、定向旧测试逐 ID 比较、独立双轴、候选源码 digest、回执与 PR 草稿。完整门禁由总调度持锁安排，本线未运行。

负责方仍需交正式来源／许可、完整谱系／split、实际标注调用、checkpoint 与训练说明；权威来源、真实模型重载、两语模型质量、独立语义采用及 training-ready 继续 blocked。本命令不自动提升这些状态。

