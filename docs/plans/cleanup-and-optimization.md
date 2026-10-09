# 冗余清除与后端优化方案

状态：方案已批准，按独立批次执行。执行基点为 `2c07160b5e829ac08afb8a31667440bbda72df73`（2026-10-09），066分支已ff-only同步，包含后端协议迁移、工程师修复与Python格式化。原方案基点9a39cc7及其基线保留；下列资产与代码规模已按新main重新统计。浏览器每次运行前检查19660/19662空闲。

## 1. 目标与不变量

目标是减少失效入口、重复过程资产和后端维护负担，同时保持已交付的工作行为、历史读取、权限、幂等、评价结果与产品方向。当前运行与历史取证依赖分别处理，文件大小不构成删除依据。

依据为项目定义 2026-10-08/10-09、启动简报 10-08、场景与训练闭环第 2/4/5 节、063 现状核对及 W14 的 063-02；协议与存储设计沿用[架构优化方案](architecture-optimization.md)。063 原分组是功能阶段建议；本方案只涵盖质量阶段，当前边界以本方案为准。AIPM 统一岗位、三同事帮助方式、条件预览与明确动作改变状态的边界不变；新增工单分流场景不在本次实施内。

必须保持：

- P0/P1 全部保留，未接通的参考 Agent、场景编译、技能与优化等能力不能列作死代码；不启动新功能任务。
- 原 v4 为唯一用户根界面；`apps/web/**` 全部由前端质量线维护，本线仅只读盘点并运行测试。
- 旧会话、作品、提交、反馈及引用可读；历史读取不重新调用模型，`retries=0`，规则核实／等待模型状态不变。不关闭 v1 创建、动作或写接口。
- 已发布内容逐文件不变，旧发布、审核身份不变。只用正式 rebind CLI 产生新包，禁止对旧目录就地修补或全局替换路径。
- 不新增 skip、不削弱断言、不改测试目的。错误分类和凭据安全修复是下文明确列出的行为修复，单独提交；其余批次必须行为等价。
- 不调用付费模型，不 push、开 PR、合并或部署。按当前批准范围执行；浏览器运行仍检查共享端口空闲。

用户故事：维护者能找到唯一有效入口；现有用户能继续原工作并读取历史；新签发凭据不会由数据库摘要推导；调用者收到兼容的业务错误及不泄漏内部内容的服务端错误；审核者能以完整测试 ID 和固定反馈证明变化边界。

## 2. 基线、口径与证据

独立 `.venv` 使用 Python 3.12.13，依赖来自 `uv sync --locked --python 3.12`；前端依赖独立 `npm ci --prefix apps/web --no-audit --no-fund`。未复用其他工作区数据库、凭据或 node_modules。

已运行 `.venv/bin/python -m scripts.regression.run --output runs/local/066-planning/baseline`，未加 `--browser`：后端 **2140 passed / 31 skipped**（2171个ID，566.39秒），前端 **224 passed / 7 skipped**（231个ID），72项状态检查、严格TypeScript及生产构建通过，渐进lint **0新增**（前端原1462项），仓库原基线比较 **0 problems**。后端仅原AnyIO弃用警告。

完整XML/JSON及日志保留在 `runs/local/066-planning/baseline/`，开工全部ID与结果另固定为 `test-results.json`，附源码commit及文件SHA的 `receipt.json`。仓库内旧 `test-baseline.json`只有2109个后端/226个前端ID，本轮新增覆盖也必须进入后续比较，不能仅依赖它。**未运行浏览器、正常v4中英实操或真实MCP，本轮不宣称这些通过**；执行前获放行后补跑。

原方案代码指标（9a39cc7）来自同一项目工具 `.agents/code_metrics.py <worktree> src`：239 个 Python 文件，24,919 行，1,250 个函数；参数／返回类型标注 14%／9%；分号压行 937（37.6/千行），超过 120 字符行 2,546（102.2/千行）；含 logging 文件 0；函数内 import 290；超过 100 行函数 14，超过 200 行 2。最长为 `create_app` 277 行、`V2Store.execute` 227 行。格式化后这些数字必然变化，不能把总协调的格式化收益归到本线。

当前2c07160指标（同一工具，格式化收益不归本线）：

```text
files=245 lines=44611 funcs=1265
arg_annot=16% ret_annot=12%
semicolon_lines=436 (9.8/kloc) long>120=344 (7.7/kloc)
files_with_logging=0 function_level_imports=291
funcs>100 lines=68 funcs>200=22 top5=[(707, 'v2_store.py', 'execute'), (564, 'seed.py', 'build_seed'), (419, 'app.py', 'create_app'), (392, 'content.py', 'materials'), (346, 'export.py', 'export_snapshot')]
```

资产统计限定 `git ls-files` 中实际文件，bytes 为原字节长度，行数为文本行数，二进制无行数；不包含依赖、缓存和本地运行结果。全部逐文件路径、bytes、行数、SHA-256、重复组与静态导入入边保存在本机 `runs/local/066-planning/inventory.json`；场景读取结果在同目录 `historical-pack-readability.json`。它们是本次取证输出，不是新增长期状态台账。Git 基点足以重建本节统计。

| 对象 | 文件数 | bytes | 文本行数 |
|---|---:|---:|---:|
| `scenarios/pm_pilot/v2/installed` | 1,057 | 17,454,345 | 483,772 |
| `scenarios/pm_pilot/v2/candidates` | 294 | 4,984,675 | 134,458 |
| `scenarios/pm_pilot/v2/variants` | 199 | 3,174,257 | 89,171 |
| `apps/web/tests/screenshots` | 138 | 15,346,558 | 图片／GIF与少量 JSON |
| `docs/reports` | 41 | 1,625,818 | 12,404 |
| `docs/contracts/expansion-v3/drafts` | 143 | 622,283 | 24,974 |
| `docs/integration` | 7 | 222,416 | 4,458 |
| `tests/regression` | 20 | 1,773,349 | 9,312 |

证据方法：精确路径、basename、符号和动态 CLI 入口搜索；AST 导入图辅助筛选；读取 catalog、manifest、归档恢复、冻结测试和实际测试体；逐个调用现有 `load_immutable_content`。**静态零入边不等于死代码，历史包能读取也不等于旧会话全链路通过。** 本轮未枚举所有已部署数据库和外部归档，不能证明任何旧代次已无用户依赖。

## 3. 场景包：全部保留，删除条件单独列明

### 3.1 分代清单与引用分类

下表路径均相对 `scenarios/pm_pilot/v2/`。R 为当前运行依赖，T 为当前回归测试，H 为历史证据或冻结测试；一项可以属于多类。

| 对象 | 文件／bytes／行 | 证据与引用类别 | 分类、风险与验证 |
|---|---|---|---|
| `installed/current.json` | 1 / 1,697 / 42 | R：`api/vertical_runtime.py` 默认入口读取它；指向 candidates 新协议包 | **保留**；删除即不能默认启动。验证默认 CLI/HTTP及双语目录 |
| `candidates/protocol-v1-2.9.6` | 294 / 4,984,675 / 134,458 | R/T：current 和 `tests/regression/published-catalog.json` 指向其六包；H：release 引用原审核 | **保留**。目录名不表示未启用；禁止为了美观移动或与 installed 合并 |
| `installed/rubric-v2-a577-2.9.6` | 288 / 4,773,642 / 132,136 | T：`test_standard_runtime_install.py`、`test_installed_variants.py`、`test_protocol_migration.py`；H：`published-catalog-legacy.json` 为回退入口 | **保留**。六包旧发布身份和新协议迁移父输入均有用途；六包启动／回退／历史材料与反馈读取分别验 |
| `installed/rubric-v2-a577-2.9.5` | 288 / 4,773,636 / 132,136 | T：`tests/e2e/test_w06_standard_legacy.py`、`w02/test_rebind_tooling.py`；H：review packet、字节门禁 | **保留**。旧标准入口与重绑工具的兼容测试不能全部替换成最新版 |
| `installed/rubric-v2-c2-2.9.4` | 288 / 4,773,732 / 132,136 | H：`reviewed-options-2.9.4.json`、`content-continuity-2.9.6.json`、`docs/integration/v4-fixed-inputs.json`、release-identity | **保留，暂停删除**。静态未见直接运行调用，未知旧库仍可能绑定其 hash |
| `installed/rubric-v2-c2-2.9.3` | 96 / 1,579,162 / 43,850 | H：continuity、固定输入与 release-identity | **保留，暂停删除**；同上 |
| `installed/rubric-v2-c2` | 96 / 1,552,476 / 43,472 | H：continuity、固定输入与 release-identity | **保留，暂停删除**；同上 |
| `variants/pm_pilot_urgent` | 92 / 1,497,017 / 43,680 | T/H：变体作者包、变体／双语校准测试及原审核 lineage；不是 installed 的别名 | **保留**；不能用内容近似的当前发布物覆盖作者包 |
| `variants/pm_pilot_capacity15` | 92 / 1,499,615 / 43,684 | T/H：同上 | **保留** |
| variants 其余 15 文件 | 15 / 177,625 / 1,807 | R/T/H：catalog、reviewed-options、review-packet、reviews；`api/v4_extensions.py`、`scripts/regression/published.py`读取审核及连续性 | **保留**；逐语言、场景、审核身份验证，历史记录不改签 |

