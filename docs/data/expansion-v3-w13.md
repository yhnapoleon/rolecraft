# W13 工程师任务包与基线复现

本切片实现从真实 PM 会话交接固定版本的配置、测试记录、公开案例和公开测试问题，并用现有 W02 助手复现选定测试。它是 W13 的第一部分；配置修复提交与完整回归 review、PM 报告回引、probes-from-plan 尚未实现。

## 行为与验收

- 任务包来自当前凭据获准读取的同一会话、同一已保存时点。保存当前配置和所选测试原件；测试各自保留其历史配置与执行时点，不能混称同一配置。
- 场景、配置、材料与测试用内容 hash 和原始引用固定。公开探针只导出标为 public 的问题，不导出作者的动作脚本、预期答案或隐藏探针。
- 不导出会话凭据、角色私有事实、未来事件、场景答案或完整内部快照。完整场景只留在受信任的本地运行环境。
- 复现重新核对原会话和当前授权，在原测试的历史快照上调用同一个助手。权限撤销、来源丢失、文件篡改和运行版本不符明确失败，不能信任交接文件自报的 hash。
- 复现只比较记录中的行为是否重现，不代表答案正确或配置修复。父会话不新增测试、事件、作品或审批；复现结果是独立产物。
- 同一输入重复导出得到相同包身份；已存在且内容不同的目录拒绝覆盖。中英文分别验证。

测试通过当前解释器的 `python -m career_lab.engineer` 运行被测源码，并保留已发布的 `career-lab-engineer` 入口兼容检查；子进程显式设置本工作区源码路径且断言导入路径。测试数据通过动态端口真实 HTTP API 创建，使用独立 SQLite、场景及助手，完成后停止服务。覆盖正常交接和复现、权限、版本漂移、篡改、重复执行与原会话不变。外部模型、PostgreSQL、工程师专用 UI 不属于本切片验收。

## 使用

在已有环境操作者的本机运行。需要原 SQLite 运行库、与会话绑定一致且通过当前运行源码校验的安装场景，以及私有凭据 JSON 文件。配置结构为 `api_url`、`session_id`、`token`，文件须属于当前用户且权限为 0600；命令不访问其中的 URL，不把 token 放入 argv 或输出。SQLite 以 `mode=ro` 打开，不创建新源库。

```sh
career-lab-engineer pack \
  --database /path/to/source.db \
  --credentials /private/path/client.json \
  --scenario /path/to/installed/pm_pilot \
  --test EXISTING_TEST_ID \
  --output /private/path/handoff

career-lab-engineer reproduce \
  --database /path/to/source.db \
  --credentials /private/path/client.json \
  --scenario /path/to/installed/pm_pilot \
  --pack /private/path/handoff \
  --output /private/path/reproduction
```

`--test` 可重复，最多选择 100 个已有记录；它们是待调查输入，不自动被判为错误。英文会话使用其英文安装目录。pack 需要读取权限；reproduce 另须已有 `act/tests.create` 权限。受限对象和动作范围继续生效，凭据撤销后不能再从原库复现。

新包的私有 `index.json` 使用格式 2：记录 `tool_versions` 和 `template_version`，来源与数据文件定义包身份；README和requirements说明独立保留，当前模板不参与旧包真实性判断。格式1仍按原算法验证其原始说明和数据，不重写已导出的旧包。说明本身的hash只表示完整性，不能证明其中指令来自可信作者。

输出包包含 `pack.json`（现有 EngineerPack）、`index.json`（成员及来源索引）、`config.json`、所选测试原件、按场景 `investigation` 材料域选择并经权限投影的案例材料、公开问题和对应语言的 README。场景引用指向可信环境中的原始场景，不把完整内部场景复制进任务包。

复现逐条使用原测试自己的历史时点和配置，不拿导出时的当前配置覆盖历史。`report.json` 保存本次真实执行者、固定场景／运行／评价绑定、原结果与实际重跑结果；`model_calls` 来自本次 `execution.attempts`，执行用量不完整时为null且mode标未知；本地无调用时标 `isolated_reexecution_without_model_calls`，不假称确定性。逐条保留调用记录与完整性标识。`matches_record` 仅表示行为一致，`correctness_assessed=false`，不会把模型回答或人工兜底判成正确。原库缺失、权限不足、场景版本不匹配或包被篡改时非零退出，不产生成功报告。相同内容的重复命令可回读；不同内容或执行者不能覆盖既有目录。包与报告含授权业务内容，应按原会话的分享范围保存。

