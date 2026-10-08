# 工程师任务包、基线复现与离线候选

工程师命令从获准读取的 PM 会话交接固定配置、原始测试和公开失败案例，使用同一助手复现历史行为；也可把保存的测试计划或已确认的原文片段导出为待审 probe 候选。配置修改提交与完整回归 review、研究 suite 审查发布、PM 报告回引尚未实现。

## 读取与材料边界

需要原 SQLite 运行库、当前有效的私有凭据 JSON 和与会话绑定一致的已安装场景。凭据包含 `api_url`、`session_id`、`token`，文件须属于当前用户且权限为 0600。命令不访问该 URL，不将 token 放入命令行或输出；SQLite 以 `mode=ro` 打开，不创建新源库。

- 导出和每次复现都重验当前授权；凭据撤销、对象或动作范围限制不会因已有文件而被绕过。
- 案例材料限于场景加载器校验的 `failures`、`trial_details`，且仍按角色、来源版本与当前授权投影。调查域中的访谈、候选邀请清单、审批等其他材料不随任务包导出。新场景需要明确的案例清单，不能用整个调查域代替。
- 公开 probe 只导出问题，不导出作者动作脚本、期望答案、隐藏 probe、角色私有事实、未来事件或完整内部快照。
- PM 源状态只读；导出、复现和候选转换均不新增 PM 测试、作品、事件或审批。

## 任务包与历史复现

```sh
career-lab-engineer pack \
  --database /path/to/source.db --credentials /private/path/client.json \
  --scenario /path/to/installed/scenario \
  --test EXISTING_TEST_ID --output /private/path/handoff

career-lab-engineer reproduce \
  --database /path/to/source.db --credentials /private/path/client.json \
  --scenario /path/to/installed/scenario \
  --pack /private/path/handoff --output /private/path/reproduction
```

`--test` 可重复，最多选择 100 个已有记录。它们是待调查输入，不自动被判为错误。pack 需要读取权限；reproduce 另须已有 `act/tests.create` 权限。

任务包包含 `pack.json`、私有成员索引 `index.json`、`config.json`、所选测试原件、失败案例材料、公开问题和对应语言的 README。配置文件是导出时的当前配置；每个测试保留自己的历史配置与执行时点。

私有包格式 2 用来源和数据文件定义身份，单独记录 `template_version` 和 `tool_versions`。工具身份为实际 engineer 模块源码的 SHA-256 快照，能反映本地代码变化，不依赖安装包版本或 Git 历史；源码无法读取时返回 JSON 错误。README 等说明的变化不改变格式 2 的数据身份；文件校验仅表示完整性，不证明声明出自可信作者。复现另按格式／模板规范常量比对 requirements，并在报告与CLI给出 `declaration_status`：`matched`、`mismatch` 或 `unverified`。规范不符标为mismatch；未知模板或工具来源不能核验标为unverified。报告保留声明原值、规范值及当前工具身份，行为复现成功不表示约束声明已通过。工具身份与当前源码不同可能是合法旧版本，不能据此直接断言伪造。

格式 1 保留原身份算法与原说明字节，requirements 必须匹配已发布版本的冻结常量。修改该字段并重算文件声明 hash 仍被拒绝。所有格式的数据均与授权原库逐字节核对，不能凭提交者自报 hash 证明真实性。包的材料集合必须与当前支持的失败案例范围一致；不匹配时拒绝，原包不被覆盖。

复现使用各原测试自己的历史快照，保存固定来源、本次实际执行者及原行为／复跑行为对照。`matches_record` 仅表示行为一致，`correctness_assessed=false`；不据此宣称答案正确或修复成功。行为改变时保留报告并非零退出；源库丢失、权限不足、版本不符或篡改不生成成功报告。

`model_calls` 和 `mode` 从实际 `execution.attempts` 与完整性标记汇总；用量不完整时标未知，不硬编码零调用或确定性结论。当前真实助手没有模型调用。复现报告仍使用私有格式 1；明确的报告版本迁移及有模型调用分支的独立测试待补。

## 离线候选 probe

```sh
career-lab-engineer probes-from-plan \
  --database /path/to/source.db --credentials /private/path/client.json \
  --scenario /path/to/installed/scenario \
  --product SAVED_PRODUCT_ID --product-version 1 \
  --output /private/path/candidates
```

结构化 test_plan 保留 TestCase 原句、id、revision、intent、来源引用及自报 category／expected。自由作品必须显式选取原文片段并加 `--confirm-extraction`；`--span START:END` 使用 Unicode 字符位置，左闭右开，可重复但不能重叠。`--text-field content|body` 默认 content，body 仅指 TextPayload.body。未确认、字段不符、范围非法、空白或超长问题均拒绝，不猜测或改写问题。

输出为 `source-product.json` 原件和私有 `candidates.json`。作品引用／版本／hash、读取时点、语言、来源执行者与本次执行者均保留；结构和 split 来自会话固定场景。导入作品的外部谱系保留在原件中，未额外验证。所有候选都是 `pending_review`／`unverified`，自报期望仅作为意图，没有 pass/fail、gold 或能力分数。

候选仅供 review，训练与优化资格均为 false，CLI 不接受覆盖 split 的参数。它们不是研究 suite 的发布格式。经规则／场景审查后，新增 probe 才能由负责方发布到新的 suite 版本；本命令不执行 probe，不修改原 suite 或已冻结 review。

同一来源快照、选择与执行者重复导出得到相同批次身份；源时点或作品版本变化使用新目录。已有不同内容、损坏输出或未取得发布锁时明确失败，不覆盖原目录。共用发布器目前返回 `publisher_busy`；崩溃遗留锁的安全识别与恢复尚未实现，不能根据时间猜测并删除可能仍有效的锁。

## 验证与后续接口

测试通过动态端口真实 HTTP 创建与修订 PM 作品，CLI 子进程显式使用被测工作区源码并检查导入位置；原 `career-lab-engineer` 入口分别验证中英文。旧格式兼容使用校验固定的已发布导出器夹具，不依赖浅克隆中可能缺失的提交对象。

冻结的 EngineerSubmission 尚不能表达基线 hash、自报报告引用、未修复项和创建时间；RegressionReport 也缺少完整复核状态、suite／reviewer 身份和实际生效配置的冻结映射。公共契约负责方完成兼容增量、集成人串行发布冻结输入后，才能接续 submit/review；不能把这些字段塞进说明字符串或另造平行公共协议。专用页面、任意代码执行、训练和付费模型调用均未由这些命令开放。