32 个 manifest（installed 22、candidates 6、variants 4）已用真实历史读取器逐个通过完整成员 hash／材料引用校验。`ScenarioReadCatalog.resolve` 在当前 binding 不匹配时只访问 `<archive>/<scenario_hash>`，并重验 runtime/evaluation binding；它不会自动去 Git 找回删除的包。初始化只自动 preserve 当前装配的包。Git 中仍有文件不能保证正常用户历史可读。

整个 v2 场景树的精确重复中，`retrieval-calibration.json` 有 17 份相同的 502,239 bytes（多余副本共 8,035,824 bytes）；`materials.json` 有 6 组共 34 份，组内重复合计 6,164,716 bytes。此统计包括基础作者包，范围大于上表三目录。这些 JSON 是 manifest 成员；英文校准测试还读取 selected threshold，loader 和历史 reader 都校验材料及片段。分类为**保留已发布副本**，未来作者构建仍可生成它们；本轮不引入共享 symlink、跨包查找、按请求生成或重新序列化，均会影响包内路径、身份或历史可移植性。

### 3.2 未来可重现保留方案及删除停点

当前没有场景删除批次。若后续要释放上述旧目录，须另外完成以下全部条件后再评审具体目录清单：

1. 固定每个原 manifest 原字节、全部 FileRef、语言、content/runtime/evaluation/review 身份和 Git commit；列出真实已知数据库与快照绑定，未知部署继续作为保留理由。
2. 通过现有 `docs/integration/archive_scenarios.py <固定commit> --source-root <精确旧包根> --archive <隔离目录>` 在干净 clone 逐 hash 恢复，证明无需工作区外 tar 或临时文件。该命令一次处理一个根；不能只恢复中文主包。
3. 若变更当前包，只用 `python -m career_lab.scenarios.v2.rebind --protocol scenario-release-v1 …` 生成全新目标；逐成员比较业务字节。先生成并验证新包，再迁移 R/T 入口，最后删除已无依赖的目录。H 类原字符串与身份原样保留；为其提供可运行恢复步骤。
4. 归档必须在用户访问前可用，支持已有数据库、全新安装、浅 clone／缺历史对象的明确失败、离线回退；保存旧会话材料、引用、旧反馈和新旧修订的同值对照。不在 HTTP 请求中拉 Git、重建包或调用模型。
5. `release-identity.json` 目前保护 installed 的 1,056 文件及 variants 199 文件；不得仅移除清单项使删除通过。若获准迁移为历史夹具，须等强校验原字节恢复并由 Claude 接受门禁迁移；不能改变原测试目的。缺任何条件即保留目录。

这是一条有待实现和证明的恢复路径，不是本轮已证明可删的结论；本轮不部署归档、不读取或迁移他人数据库。

## 4. 过程资产及回归夹具

所有 Git 历史归档均保留原 blob，使用固定完整 commit 的 `git show <commit>:<path>` 恢复并验 SHA-256；现有文档链接必须同步改为原 commit 的历史链接／恢复说明。只清理工作树，不改写 Git 历史。若干净完整 clone 无法恢复或外部引用要求原路径，暂停该对象。

| 对象 | 规模 | 证据 | 分类与实施约束 | 风险、回退与验证 |
|---|---|---|---|---|
| `apps/web/tests/screenshots/**` | 138 文件 / 15,346,558 bytes | web README、motion-acceptance.md、frontend-style.md 引用；旧脚本会生成截图，当前浏览器门禁写入 output/screenshots | **保留，本线只盘点，交前端线决定**；138 文件全部在排他边界内 | 本线不删截图、不改 web 链接、不计其收益；原动效和布局证据仍可读 |
| `docs/reports/controlled-v2-dev.json` | 1 / 669,539 / 3,627 | report generator 从 `runs/controlled-v2/development.json`读输入，历史报告／计划引用本文件；未发现 src/tests 读取本路径 | **归档到 Git 历史即可，条件候选**；保存原 commit/blob/hash，修复 controlled-v2-results 和相关工程计划的历史引用 | 不重新训练“还原”旧指标；原始 timing/硬件信息不可由当前运行重造。恢复逐字比较，报告所引数值一致 |
| `docs/reports/controlled-v2-freeze.json` | 1 / 629,666 / 2,440 | `test_freeze.py` 与 `test_core_wiring_legacy_protection.py` 对照 80cf1f6 原字节 | **保留** | 删除或精简会破坏实验冻结；不削弱两测试、不重签 freeze |
| `docs/reports/*.xml`（全部 14 份，详见附录） | 14 / 89,193 / 14 | 历史 JUnit；无 src/tests 读取，实施报告及计划有引用 | **归档到 Git 历史即可，条件候选**；保留历史通过数及完整恢复入口 | 当时 PG／真实模型结论只能追溯当时记录，不能用本轮测试顶替；逐文件 SHA 与链接验证 |
| reports 其余文件 | 25 / 237,420 / 6,323 | 6 MD、1 CSV、其余 JSON 保留结果、来源、真实调用与环境边界 | **保留**；体积较小且不重复，避免切断独有实验来源 | 原引用可达；不改研究结论 |
| `docs/integration/v4-fixed-inputs.json` | 1 / 200,411 / 3,990 | W02–W06 当时来源清单；仅 `w14-native-workbench.md`引用，无当前运行／测试读取 | **归档到 Git 历史即可，条件候选**；保留精确提交、blob/hash和恢复命令，更新唯一工程说明引用 | 不把原清单重写为当前源码；完整原文可恢复、校验所有原键值 |
| `docs/integration/rebind_runtime.py` | 1 / 6,387 / 149 | 无 src/scripts/tests 或仓库文档调用；末尾逐文件回写旧目录，现行 prepare 已调用正式 CLI；项目历史偏离排查只作历史引用 | **归档到 Git 历史即可**，移除活动的旧就地补丁入口 | 不运行它；保留历史 commit 定位，正式 prepare/rebind CLI 测试继续通过；回退用原 blob |
| integration 其他 5 文件 | 5 / 15,618 / 319 | `prepare_scenarios.py` 为测试生成六包；`archive_scenarios.py`为历史保留路径；`check_public.py`与两份说明 | **保留** | 当前 CLI、旧 hash 归档及说明链接可达；不让历史工具成为当前推荐重绑命令 |
| contracts drafts 的 examples | 21 / 20,024 / 790 | 两个契约测试文件直接读四类 DatasetRecordV2 和 CriterionInput；全部受 release-identity 保护 | **保留**。当前实际直接读 5 个 JSON，但本轮不剪断原 manifest成员关系 | 不用现行模型导出同名 JSON 冒充旧例，避免自证兼容；原测试 ID／字节检查 |
| drafts schemas / manifest / revision / tar | 122 / 602,259 / 24,184 | schemas 119份 494,591 bytes；manifest 25,677；revision 71；tar 81,920（12成员共51,437）；原 manifest与 release-identity绑定 | **保留，暂停删除**；“draft”不代表无需保全 | 日后若迁移，须先设计精确历史恢复与原冻结目标等强测试；不通过删 143 个门禁项清理 |
| `tests/regression/fixtures/w05-r10-owned-source.tar` | 1 / 542,720 / 二进制；63成员 | run.py 通过 W02_W05_R10_ARCHIVE 指定；`test_evaluation_facts.py::test_frozen_w05_change_rules_consume_actual_adapter_facts` 校验整个 tar 的 SHA，分别在中英运行，读取其中原 rules_v2.py | **改为生成**：仓库保留确定性 gzip，门禁在临时目录解压为原 tar，原测试体及 SHA 断言不变 | 本机内存试压 mtime=0 为114,637 bytes，预计节省428,083；最终 gzip 另锁hash。防截断/损坏；恢复后原 tar SHA 必须是 `99297d18c80e69248624b7ad2177729c5ac2f3ccb19afeedb138f3d799030bf3`；禁止用当前规则替换历史规则或新增skip |
| `feedback-baseline.json` | 1 / 31,381 / 980 | test_feedback_equivalence 与评价版本注册锁定摘要 | **保留原字节**；不能自动生成 expected 与 actual 同源 | 完整输出逐项等价及故意变异反例；不只比总分 |
| `engine-cases.json` | 1 / 70,021 / 1,178 | test_protocol_migration 的真实 FeedbackEngine 四组14项对照；有冻结摘要 | **保留原字节** | 实际反馈代码导入与输出变异门禁仍通过 |
| `release-identity.json` | 1 / 300,386 / 1,952 | compare.py 的业务／旧发布／协议保全门禁 | **保留**；不以体积或源码去重为由去项 | protected_changes 仍逐文件检查；本方案不修改保护集合 |
| `test-baseline.json` | 1 / 329,106 / 2,397 | 逐测试 ID 与 outcome基线 | **保留**；当前发布基线与本次开工基线双重比较 | 不重新生成以吞掉失败、缺失或跳过 |
| `frontend-lint-baseline.json` | 1 / 439,403 / 1,145 | Biome诊断多重集合，行内容参与身份 | **保留，前端线管理迁移**；虽在 tests 下也不由本线重写 | 同步 main 后确认归属与新基线，不能清空旧债 |
| `fixtures/prior-cycle-adoption.json` | 1 / 17,011 / 545 | test_revision_adoption 回放父版本真实Gateway快照 | **保留原件**；用当前逻辑生成会失去历史回归目的 | 旧轮作品采用及合法快照恢复结果不变 |
| regression 其他 13 文件 | 13 / 43,321 / 1,115 | 测试实现、fixture builder、两个catalog及兼容转发 | **保留** | 逐ID、导入真实生产代码与旧/新启动对照 |