## 下一切片

配置修改提交、完整公开／隐藏探针回归、伪造回归报告核验、PM 证据回引和 probes-from-plan 待实现。当前命令不执行补丁、训练或模型调用，不改变 PM 配置、资源或评分。W13 保持部分交付，不能据这条基线复现链宣称工程师路径整包完成。

## 062 修复规格与失败模式

工程师需要在工具说明升级后继续复现已导出的包，并确认测试及报告来自当前被测源码和实际运行。本轮保留既有公共业务契约，只修任务包与基线复现；M1配置提交、完整review遇到冻结契约缺口时停止，不自行发布新公共schema。

测试接缝已经由062用户确认：CLI子进程显式运行本工作区源码；真实HTTP接口创建PM会话与测试；输出目录中的不可变文件。以下每种失败模式对应具名测试，两语参数分别执行；不以mock内部助手代替真实运行。

| 失败模式 | 期望行为／测试 |
|---|---|
| console script误导入其他checkout | module入口及子进程导入路径属于被测根；`test_cli_imports_tested_source`，原console入口仍可调用 |
| README／requirements文案变化误拒旧包 | schema 1旧包与schema 2包均依据原数据复现；`test_old_pack_survives_documentation_upgrade` |
| 新包缺工具版本，模板变化改变数据身份 | 独立记录工具／模板版本，数据身份不受文案影响；`test_pack_versions_documentation_separately` |
| 包数据被修改并重算声明hash | 与原库逐字节比对仍拒绝；保留 `test_rehashed_forged_pack_is_rejected_against_original_sources` |
| 实际调用与硬编码零调用／确定性标签不符 | 从实际execution.attempts和cost_complete推导；不全时标未知；`test_reproduction_reports_execution_metadata` |
| 授权范围改变导致行为不同 | 保存真实差异，status=behavior_changed并非零退出；`test_behavior_change_is_not_success` |
| 场景版本不符 | 明确非零且无成功报告；`test_wrong_scenario_fails` |
| 原SQLite库缺失 | 不创建空库，不生成成功报告；`test_missing_source_database_fails` |
| 选择超过100个不同测试 | 明确拒绝且不导出；`test_too_many_tests_fail` |
| help／README包含内部代号 | 用api_url/session_id/token与0600说明凭据；`test_guide_and_help_describe_credentials` |
| 非pm_pilot材料ID丢失 | 根据场景材料元数据与授权投影导出，无新增固定ID；`test_pack_materials_follow_scenario_metadata` |
| 目录已存在／并发发布 | 复用已有immutable_directory；相同内容回读，差异不覆盖；既有immutable测试及 `test_concurrent_exports_preserve_one_complete_package` |

身份方案：数据文件与来源定义pack身份；文档独立完整性检查，不再将当前程序生成的说明字节用作来源真实性依据。schema 1保留原身份算法，在原包说明字节上验证原ID，不重写旧包；新schema 2独立记录tool与template版本。数据文件、源时点、场景与权限校验不减弱。

M1后续失败清单（契约放行前不实施）：错误pack/base hash、重复ID不同内容、越权、未知配置字段／执行参数、缺资源误判生效、目标未修复、新增回归、自报不符、模型／进程故障误判业务失败、重复review重跑、语言／来源版本丢失。对应测试须按W13 §6–7逐切片红绿推进；语义说明仅advisory，缺模型标等待模型接入。PM回引与界面、probes-from-plan、公共契约、docs/plans及apps/web均不在本修复切片。

## M1 契约停点与接续

062只完成上面的任务包与基线复现修复，未实现submit/review，不称M1完成。当前冻结的EngineerSubmission只含id、pack/config文件引用、explanation、字符串claimed_results及executor；缺base_config_hash、regression_report引用、unresolved与created_at。RegressionReport缺结构化复核状态、report_mismatch、suite/reviewer版本和实际生效配置／执行元数据的明确映射，两者extra=forbid。

按062用户指定停点，需要公共契约负责线提供兼容的冻结增量，或明确批准上述字段如何通过具名、带hash的私有附属文件绑定到现有引用。不能把结构化字段塞进说明字符串或另造一套可与公共模型分叉的提交协议。公共契约、API挂载、场景冻结、前端、docs/plans本轮保持原字节。

下一轮先取得上述映射及冻结版本，按本页M1失败清单和W13 §6–7实现submit/review；再评估§8的离线候选probe转换。M2 PM回引等待公共后端线合入。说明的语义评价保持advisory／等待模型接入，不发起付费模型调用。
