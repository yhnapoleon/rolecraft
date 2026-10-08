# W13 工程师任务包与基线复现

本切片实现从真实 PM 会话交接固定版本的配置、测试记录、公开案例和公开测试问题，并用现有 W02 助手复现选定测试。它是 W13 的第一部分；配置修复提交与完整回归 review、PM 报告回引、probes-from-plan 尚未实现。

## 行为与验收

- 任务包来自当前凭据获准读取的同一会话、同一已保存时点。保存当前配置和所选测试原件；测试各自保留其历史配置与执行时点，不能混称同一配置。
- 场景、配置、材料与测试用内容 hash 和原始引用固定。公开探针只导出标为 public 的问题，不导出作者的动作脚本、预期答案或隐藏探针。
- 不导出会话凭据、角色私有事实、未来事件、场景答案或完整内部快照。完整场景只留在受信任的本地运行环境。
- 复现重新核对原会话和当前授权，在原测试的历史快照上调用同一个助手。权限撤销、来源丢失、文件篡改和运行版本不符明确失败，不能信任交接文件自报的 hash。
- 复现只比较记录中的行为是否重现，不代表答案正确或配置修复。父会话不新增测试、事件、作品或审批；复现结果是独立产物。
- 同一输入重复导出得到相同包身份；已存在且内容不同的目录拒绝覆盖。中英文分别验证。

测试入口为正式 `career-lab engineer` CLI，测试数据通过现有 HTTP API 创建，使用真实 SQLite、场景及助手。覆盖正常交接和复现、权限、版本漂移、篡改、重复执行与原会话不变。外部模型、PostgreSQL、工程师专用 UI 不属于本切片验收。

## 使用

在已有环境操作者的本机运行。需要原 SQLite 运行库、与会话绑定一致且通过当前运行源码校验的安装场景，以及现有 W06 私有配置文件。配置结构为 `api_url`、`session_id`、`token`，文件须属于当前用户且权限为 0600；命令不访问其中的 URL，不把 token 放入 argv 或输出。SQLite 以 `mode=ro` 打开，不创建新源库。

```sh
career-lab engineer pack \
  --database /path/to/source.db \
  --credentials /private/path/client.json \
  --scenario /path/to/installed/pm_pilot \
  --test EXISTING_TEST_ID \
  --output /private/path/handoff

career-lab engineer reproduce \
  --database /path/to/source.db \
  --credentials /private/path/client.json \
  --scenario /path/to/installed/pm_pilot \
  --pack /private/path/handoff \
  --output /private/path/reproduction
```

`--test` 可重复，最多选择 100 个已有记录；它们是待调查输入，不自动被判为错误。英文会话使用其英文安装目录。pack 需要读取权限；reproduce 另须已有 `act/tests.create` 权限。受限对象和动作范围继续生效，凭据撤销后不能再从原库复现。

输出包包含 `pack.json`（现有 EngineerPack）、`index.json`（成员及来源索引）、`config.json`、所选测试原件、获准案例材料、公开问题和对应语言的 README。场景引用指向可信环境中的原始场景，不把完整内部场景复制进任务包。

复现逐条使用原测试自己的历史时点和配置，不拿导出时的当前配置覆盖历史。`report.json` 保存原结果与实际重跑结果，`matches_record` 仅表示行为一致，`correctness_assessed=false`；不会把模型回答或人工兜底判成正确。原库缺失、权限不足、场景版本不匹配或包被篡改时非零退出，不产生成功报告。相同内容的重复命令可回读；不同内容不能覆盖既有目录。包与报告含授权业务内容，应按原会话的分享范围保存。

## 下一切片

配置修改提交、完整公开／隐藏探针回归、伪造回归报告核验、PM 证据回引和 probes-from-plan 待实现。当前命令不执行补丁、训练或模型调用，不改变 PM 配置、资源或评分。W13 保持部分交付，不能据这条基线复现链宣称工程师路径整包完成。