确定性压缩只改变存储形式；验收仍读取原始 tar。此方式保留完整冻结身份，优于删除 62 个“未直接执行”的成员后改写整个 tar 摘要。不得额外引入下载服务或运行时 Git/network 依赖。

## 5. 死代码逐文件核查

扫描 245 个源文件的导入图，再核对 pyproject console scripts、`python -m`入口、动态字符串、文档和场景来源清单。以下为全部“无静态入边且非 __init__”的 10 个文件；其中多数有真实用途。文件大小均为 1 文件的 bytes／行。

| 文件（相对 src/career_lab） | bytes／行 | 运行、测试外引用、P0/P1 判断 | 分类与验证 |
|---|---|---|---|
| `api/workspace_v2.py` | 193 / 5 | 无当前内部导入；`docs/modules/expansion-v3/W03.md:7`正式说明推荐此兼容导入；只转发实际 workspace 扩展 | **保留兼容入口**；不能把公开转发当死模块 |
| `storage/workspace_v2.py` | 400 / 10 | 无当前内部导入；固定输入清单记录，文件明示兼容导出 V2Store/ObjectWrite/Mutation，不拥有另一个存储层 | **保留兼容入口**；小型别名有恢复价值，后续先迁移已知消费者再决定 |
| `evidence/v2/review_ports.py` | 2,236 / 50 | 无 src/tests/scripts导入或 ReviewAuthority 调用；唯一类是旧 prototype Protocol，文件明确禁止生产实现；不承载待接 P1。26个包的历史source描述与固定输入提及；原件已在固定 W05 tar 内 | **归档到 Git 历史即可，候选死代码**。只删活动同名文件，不删 tar 成员或来源记录；在干净clone验证六包、新旧反馈、历史 tar测试及正式rebind，确认没有动态读取才执行 |
| `scenarios/v2/authoring/evaluation.py` | 7,930 / 195 | 当前无 import／CLI／测试入口，固定输入记录其来源；提供离线评价安装能力。正式 rebind 是现行重绑入口，但不能证明该作者能力被全量替代 | **保留并标明旧作者工具边界**。属于需核实替代能力的工具，不能据零入口删掉 P1 可能需要的发布能力 |
| `cli.py` | 5,562 / 141 | pyproject `career-lab` 指向 main | **保留**，CLI help / demo / serve / worker |
| `engineer/__main__.py` | 117 / 5 | `python -m career_lab.engineer`进入engineer.cli；该cli另由console script与此入口引用，062修复已合入 | **保留**；实际help与任务包回归 |
| `datasets/v3/__main__.py` | 48 / 3 | `python -m career_lab.datasets.v3`，P0数据接口 | **保留** |
| `delegations/__main__.py` | 919 / 31 | `python -m career_lab.delegations`，已有外部Agent服务 | **保留** |
| `experiments/v3/training/__main__.py` | 46 / 1 | 模块 CLI，技术方训练／实验接点 | **保留**；本线不运行真实训练 |
| `models/v3/registry_cli.py` | 5,166 / 116 | 可 `python -m`执行的注册命令，P0模型接入；文件末尾 main | **保留** |

不将 `api/reviews_v2.py`、`workspace/service.py` 中明确报错的旧构造函数按单文件删除：同文件还有当前使用的计划／反馈逻辑，拒绝旧私有事务入口也是安全边界。方法级清理若无外部兼容证明则保留。删除计划目前仅一份源文件的条件候选；没有“整目录未挂载就删”的批次。

## 6. 代号、可见文案与版本

原方案固定口径 `(?i)\bw(?:0[0-9]|1[0-5])\b` 在 src Python 中命中 274 次、236 行（包含 export 的历史兼容描述，不能沿用约182处的估计）。按用途分类，禁止一键替换所有 Wxx：

| 对象 | 分类与拟处理 | 兼容边界及验证 |
|---|---|---|
| 注释/docstring中的工作线名 | **保留代码，删除过期协作说明／改为领域名称**：workspace、scenario、feedback、delegation、store 等 | AST剔除docstring后逐文件相同；仍保留权限、版本、未安装状态解释；不改字符串常量／错误消息 |
| `engineer/cli.py` help 和 `engineer/pack.py` 中英说明、`delegations/openai_tools.py` help、`scenarios/v2/__main__.py` help | **保留能力，替换用户可见内部代号**：私有委托配置／private delegation configuration、场景校验工具等 | 同步062后按实际文本逐条列diff；文案之外命令、参数、文件格式不变；中英帮助和任务包快照，若有测试更新只改获批显示文字预期 |
| `api/reviews_v2.py` 的 `module_unavailable` 消息 | **保留原公开消息**，与本轮错误兼容约束一致；其代号作为明确暂留项 | 不以命名清理改变已公开业务错误；需要独立消息兼容决定才改 |
| `mcp/protocol.py INFO.version='w06-development-1'` | **替换仅对外软件版本来源**，拟用 `importlib.metadata.version('career-lab')`（本基点0.1.0）；保持 name=`rolecraft-workspace` | 版本元数据只表示安装包版本；不代表全部能力完成。初始化 serverInfo 版本变化单列，protocolVersion/capabilities/tools/schema/request_id 与恢复规则不变；stdio 和 HTTP MCP实测 |
| `w02-test`、`w05-c8-feedback` hash盐、`w04-bilingual-v1`提示修订、`rules-v4-rubric-v2-c2`、`owner='W05'`、data release协议和 source_inputs | **保留稳定身份** | 改名会改变测试/反馈ID、提示来源、协议解析或发布身份；不伪装成纯命名。只更新解释性注释 |
| `app.state.w06`等内部属性 | **保留，待有真实维护收益再迁移** | factory/clients可反射使用，别名迁移不能凭搜索少就承诺无影响 |
| 按工作线／评审轮命名的测试 | 64个 `test_*.py` / 653,722 bytes / 9,512行；目录层含编号另计。**本轮全部保留文件名与测试名** | 旧→新测试 ID 映射为恒等映射；不为视觉整齐引入成百ID迁移。新测试用领域名。未来真要rename须导出每个参数化node ID一一映射、测试体AST相同、先过旧基线再迁移；本轮不更新旧ID基线 |

