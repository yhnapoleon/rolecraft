# 交接说明

写给第一次打开本仓库的 Agent 与开发者：怎样起服务、怎样检查、契约怎样重导出、哪些文件不能手改、模型回传包在哪、后续还有什么。产品能力与配置变量见 [README](../README.md)。

## 起服务

- 一个 checkout 一套环境：`uv sync --locked` 建 `.venv`，`apps/web` 里 `npm ci`。需要编码器时另建环境：`UV_PROJECT_ENVIRONMENT=<另一目录> uv sync --locked --extra encoder`，默认 `.venv` 不装 torch。
- 三个进程：API（`career-lab serve`，缺省端口 18562）、worker（`career-lab worker`）、前端（`npm run preview` 或 `npm run dev`，缺省 18560，`ROLECRAFT_API_TARGET` 指向 API）。完整命令见 [README · 启动工作台](../README.md#启动工作台)。
- API 与 worker 共用同一数据库、`CAREER_LAB_SCENARIO_CATALOG`（不设只有中文主场景）、`CAREER_LAB_SCENARIO_ARCHIVE`、凭据密钥（`CAREER_LAB_CREDENTIAL_KEY_ID`、`CAREER_LAB_CREDENTIAL_KEY`）与模型配置。改任何一项两个都重启。
- 新 SQLite 库先启动 API，初始化完成后再启动 worker。验收用新数据库与新端口；并行的几条工作线各用自己的端口。
- 默认 `--provider local` 不调用外部模型、不需要 key。真实 provider 与费用须另获授权。

## 检查与门禁

| 层 | 什么时候 | 命令 |
|---|---|---|
| check-fast | 每次提交前 | `.venv/bin/python -m scripts.check_fast` |
| 定向＋逐 ID | 每次交付 | 改动相关的测试文件或 `::ID`；再用 `pytest --collect-only -q` 收集全部测试 ID，与基点提交收集的结果比较，缺失须为 0 |
| 持锁完整门禁 | 合并候选 | 见下 |

**check-fast**：依次跑 `python -m scripts.regression.lint`（前端 biome 新增项、相对基点改动的 Python 文件做 ruff check 与 format check）与 `pytest tests/unit tests/contracts`。去掉调用方的 `CAREER_LAB_*` 与 `PYTHONPATH`，pytest basetemp 用私有临时目录，不与同一 checkout 里的其他运行共用；不需要浏览器与锁。每步打印结果与耗时，任何一步失败退出码为 1。2026-10-12 本机（Apple Silicon，负载约 3.5）实测：lint 23 秒、测试 58 秒（1554 项通过），合计 82 秒；负载约 10 时合计约 97 秒。

**完整门禁**（输出目录必须不存在；同一台机器同一时间只跑一套）：

```sh
OUT=runs/local/gate-$(git rev-parse --short HEAD)
CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.run --output "$OUT" --browser
CHROME_BIN=<chrome-headless-shell> uv run --locked python -m scripts.regression.browser --suite model-flows --output "$OUT/model-flows"
```

- `run` 依次跑 lint、后端全部测试（junit）、前端 Vitest、72 项状态回归、构建、逐 ID 比较（含发布字节保护），`--browser` 再跑 MCP 双语与中英 published-flows（固定用缺省端口 19660／19662）。单独调用 `scripts.regression.browser` 时可用 `--web-port`／`--api-port` 换端口。
- model-flows 默认三段：`linear`、`fusion`、`slots`（回环 JUDGE 与 ASSISTANT 槽）。可选段需 encoder 环境：`UV_PROJECT_ENVIRONMENT=<encoder 环境> uv run --locked --extra encoder python -m scripts.regression.browser --suite model-flows --phases encoder hetero --output <新目录>`；`xlmr` 段另需 `ROLECRAFT_XLMR_DIR` 指向本机下载的 XLM-R base（权重放仓库与云盘之外，登记只能是合成机制）。
- 可选 encoder 检查：`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 <encoder 环境>/bin/python -m pytest -q tests/optional_encoder/check_encoder_v3.py tests/optional_encoder/check_local_encoder.py tests/optional_encoder/check_fusion_registration.py`；XLM-R 冒烟为 `<encoder 环境>/bin/python -m scripts.smoke.xlmr_base --model-dir <目录> --revision <40 位> --out <新目录>`。这些只证明加载与机制，不是质量证据。
- **锁**：门禁对 CPU 负载与端口敏感。本机约定先对机器上登记的同一个锁文件取 `fcntl.flock` 独占锁再跑（macOS 没有 `flock` 命令），例如 `python3 -c 'import fcntl, subprocess, sys; f = open(sys.argv[1], "a"); fcntl.flock(f, fcntl.LOCK_EX); sys.exit(subprocess.call(sys.argv[2:]))' "$GATE_LOCK" sh -c '<上面三行>'`。排队时不另起第二套。
- **基线**：`tests/regression/test-baseline.json` 是逐 ID 基线，只追加、不删改；新测试 ID 在全部合入后由收口线一次追加，并在提交说明里列来源与数量。平台差异只写进 `test-baseline-overrides.json`，每条带原因。
- CI 在 PR 与 push main 时跑核心门禁（不含浏览器），不拦合并；合并证据以本机完整门禁为准，合入树须与门禁跑过的树相同。

## 契约重导出与重签

公开契约是 `docs/contracts/expansion-v3/`，`revision.txt` 为 `expansion-v3-` 加 `manifest.json` 的 SHA-256。manifest 记录的源码指纹（`export.py` 的 `_implementation_files`）覆盖：

- `src/career_lab/contracts/` 下全部 `.py`；
- `cli.py`；`api/` 的 `app.py`、`v4_extensions.py`、`vertical_runtime.py`、`vertical_reads.py`、`v4_config.py`、`public_materials.py`、`lifecycle_integration.py`、`evaluation_runtime.py`、`registered_models.py`、`reviews_v2.py`、`workspace_integration.py`、`feedback_integration.py`、`role_snapshot.py`、`private_roles.py`、`modules.py`、`v2_routes.py`；
- `runtime/` 的 `model_slots.py`、`model_adapter.py`、`role_snapshot.py`；`jobs/worker.py`、`jobs/repository.py`；`rubrics/registry.py`；
- `storage/` 的 `v2_tables.py`、`v2_store.py`、`v2_jobs.py`、`v2_snapshot.py`、`v2_lifecycle.py`、`v2_remap.py`、`object_plans.py`、`reference_graph.py`、`record_invariants.py`；
- 手写文档 `docs/contracts/expansion-v3/` 的 `compatibility.md`、`module-interfaces.md`、`consumer-request-resolution.json`（以文档指纹记录）。

改这些文件就要重导出。一波里只由一条获授权的线做一次，其他线不碰。步骤：

1. 在 `src/career_lab/contracts/v2/manifest_history.py` 的 `MANIFEST_HISTORY` 末尾追加一条：`previous_contract_revision` 写当前 `revision.txt` 的值，`integration_changes` 用新键写清变化。旧记录一字不改。
2. 指纹范围新增文件时，`export.py` 的 `_implementation_files` 与 `tests/contracts/expansion_v3/test_export_reproducible.py` 的 `IMPLEMENTATION_INPUTS` 同步加入。
3. 生成并核对（`OUT` 为新目录）：

```sh
PY=.venv/bin/python
OUT=runs/local/regen-<标签>
$PY -m career_lab.contracts.v2.export --output "$OUT/a"
$PY -m career_lab.contracts.v2.export --output "$OUT/b"
diff -r "$OUT/a" "$OUT/b"                                   # 必须无差异
$PY -m career_lab.contracts.v2.export --output docs/contracts/expansion-v3
diff -r "$OUT/a" docs/contracts/expansion-v3                # 只应剩 Only in：drafts/ 与三份手写文档
$PY -m career_lab.contracts.v2.engineer_export --output "$OUT/eng-a"
$PY -m career_lab.contracts.v2.engineer_export --output "$OUT/eng-b"
diff -r "$OUT/eng-a" "$OUT/eng-b"
rm -rf docs/contracts/engineer-review-v1                    # 同目录重导出只接受逐字节相同
$PY -m career_lab.contracts.v2.engineer_export --output docs/contracts/engineer-review-v1
cd apps/web
../../$PY src/features/workspace/generate_types.py ../../docs/contracts/expansion-v3/manifest.json --host --output "../../$OUT/ts-raw.ts"
node_modules/.bin/biome format --stdin-file-path=src/contracts-v2.ts < "../../$OUT/ts-raw.ts" > src/contracts-v2.ts
cd ../..
$PY -m scripts.regression.release_identity --check            # 变化应只在 docs/contracts/expansion-v3/ 内
$PY -m scripts.regression.release_identity --refresh
$PY -m scripts.regression.release_identity --check            # 0 problems
```

`--refresh` 按当前字节重算全部受保护文件，会把意外改动一并签进去，所以先 `--check` 看清变化。`tests/contracts/expansion_v3/test_freeze.py` 核对 schema、examples、OpenAPI 与冻结一致，`test_export_reproducible.py` 核对导出确定、发布历史保留与受保护字节不变。随后跑 check-fast 与完整门禁；`main` 在合入前前进时，在历史末尾再追加一条指向 `main` 当时的修订并重导出。

## 生成文件，不手改

| 文件 | 由谁生成 |
|---|---|
| `docs/contracts/expansion-v3/` 的 `schemas/`、`examples/`、`openapi.json`、`errors.json`、`manifest.json`、`revision.txt` | `career_lab.contracts.v2.export`；`drafts/` 是历史冻结稿 |
| `docs/contracts/engineer-review-v1/**` | `career_lab.contracts.v2.engineer_export` |
| `apps/web/src/contracts-v2.ts` | `generate_types.py --host` 加 biome 格式化（头注释记 manifest SHA-256） |
| `tests/regression/release-identity.json` | `scripts.regression.release_identity --refresh`；`commit`、`scenarios`、`scope` 不变 |
| `tests/regression/test-baseline.json` | 只追加（见上） |
| `scenarios/` 下场景包、补练变体与安装包 | 场景工具生成，按 hash 受 release-identity 保护；内容改动走场景发布，重绑只用 `python -m career_lab.scenarios.v2.rebind` |
| `docs/data/return-v3/SHA256SUMS` | 包内任何文件改动后重算（`shasum -a 256` 格式，列全包、不列自身），再跑 `python3 -I docs/data/return-v3/check_package.py docs/data/return-v3` |

## 模型回传 v3 包

`docs/data/return-v3/` 是发给技术负责方的补充包，入口 [README](data/return-v3/README.md)：线性回传、编码器回传、融合选择记录、按 split 封存的数据包、v3 预测行、一次性 test 打开，以及参考导出脚本、金标向量与只用标准库的自检脚本。冻结交接包 fixture v2 一字节不变。登记、复核与导出命令见 [W07](data/expansion-v3-w07.md)、[W08](data/expansion-v3-w08.md)。每次打开封存 test 须项目负责人在对话里确认一次，CLI 不接受绕过参数。

## 后续清单（本波不做，触发后再派）

| 项 | 触发条件 | 要补的工作 |
|---|---|---|
| 五分类 head 的接收与显示 | 负责方书面答复「五分类走独立 head」 | criterion 线性与编码器注册、五类指标与 `rubric_version` 复核、criterion 预测行格式发布；14 项逐项「模型建议（不计分）」与冲突、未覆盖、待核验状态；model-flows 加 criterion 段。契约可选字段已保留，预计不需二次重导出 |
| Judge SFT 输入格式导出 | 负责方答复「做 SFT」并索取格式 | Judge messages 抽成纯函数（线上 prompt hash 不变），授权导出新增 `judge` 投影（含规则界与声明决定、`PROMPT_VERSION`、不含 gold），W07 手册补命令。模型服务接入已具备：JUDGE 槽配 `openai_compatible` 即可 |
| GRPO | 负责方决定执行 | 我方无接收工作，adapter 同样以 OpenAI 兼容服务接入；未执行时报告如实写「未执行」 |

补做时沿用已保留的测试编号，不替负责方训练、不运行其命令、不新增费用。

## 依据文档

以下文档在项目本地维护，不在仓库内，维护人均为项目负责人（产品侧）：

- 项目定义：范围、分工与产品决定的唯一主维护位置。
- 模型与数据准备事项：给技术负责方的交接说明与 fixture v2 冻结包。
- 143 模型承接波任务书：本波分线、接口、测试编号与 §8 后续清单。
- 模型承接波各线完成回执：各线证据与手册段落。