MCP版本的预期差异仅 JSON-RPC initialize 响应中 `serverInfo.version`，不是 HTTP 状态变化，不新增工具或权限。

## 7. v1 与存储依赖

### 7.1 v1 保留范围

保留 `api/app.py` 的 v1／v2 分流与 `SessionStore`、旧 scenario loader/reducer/visibility、TrainingService、runtime loop、feedback/timeline/evidence/relation 读取及其 contracts、jobs。它们仍支持真实 v1 创建/写入及旧会话读取，不能只保留几个模型就删后端。原五份契约和 v1场景字节锁、旧研究freeze保持。验证创建 →动作 →测试 →作品 →提交 →worker反馈 →旧反馈／证据／时间线读取及重开库；新v2修订和旧轮采用不引入新的周期拒写。

### 7.2 反向依赖与函数内 import

| 对象 | 规模与实际边 | 方案、风险与验证 |
|---|---|---|
| `storage/v2_store.py` | 137,223 bytes / 3,082行；`begin_role_execution`由 `begin_role_execution`依赖 api.FixedRoleSnapshotPort、runtime.ContextPort及role_memory.RoleTurn | **保留事务，降低依赖的后续候选**：先将无HTTP依赖的 FixedRoleSnapshotPort移到现有角色runtime职责层，api旧路径保留转发；只解决 storage→api 边。更进一步把snapshot capture注入store涉及私有执行seal/授权时窗，暂不做 |
| `api/role_snapshot.py` | 8,969 bytes / 217行；读取store固定历史、构造RoleFrame | 迁移纯适配逻辑，保留原class身份/方法行为；不能将模型调用带入事务或把授权复核上移。入口与历史快照、撤销竞态和收到分享边界测试 |
| `storage/role_memory.py` | 29,118 bytes / 808行；memory_from_generation导入 runtime.context_v2.role_text | **保留暂缓跨层搬迁**。双语memory文字进入固定上下文；抽公共文本会触及prompt hash、模块循环，收益不足以支持本轮扩大重构 |
| `v2_snapshot.py`、`v2_remap.py`等纯依赖 | 局部导入中含 sqlalchemy IntegrityError、dataclasses.replace、contracts.projection等 | **保留实现，低风险提升import到文件级**；优先核对 v2_store.py 的dataclasses.replace、v2_snapshot.py 的IntegrityError、role_memory.py 的dataclasses与TypeAdapter；逐条检查导入环及可选依赖，冷进程import、CLI和全量门禁通过后才接受 |
| `role_memory`↔`v2_store`，`object_plans`的 ObjectWrite 等 | TYPE_CHECKING和函数内延迟import已用于消除循环 | **保留必要延迟import**；不能为降低290计数恢复循环，不能移动事务边界 |
| `V2Store.execute` | 707行 | **保留核心编排**。已拆object_plans/reference_graph，继续保留单事务内最终校验、锁顺序和一次提交/回滚，不机械拆短 |

低风险import调整与适配器搬迁分批；若冷启动/CLI产生循环或历史结果变化，撤回该批。存储对runtime的剩余依赖如实列出，不声称完全分层。原路径转发保留用于旧测试/外部调用；新文件完整类型、Ruff 100列、E/F/I/UP/B，不新增业务抽象或第二个存储层。

### 7.3 硬编码版本和路径

保留 `installed/current.json` 作为唯一默认场景指针及明确 `scenario_root`／环境配置优先级；默认相对 archive 路径、`scenarios/pm_pilot/v1/scenario.yaml` 和旧 CLI 参数不变。当前 `v4_extensions.PracticeCatalog`及 `scripts/regression/published.py` 写死2.9.0原审核/2.9.6连续性属于已知发布协议债务，替换需发布描述与正式CLI导出，当前不重写原审核。

只收敛**当前代码重复解析同一个指针**且返回相同值的部分；历史commit、场景revision、评价版本和已冻结source paths不抽成“永远最新版”常量。`FastAPI version='0.2.0'`参与冻结OpenAPI，保留；MCP服务软件版本按第6节单独变更。`scripts.regression.lint`的原git基点保留，新执行批次额外用明确批次base检查；不随意更新基线吞掉问题。

## 8. 错误分类与安全日志：默认保持，显式升级

按074续行决定，默认ValueError（含ValidationError）保留父提交1881ed5的422及原error/code/details；KeyError保留404及原not_found正文。ProtocolError、CodedValueError、RequestValidationError、HTTPException的状态、消息、details、headers不变。不以异常消息猜类型，不将未分类ValueError/KeyError全局转500。输入错误或资源缺失的兼容遗漏直接恢复父版响应并补对照，不再触发停点。

仅下表四个明确持久化读取位置把异常显式标为InternalFailure，HTTP返回500及`{"error":"internal server error","code":"internal_error"}`。未被既有handler分类的异常（HTTP-11）也统一此JSON500，不重试、不记录内部文本。其它已分类异常保持父版，包括既有module_response_invalid 503；不将其扩大为500。

| 显式升级位置 | 内部错误证据 | 父版响应 | 新响应 | 参数化测试样本 |
|---|---|---|---|---|
| api/feedback.read_evidence读取report.sources | report来自保存的feedback对象，用户只选择criterion/evidence | 404 / not_found | JSON500 / internal_error | persisted_sources_missing |
| 同处读取ref.observed_at_seq及report.as_of_seq | 已保存证据坐标缺键；选择不存在仍原404 | 404 / not_found | 同上 | persisted_coordinate_missing |
| storage/sessions.get_state的WorldState.model_validate_json | raw来自数据库session或snapshot，非请求内容 | 422 / invalid_request，完整ValidationError正文 | 同上 | persisted_state_invalid |
| workspace/imports._legacy_structure.source_ref的EvidenceRefV2校验 | citation来自snapshot中已存test记录，raw仅提供查询id/version | 422 / invalid_request，完整ValidationError正文 | 同上 | persisted_source_ref_invalid |

### 父版HTTP样本矩阵

`tests/regression/http_samples.py`只构造正式HTTP请求及隔离数据库损坏；`http-parent-responses.json`由完整1881ed5归档源码和锁定依赖执行产生，不由候选实现生成expected。单一参数化测试`test_http_matches_fixed_parent_response`对以下12条默认样本逐字段比较status、body与全部响应headers；上述4条显式升级样本断言固定JSON500完整响应。原HTTP-01–08基线另保留，覆盖ProtocolError、CodedValueError、外层请求验证、Gateway请求、资源选择、404/405和认证等。

| 样本 | 父版与候选均保持 |
|---|---|
| empty_pilot_plan：v1 update_pilot plan={} | 422 / invalid_request，PilotPlan完整错误正文 |
| invalid_object_version：v2对象路径version=0 | 422 / invalid_request，ObjectRef完整错误正文 |
| negative_configuration_participants：当前base配participants=-1 | 422 / invalid_request，AssistantConfig完整错误正文 |
| test_case_revision_zero：导入case revision=0 | 422 / invalid_request，TestCase完整错误正文 |
| investigation_block_revision_zero：导入block revision=0 | 422 / invalid_request，InvestigationBlock完整错误正文 |
| investigation_review_focus_invalid：导入review.focus=invalid | 422 / invalid_request，InvestigationPayload完整错误正文 |
| test_case_id_missing：导入case缺id | 404 / not_found，原正文 |
| legacy_raw_purpose：contracts/v2/legacy.py解析raw.purpose=7 | 422 / invalid_request，LegacyProvenance完整错误正文 |
| unclassified_value：未显式分类ValueError | 422 / invalid_request，原正文 |
| unclassified_key：未显式分类KeyError | 404 / not_found，原正文 |
| unknown_scenario：未知v1场景 | 422 / unknown_scenario，原正文 |
| unknown_role：v1 turn未知角色 | 422 / unknown_role，原正文 |

### 横向输入清单

v1 actions参数与PilotPlan、v2对象路径与查询、configuration.apply的SettingsInput和合成AssistantConfig、Gateway命令/query/payload、workspace raw晚解析、scenario/approval/feedback/import模型，均保留原handler映射，不再需要逐输入窄包装。FastAPI外层请求验证及既有业务异常照旧。存储资源缺失与evidence选择缺失照旧；只有上表已证实持久化损坏升级。注册/安装/离线CLI错误不改变，worker持久化错误对象与MCP业务错误契约不扩大。

### 日志

三正式serve入口（主CLI、delegations、scenarios/v2）共享白名单logging配置；root不启用依赖INFO，依赖日志不向外输出；Uvicorn关闭原始access日志且不重装默认配置。每请求一条摘要、错误一条类型分类诊断，允许字段仅event、服务端request_id、方法、路由模板、状态/code、耗时、异常类型和安装包版本；禁止原始URL/query/header/token/DB URL/请求响应正文/私人材料/异常文本与exc_info。默认422正文依法保持原输入内容，但日志不复制该正文。当前接口无流式响应；四handler与read_evidence签名完整。

## 9. 凭据派生修复（063-02，独立安全批次）

已确认的代码事实：`storage/v2_store.py issue_delegation`和`api/v4_extensions.py _practice_session`从owner token_hash作HMAC key；同文件 `reference_agent_token`存在第三处相同派生方式。只拿数据库摘要加公开上下文就足以复现这些算法；这里是静态风险确认，未声称真实数据泄漏。

本票原列两条公开路径；第三处内部参考Agent路径已获批准**纳入批次7的同根修复**，不新增研究功能、不把参考Agent能力接到用户入口。三条派生路径须一并覆盖，不新增参考Agent对外入口。

拟采用部署侧秘密提供器，由服务装配注入，使用明确key_id和用途域（delegation、practice-session、reference-agent）绑定owner credential、会话、完整请求／授权指纹和目标身份。秘密不存DB；新增必要的非秘密派生元数据及唯一约束以支持并发、跨进程、重启和幂等。缺key、旧key版本不可用或key内容不匹配时明确失败，不自动随机换值，不回退到token_hash，不隐式轮换或撤销现有凭据。生产秘密由获准部署配置，本线测试只用固定虚构key。

所有恢复重新验证当前owner、scope、撤销、到期及对象归属。并发补练不能依赖当前`contains`后`create_session`的分离检查；要通过现有事务/唯一约束返回同一身份并拒绝同request_id异体，不新增独立事务系统。原引用、补练选择记录及旧会话身份保持。

**兼容限制必须正面处理：** 已签发旧token仍按摘要验证，因此无法同时声称“保留所有旧token”且“基于旧库计算出的同一旧token立即失效”。本票阻止新签发／恢复继续使用不安全派生，保留旧token验证；全面撤销或轮换旧token需要另行决定。绝不把旧hash继续算出明文包装成安全恢复。

| 凭据 HTTP 情况 | 已批准变化（新增错误名称实施时固定） | 保留内容／停点 |
|---|---|---|
| POST `/sessions/{id}/delegations` 新签发／同请求重放 | 正常仍200，同grant、同token；缺配置／key版本不可用为503 `credential_derivation_unavailable` | 原公开字段、权限、到期、同ID异体409继续；拒绝时无新记录 |
| POST `/sessions/{id}/practice/choices` 新建／重放 | 正常仍200，同目标session/token；相同新503状态 | 原语言、来源反馈、选项校验不变；源choice与目标创建不得部分成功 |
| 已存在旧派生记录的主人同请求重放 | 已认证owner在相同source session/feedback/choice/request上，按新方式对同一目标会话加法重签并返回200、同session id、新token；委托同理 | 旧token继续按摘要验证，不计算旧派生明文；未认证或请求不匹配维持401/403/409，不创建第二会话 |
| 再签发权限与幂等 | 使用已有HTTP同请求重放，不改前端；已有link或新intent的记录不允许用新request_id绕过；持久化派生版本与对应原请求指纹 | 元数据加法存储；新旧token同时有效；同请求重放返回同新token。若发现安全缺口，停在批次7之前汇报 |
| 吊销／过期／越权 | 原401/403和业务错误保持 | 即使持有正确派生元数据也不能恢复凭据 |

测试沿W14预先确认的正式HTTP接缝，一次一个红→绿：CRED-01仅DB摘要不能签发**新**有效凭据（合法新签发成功）；CRED-02跨用途/主体/请求不能串用；CRED-03缺key/版本漂移不改记录；CRED-04并发/丢响应幂等与异体冲突；CRED-05旧token仍验证、旧主人同请求重放200重签同身份；CRED-06撤销/到期/越权无有效返回；CRED-07秘密不进入DB/导出/异常/log。第三条派生路径额外用直接内部受权接口验证，不新增对外HTTP。

回退不能简单换回不安全算法。采用加法元数据、保留旧摘要验证，修复后签发凭据的校验与身份保持；若回退业务版本，保留能识别新派生元数据的兼容签发/恢复组件，或明确停止新签发且不影响已持token读取。备份使用独立测试数据库先演练，不在本线触碰已部署数据。

### 批次7实现与验收映射

**2026-10-09 080续行裁定：** `agent_label`属于委托请求内容，同request_id改标签必须409；同ID同内容仍200且身份不变。`delegations/service.py::issue`只增加一行完整payload摘要透传，存储将该摘要纳入现有派生指纹，不保存标签正文。该hunk获准纳入093，086在同文件的工具目录／参考身份增量由080合并；本线不改其余部分。

四处签发共用`security/credentials.py`；部署通过`CAREER_LAB_CREDENTIAL_KEY_ID`及`CAREER_LAB_CREDENTIAL_KEY`提供至少32字节秘密，由装配注入提供器，生产无默认值。服务只在签发/恢复时读取配置；已有token认证不依赖部署key。配置缺失、版本/内容漂移、提供器异常及已损坏的派生认证链统一503 `credential_derivation_unavailable`，正文为`credential derivation unavailable`，无秘密或内部异常文本。

补修snapshot restore遗漏路径：带request_id且未显式提供token的新恢复使用同一签名器、`snapshot-restore`用途和同一组部署配置；绑定父human授权、子身份及目标session/request/snapshot hash，来源与子会话同事务落库。重放重检当前授权、固定派生版本及指纹，返回同一凭据；缺配置或key漂移503且不改记录。历史restore凭据缺少派生来源；按074裁定不复算旧明文，因此不区分显式token与旧摘要派生token，不自动加别名；旧token及显式携token重放仍有效，省略token时409 `restore_token_conflict`。仅新restore走新派生；本提交前派生的restore token仍可凭数据库读权限推导，直至撤销。是否撤销持久库中历史派生凭据由用户决定。

新增两张凭据表只存scheme/key_id、完整请求与授权指纹、token摘要及原credential_id别名；不改原凭据摘要、上下文或撤销位。别名认证仍进入原凭据的session、scope、撤销和到期检查。新旧token在原授权有效时同时有效；不声称旧DB摘要推导出的同一历史token已失效。

补练新增`v4_practice_intents`：完整选择意图、目标会话和派生元数据同现有事务写入；链接完成时重新检查owner和既有link，再同事务登记完成；意图指纹在第一事务统一检查。链接I/O失败允许留下未完成意图及唯一目标，原请求继续恢复；不把这一步当成功响应。同ID改choice/option或原反馈指纹拒绝409；新ID不能绕过已有未完成意图。保留原测试中“目标创建后link写失败仍有2个session”的恢复断言，未删除旧记录。

**已批准兼容限制（2026-10-09，080裁定，由093任务书确认）：** 没有link/intent的旧孤立目标只能由原请求命中恢复；新request_id不自动附会旧目标，也不能取得对旧目标有效的凭据。严格的跨ID禁止绕过保证只覆盖已有link或新intent的记录。旧sid是source/feedback/request的不可逆摘要，库中没有可反查来源；不复算旧token明文、不补造历史。新ID可以创建独立的新会话，但不能恢复该旧目标；恢复旧目标须由已认证主人明确重放原请求，并按新派生方式加法再签发。缺部署key、身份或授权不符时关闭恢复，不返回伪成功。不能声称所有旧记录均满足跨ID禁止绕过。

| 验收项 | 真实入口与反例 | 当前证据 |
|---|---|---|
| CRED-01 | 委托、补练HTTP及参考Agent内部接口，DB摘要按旧算法无法推导新有效token | 三处已有红绿 |
| CRED-02 | token不能跨session，参考身份不能进入用户tools；同ID异体拒绝 | 正式HTTP及内部受权回归 |
| CRED-03 | key缺失/版本/内容漂移无新记录、原token仍可读；alias损坏不伪报恢复成功 | 漂移及alias红绿 |
| CRED-04 | 并发选择同target/token；link写失败后同ID改decline拒绝，原请求恢复 | 并发与完整意图红绿；保留原失败恢复测试 |
| CRED-05 | 旧委托/补练/参考加法重签，同身份/新token，旧token保留，重启恢复 | 旧委托/补练红绿与旧reference/重启回归；旧孤立目标按已批准兼容限制补验 |
| CRED-06 | 未认证、跨会话、越权、撤销、过期与重签优先级 | 真实DELETE撤销、过期时钟及参考撤销验证 |
| CRED-07 | DB、公开schema、日志与错误无部署秘密；提供器含秘密异常不外泄 | 提供器红绿及持久化/出口检查 |

测试与回归脚本仅给自身隔离数据库注入明确标记的虚构key；不会给生产设置key或改动部署。完整门禁、逐ID/固定反馈/发布字节、独立双轴及PR草稿由每批回执固定实际证据。

P3协调封装判断：本批保留`_practice_session`作为API装配层的协调函数。它同时需要场景注册、公开状态投影和同一Connection；存储层已提供`create_session`事务接入和凭据原语。将整段搬入存储会反向引入场景注册与API投影依赖；按行数拆分也可能模糊目标与派生元数据的同事务边界。当前无重复实现，权限和签发仍由既有存储/安全原语执行，本批不为该非阻塞可维护性建议扩展存储职责。

## 10. 分批执行、失败模式与验收

流程采用 ask-matt 的规格→TDD→双轴code-review→PR正文草稿路径。方案已批准进入执行；不创建额外任务台账、GitHub issue或产品规格。执行期由本地独立worktree进行，一批一提交；Claude独立评审与合并。本线不给其他Codex对话发消息。

| 顺序 | 批次 | 文件范围与交付 | 放行条件／回退 |
|---|---|---|---|
| 0 | 更新执行基线 | 同步总协调指定main，重装锁定依赖；保存本次旧ID结果与新main全部ID；浏览器端口19660/19662获放行后跑执行前baseline | 062/格式化/065带来的差异逐项归属；不能覆盖本轮基线隐藏缺失；此步不清理资产 |
| 1 | 过程证据归档 | 第4节两个JSON（dev、fixed-inputs）、14 XML和工程链接；不含freeze、drafts、apps | 完整Git恢复/sha/文档链接无缺口；否则仅保留可证明的子集；原blob恢复即可 |
| 2 | 历史tar按需还原 | 压缩原tar、门禁启动时解压，保持原两个参数化测试体/sha不变 | 新旧逐成员、原tar hash相同；损坏压缩包非零失败、无skip；回退保留原tar |
| 3 | 已退役源码／脚本入口 | review_ports条件删除、旧rebind_runtime归档；必要单一历史说明 | 无动态依赖，原历史证据恢复/CLI/全量通过；不得删除未接P1；任一引用不可恢复则保留该文件 |
| 8 | 评价源码字节锁迁移（在3后执行） | 见下方补充规格；真实规则文档改用评价版本/修订/固定对照，新六包仅经正式rebind生成 | 旧包读取兼容、业务逐文件不变、原审核身份不变；格式化另一个提交，八文件AST相同 |
| 4 | 名称和低风险import | 注释、用户CLI文案、MCP version；纯依赖import单独清楚diff | 身份字串不变，原业务错误不改；MCP唯一预期变化审明；062新文件不得覆盖 |
| 5 | 角色快照适配器分层 | 第7节单一storage→api边，原导入保留转发 | 未触及事务／时窗；循环、授权或历史差异就撤回；storage→runtime其余债务仍保留 |
| 6 | HTTP分类与logging | app/errors、明确输入/资源查找边界和新增领域测试 | 第8节逐行HTTP对照、日志无敏感哨兵；已知业务code/status/message不变 |
| 7 | 063-02凭据安全修复 | store、凭据服务/非秘密元数据、补练签发、装配与HTTP测试 | CRED全部通过，旧补练再签发接缝可用；范围/兼容不能解决则停在此批之前 |

若批次4的显示文案与import涉及不同风险，拆成两个提交；不会将安全修复混进格式化／改名提交。每批进度报告：`可合入的候选提交 <sha>｜批次名称`，附前后指标、精确删除列表、测试ID对照、固定反馈结果、双语/MCP证据，然后继续下一已获准批次。

### 10.1 失败模式一对一验证

新增测试用领域命名，不将066编号写进产品或测试文件名。以下ID是方案验收项，执行时映射到实际pytest/浏览器测试ID；原ID一律保留。

| 方案验收ID | 失败模式 | 对应一条明确测试／检查 |
|---|---|---|
| ASSET-01 | 归档后文档找不到当时证据 | 干净clone按固定commit恢复每个清理文件并验hash、原链接目标可达 |
| ASSET-02 | 压缩后tar不再是原冻结输入 | 解压后整tar固定SHA及成员逐字比较；损坏压缩输入必须失败 |
| ASSET-03 | 归档源码被当前实现取代 | 实际历史rules模块仍从原tar载入；原中英测试ID和断言不变 |
| HIST-01 | 删除旧包后历史会话找不到hash | 每个拟删hash通过真实archive reader及旧会话材料读取；未覆盖则禁止删除 |
| HIST-02 | 回退或旧反馈重算／改身份 | 六包rollback＋旧提交/feedback/evidence持久化前后同值，model调用计数0 |
| HIST-03 | 重绑改变业务内容或旧审核 | 正式CLI输出逐业务文件sha、原manifest/review身份及六语言场景组合 |
| CODE-01 | 动态CLI/兼容import被误删 | 冷进程实际import与所有保留CLI help，读取正式应用安装后的operation目录 |
| CODE-02 | 存储拆分漏掉最终权限／竞态检查 | 现有撤销、过期、job结束、分享、修订、旧轮采用与恢复的真实Gateway/worker回归 |
| NAME-01 | 改名改变持久化ID或prompt/发布hash | 对同输入的test/feedback/ref身份及prompt版本逐值比对 |
| NAME-02 | MCP版本改动影响协议或工具 | 真实initialize/ping/tools/list/call/撤销/未知结果恢复，仅serverInfo.version有批准差异 |
| HTTP现行矩阵 | 错误类型、消息、状态、headers或回滚不符第8节 | 同一参数化父版对照覆盖兼容及四处显式升级；默认ValueError正文保留，日志出口不泄漏；未分类HTTP-11为安全JSON500 |
| LOG-01 | 日志暴露token/私人正文/异常文本 | caplog＋HTTP出口哨兵；仅白名单字段，无exc_text/locals/query |
| CRED-01…CRED-07 | 见W14原任务单及第9节 | 逐ID独立正式签发／补练HTTP回归，另加内部参考Agent同根反例 |
| GATE-01 | 清理漏测、隐藏skip或丢ID | 原开工基线、新main基线、每批候选三方比对，缺失/失败/新增skip均非零 |

文件归档这种低影响变化使用恢复与现有门禁核验，不额外编写镜像实现测试；行为修复和高风险迁移按真实入口TDD。测试必须导入被测生产代码，故障替身限外部I/O、时钟和异常注入，不重写权限/评分实现。

### 10.2 每批统一门禁

1. 精确源码差异、变更文件归属、锁定业务/冻结字节检查；Ruff格式和E/F/I/UP/B零新增；`git diff --check`。代码指标沿相同脚本采集，记录删除字节与剩余债务。
2. `scripts.regression.run --output <新目录> --browser`完整门禁；浏览器只在总协调放行端口后执行。后端/前端逐ID与本轮基线比较，再与同步main的执行基线比较；不只使用仓库原2109/226旧清单。
3. 原 `feedback-baseline.json`、`engine-cases.json`、prior-cycle snapshot逐项不变；保留变异反例。中英文各从正常v4完成工作与反馈/修订，真实MCP链，v1旧会话读写与历史恢复；不得把fixture或翻译可运行称作模型/真人质量通过。
4. 双轴独立review：Standards按编码约定；Spec按本方案、W14 063-02与产品边界；额外检查测试是否导入真实实现、工程文档是否只涉及本切片。PR正文只起草交总协调，不发布。
5. 任何未批准行为变化、历史读取失败、测试ID缺失、新skip、需要削弱断言或无法保持旧发布身份，停在该批之前。安全修复只有本方案明确审定的差异可通过，不能用“修bug”掩盖其它变化。

## 11. 收益与保留项

主要候选缩减为过程证据归档与tar压缩，原始可移出工作树字节约 967,766（两份JSON、14份XML、旧脚本和review_ports）；tar另可节省约428,083，共约1.40 MB十进制，需扣去归档说明与fixture还原代码。此为候选上界，尚未执行；不将截图15.35 MB、场景重复14.20 MB或受冻结保护的草稿列入可兑现收益。

更重要的质量结果是去掉旧就地补丁入口、明确历史/活动输入、减少一条反向依赖、建立稳定异常边界和修复摘要派生。不能用删除量作为完成标准。明确保留：全部场景代次、drafts、研究freeze、评价对照、旧测试名字、v1读写及未接通P1。第三处同根修复与旧主人同请求200重签已批准；实施发现安全缺口则停在批次7之前。

## 附录：候选归档清单与恢复身份

以下14份XML为批次1的完整候选清单，不能用glob删除后来新增的报告。其余候选已在正文逐文件列出。固定恢复基点均为 `9a39cc7247009e8e4a20f176c79b8a0954c1663e`；原字节SHA以盘点JSON逐文件清单为准，执行前把清理子集的SHA写入提交内归档说明，避免依赖仅本机证据。

| 相对路径 | bytes | 文本行数 |
|---|---:|---:|
| `docs/reports/controlled-v2-final-tests.xml` | 10,127 | 1 |
| `docs/reports/controlled-v2-task2-tests.xml` | 9,189 | 1 |
| `docs/reports/task-01-tests.xml` | 3,091 | 1 |
| `docs/reports/task-02-tests.xml` | 3,791 | 1 |
| `docs/reports/task-03-tests.xml` | 4,253 | 1 |
| `docs/reports/task-04-tests.xml` | 4,506 | 1 |
| `docs/reports/task-05-tests.xml` | 4,850 | 1 |
| `docs/reports/task-06-tests.xml` | 5,911 | 1 |
| `docs/reports/task-07-tests.xml` | 6,493 | 1 |
| `docs/reports/task-08-tests.xml` | 6,835 | 1 |
| `docs/reports/task-09-tests.xml` | 7,068 | 1 |
| `docs/reports/task-12-tests.xml` | 7,319 | 1 |
| `docs/reports/task-13-tests.xml` | 7,438 | 1 |
| `docs/reports/task-14-tests.xml` | 8,322 | 1 |

恢复例：在独立临时目录执行 `git show 9a39cc7247009e8e4a20f176c79b8a0954c1663e:docs/reports/controlled-v2-dev.json > controlled-v2-dev.json`，再与清单SHA比较。固定commit不可用时先恢复完整Git对象，不能生成一份当前结果冒充旧证据。


## 批次8补充规格：评价身份与源码排版解耦

规则文档使用评价逻辑版本、规则修订、登记的engine-cases.json及feedback-baseline.json摘要，不含实现源码字节。旧rules文档按原文件hash和原登记语义兼容读取，不再与磁盘当前源码逐字比较。正式rebind导出六个新组合；旧包原件、原审核、内容文件全部保留，runtime/evaluation描述允许引用新的生成规则描述。评价对照本身与原注册摘要不更新。

预先确认的测试接缝为正式rebind CLI、六包HTTP/worker反馈和真实FeedbackEngine。EVAL-01：仅改变八个实现文件的排版后，旧/新六包仍能生成等值反馈；EVAL-02：同语义版本的规则输出被改变时，固定对照门禁必须失败，不能重生成expected消除失败；EVAL-03：旧rules内部文件内容或新规则描述被篡改，manifest/语义注册校验拒绝；EVAL-04：六包业务文件、内容身份和原审核链不变，历史反馈不重算。每个反例先红后绿并记录原始证据。

迁移完整门禁通过后，另一个提交移除pyproject中八个rubric规则文件的extend-exclude并执行ruff format；五个v1契约仍排除。逐文件AST不变、完整门禁/逐ID/固定反馈再次通过才交候选。

## 批次1：历史证据归档

以下16份原件保留在固定Git提交 `2c07160b5e829ac08afb8a31667440bbda72df73`。当前工作树移除副本，既有工程说明指向原提交；研究freeze、全部场景和冻结契约保留。恢复使用 `git show <commit>:<path>`，逐条验证SHA；不要用新实验覆盖旧证据。

| 原路径 | bytes | SHA-256 |
|---|---:|---|
| `docs/reports/controlled-v2-final-tests.xml` | 10127 | `243f90c01723cfc8f8e7e7cfcfad53a4818ce3203dcce07a1c86d1cc97a5295f` |
| `docs/reports/controlled-v2-task2-tests.xml` | 9189 | `facc9a0255e78342f95b41d87b6ec0d77b6e1729563772981ae1c8a0c059573d` |
| `docs/reports/task-01-tests.xml` | 3091 | `47645bcd3765fbbf2fe69d5993f56328394b091694fe277c866819a32ba67e9e` |
| `docs/reports/task-02-tests.xml` | 3791 | `ed6cb8eb588246aa77d64f0a1f54cbd7d86edc40fdc810fe00d925249dbe0402` |
| `docs/reports/task-03-tests.xml` | 4253 | `ae79fc8d410de53c4bef52cb54543316ce43f0d2020f52816e862abf77611600` |
| `docs/reports/task-04-tests.xml` | 4506 | `744505dfc6e8762c8eed1f14c88c4cd67661761fa3557366a2c71a0498bcf272` |
| `docs/reports/task-05-tests.xml` | 4850 | `5a4c0b42871cf896eedfbb5be49642e179e34a546c2e78068cb67c8fa9f7820d` |
| `docs/reports/task-06-tests.xml` | 5911 | `bf044886e4355e1f826dd3b70a521b21cf8ce412f8216893a47fcbcbb3831c16` |
| `docs/reports/task-07-tests.xml` | 6493 | `06453decbbe75b1c03e285477580410e566f0563a0ba872c5cd0a1b63be36240` |
| `docs/reports/task-08-tests.xml` | 6835 | `827261c508c7649a864413bca8757ecb9fd13c059289fb551933737133e30762` |
| `docs/reports/task-09-tests.xml` | 7068 | `7f31151d5255122d8c1ca6123050120de6e60b7ea919c08dbde2da2824a73ffc` |
| `docs/reports/task-12-tests.xml` | 7319 | `ae9374c41f5b150eb84b650b6359dfae6fb1279d94738a4204e6900996292216` |
| `docs/reports/task-13-tests.xml` | 7438 | `a5270c4b2c3beb8fab26282af038cdd50b22770881526c83bc49c3e90e02cd2d` |
| `docs/reports/task-14-tests.xml` | 8322 | `222380eaf34c29d92235377dd465eee8e615a6147ab109c355658fa0b066dd0c` |
| `docs/reports/controlled-v2-dev.json` | 669539 | `2131e6b23a09bac9c524df883d1ce743213558d935e65d9f8dce379f121934b4` |
| `docs/integration/v4-fixed-inputs.json` | 200411 | `246743f33451805afadc5513962670bac03a2ecae687ba9fc450e4dfc9a23cc5` |

报告生成器同步使用固定历史链接，重新执行真实CLI不会覆盖为失效的本地引用；报告指标和计算过程不变。`test_report_cli_keeps_archived_evidence_links`在原生成器上失败，修改两条证据引用后通过；测试使用固定历史输入并执行实际脚本，保留CSV产物检查。

## 批次2：历史规则夹具按需还原

原542,720 bytes tar以确定性gzip（mtime=0、空文件名、level=9）保存，压缩后114,637 bytes，节省428,083 bytes；压缩文件SHA-256为 `d80f62b410c78f502f5c54df176935994d9175f974abeb308e7f9e11de8153f2`。门禁仅在自己的临时目录还原，先验证原大小及 `99297d18c80e69248624b7ad2177729c5ac2f3ccb19afeedb138f3d799030bf3`，再把路径传给原历史测试，结束后清理。两个原中英测试体及其整tar SHA断言原样保留。

新增验证先证明还原入口缺失，再证明被替换但gzip格式合法的内容会被误接受；还原接口和写出前身份校验分别使测试转绿。生成器限制解压读取大小，并拒绝覆盖已有输出。回退可从gzip恢复逐字相同tar，或从父提交恢复原文件，不依赖当前规则生成历史源码。

## 批次3：退役入口与历史恢复

当前运行／测试源码无这两个入口的调用方：旧脚本会就地修改发布目录，正式prepare已经转用rebind CLI；ReviewAuthority只是已明确退役的私有事务Prototype Protocol，不承载未接P0/P1。原包中的来源记录和原W05 tar保持原样，兼容workspace转发与离线评价作者工具保留。

| 原路径 | 原commit | bytes／行 | SHA-256 |
|---|---|---:|---|
| `docs/integration/rebind_runtime.py` | `20847cb562c098da1efba55b039222d04cfb0e82` | 6387 / 149 | `667b405c9fe77e7d78a9e749081cfceabd7dc6e2c75cb87806872dd1e44ec4dc` |
| `src/career_lab/evidence/v2/review_ports.py` | `20847cb562c098da1efba55b039222d04cfb0e82` | 2236 / 50 | `9085b469c3faf0c0566fc0088812dffe90bd2ccd7f525b609996a90724354cb1` |

原件按固定commit使用git show恢复。真实旧CLI与Python导入两条退役边界分别先红后绿，正式rebind CLI仍可调用；业务路径由全量门禁、六包加载、固定反馈及中英文正常入口/MCP覆盖。


## 批次8：规则身份兼容迁移

规则身份由`feedback-rubric-v2-c2.1`、规则与rubric修订、原两份固定对照摘要组成。已登记的28份旧rules原件具有同一固定SHA；读取时仍验FileRef，再仅接受该原件或精确语义描述，不读取当前实现文件的字节。原评价签名保留，追加中英等价语义描述签名；不改固定对照或评价输出。

正式rebind在新六包内新增`runtime/evaluation-rules.json`并更新生成式EvaluationBundle/发布描述；旧evaluation业务原件逐文件保留，内容身份、原始manifest和审核链不变。候选目录为`semantic-rules-v1-2.9.6`，本分支current和回归catalog指向该候选；旧六包与全部旧代次保留。CLI生成的source身份描述本次导出代码，不构成审核通过声明。

EVAL-01测试在独立进程执行实际格式化后的八个模块，经正式安装读取器、旧六包HTTP/worker和固定FeedbackEngine输出验证。EVAL-02沿原测试ID保留完整结果摘要反例，使用AST精确定位一个coverage表达式，避免依赖空格。EVAL-03覆盖旧源码清单与新对照摘要篡改，包含未更新/同时更新FileRef两种情况。EVAL-04由正式CLI及六包逐文件和审核链对照验证。

本批实际修改的rubric_v2按统一代码标准排版，避免渐进lint对未排版旧行产生误报；未修改lint规则或基线。八文件extend-exclude仍在，解除排除与其余机械排版另交独立批次，届时逐文件AST相等（已排版文件允许无差异）。


## 批次8独立排版

从Ruff的extend-exclude移除八份评价实现文件，五份冻结v1契约仍保留排除。对八文件执行Ruff格式化；逐文件AST与迁移候选f40da83一致（rubric_v2已在上一批排版，本批无变化）。不改规则文档、评价版本、场景包、固定对照或测试断言。完整门禁仍包含排版副本的新旧六包反馈与规则输出变异反例。


## 批次4：领域名称与纯依赖导入

注释和docstring中的工作线称呼改为对应职责名；两处用户CLI文案改为私有委托配置、场景模块校验。工程师CLI/任务包在同步基线上已无待改W代号。MCP的serverInfo.version改读安装包career-lab版本，name、protocolVersion、capabilities与其余响应字段不变；现代响应元数据同样使用该serverInfo。所有hash盐、owner、提示修订、协议来源、业务错误原文及测试ID保留。

低风险导入限三文件：移除v2_store重复的局部dataclasses.replace；将v2_snapshot的IntegrityError、role_memory的fields/is_dataclass/replace/TypeAdapter上移。所有打断导入环的延迟导入保留，不动事务边界。67份源码的AST在排除docstring、上述纯导入、两条精确help文案与MCP软件版本后相同；逐模块冷进程导入验证无循环。

真实CLI帮助与完整MCP初始化响应分别先红后绿；固定反馈/快照验证和每批完整门禁覆盖稳定身份、历史、授权与丢响应恢复。


## 批次5：角色快照适配器归层

FixedRoleSnapshotPort及其激活坐标辅助函数从api迁入runtime，原api路径保留同一对象的兼容转发。存储层仅修改begin_role_execution中的这一条延迟导入路径及该导入块的排序；其它代码逐字不变。迁移后适配器补完整类型与显式导入，五个函数除类型注解外的AST保持相同。事务、授权时窗、私有读取、事件接收、历史采用和模型调用位置均不动。

真实V2Store角色输入验证在禁止HTTP模块导入的冷进程中先失败后通过；旧新导入对象恒等，既有角色快照和私有角色测试验证正常/历史/撤销边界。不扩展为存储层整体解耦，storage到runtime的其它依赖保留。


## 批次6：默认HTTP兼容与安全日志

实施按第8节现行表。早期“未分类全部500”草稿已被074续行决定取代，旧草稿和停点证据留在独立runs目录，不作为当前实现。多余输入包装与ResourceNotFound改动撤回，减少无必要类型和存储改动。

父版对照10样本首次7失败/3通过，恢复默认映射后10通过；持久化反馈、会话状态、source_ref各自先红后绿。日志三个入口的真实进程测试沿用已有红绿，HTTP输出回滚反例使用未分类OSError（父版默认500）验证原事务与显式重试。仅尚未提交的探索测试按最新批准更新默认ValueError/KeyError断言，所有1881ed5已提交测试ID、expected和断言保持原样。


## 批次8收尾：本线独立部分

2026-10-09，080将评价常量、作者安装用途和rubric导入交085，datasets文案交083，rebind文案交082。本线只完成以下项；旧发布包、审核、业务文件与固定评价结果不改。批次8已从原干净基线形成五个独立本地提交；其门禁未取得机器锁。080随后批准标签请求指纹接缝，明确允许批次7与8在同一候选树完成完整门禁，回执分别标明独立定向与合并后的全量证据。

| 项 | 最小变化与失败模式 | 验证接缝 |
|---|---|---|
| 2 | 排版反例对八份副本追加注释后格式化，逐文件断言字节确实不同且AST相同；Ruff经shutil.which查找，缺失明确失败，不skip | 真实新旧六包HTTP/worker与固定FeedbackEngine对照 |
| 4 | 新导出的源码清单补runtime/role_snapshot.py；此前只有api兼容转发，遗漏实际运行实现 | 真实contracts exporter输出manifest中的文件身份与摘要 |
| 5 | training CLI两处帮助文字按能力命名，去工作线代号；命令、参数、处理器和运行逻辑不变 | training包正式--help；原子文案差异及参数保留 |
| 6 | 包元数据查询从模块导入移到MCP响应构建；已安装仍用career-lab实际版本，未安装源码明确为0.0.0+uninstalled；INFO无外部消费者，局部协议version不遮蔽package_version | 冷进程导入/构造不查询版本，initialize、现代discover/ping三处版本一致；既有已安装协议回归 |
| 7 | pyproject多余空行移除；角色快照导入合并，保留所有兼容名字（含私有_before） | TOML解析值相等、导入对象相同与无HTTP依赖冷进程检查 |

第4项只改变之后新导出的源码身份，不重新导出或改签任何已发布业务字节，不改变公共schema、旧对象序列化或hash。其余三线项目不计入本线完成范围。全量门禁、逐ID、发布字节与双轴结论由本批回执绑定提交；定向通过不代替模型质量或真人体验。
