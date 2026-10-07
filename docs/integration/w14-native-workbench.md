# 中文纵切部分候选：启动和接续

2026-10-07 按用户“先固定可测候选，不等所有模块齐”的决定冻结。当前是 W14 部分候选，完整七步、录屏和最终验收没有宣称通过。源码身份与精确模块输入以项目接口预览中的 `w14-native-vertical-20261007/manifest.json` 为准。

## 正常入口

仓库根运行下列两条命令，API 与 worker 必须共用同一个数据库和 provider。当前默认装配函数为 `career_lab.api.vertical_runtime.create_runtime_app`；不需测试bootstrap或私有router。

```sh
.venv/bin/career-lab serve --host 127.0.0.1 --port 18832 --database-url sqlite:///runs/local/expansion-v3/W14/20261007-032-vertical/candidate-c15.db --provider local
.venv/bin/career-lab worker --database-url sqlite:///runs/local/expansion-v3/W14/20261007-032-vertical/candidate-c15.db --provider local
```

在 `apps/web` 运行：

```sh
ROLECRAFT_API_TARGET=http://127.0.0.1:18832 npm run dev -- --port 18830
```

正常根入口为 `http://127.0.0.1:18830/`，**默认v2**；`?v2=1`与根入口相同。`?legacy=1`保留旧v1入口，旧会话不会迁移为v2。点击“进入工作区”或“新练习”创建隔离会话，不清除已有浏览器存档。独立QA可改成自己的空数据库及未占用端口，并同步修改前端代理；不要复用旧工作树的数据库/凭据。

## 当前可测与缺口

- 标准装配含W02、W03后端、W04 r7生产私有端口与原生同事部件、W05 r9生产reader/反馈worker与原生反馈部件。材料、配置、助手试用、实际资源申请、角色发送/保存/追问/显示记录可测。
- W03新原生作品部件尚未固定到本候选；“我的作品”仍显示接入提示。作品、分享、提交接口和W05两轮反馈已由真实API/SQLite/公共worker验证，但**完整浏览器创建作品→分享→提交链尚未完成**。W03后续从031固定的准确owned输入装配，不复制它的旧公共层。
- W02业务内容仍为b821b0e r6。运行绑定和EvaluationBundle已真实生成；新中文内容检查点524dca4及英文包尚未装入。旧测试数据库及旧绑定保留，不静默改签历史会话。
- 当前W05使用冻结的7项本地advisory责任政策及准确源码哈希，语义没有评分。技术原稿14项rubric与政策更新后复测/调整的完整反馈由040/041后续交付，不能将这7项等同最终rubric。
- 全链PostgreSQL、英文体验、真实provider质量、七步录屏和独立产品QA未完成；已知包级剩余项仍见任务登记及排期清单。

## 模型与重试

当前 `--provider local`：角色界面为 `local_reference`；反馈为 `placeholder`，语义显示“等待模型接入”，可核实内容标“规则核实”。没有线上调用、模型下载或费用。

后续兼容provider使用 `CAREER_LAB_KEY_FILE`、`CAREER_LAB_BASE_URL`、`CAREER_LAB_MODEL`；key仅由进程读取本机文件，不进数据库/源码/日志。支持的真实adapter要求`retries=0`；标准CLI和直接API工厂的真实模型handler均禁止自动重排，租约过期也不能自行重调。Judge修复循环的同一输入被公共单次调用包装拦住；实际线上语义与调用计数仍须接真实配置后独立验证，当前不声称通过。

用户显式 `jobs.refresh` 可恢复failed模型任务及needs_context，重新检查原身份、scope、subject和上下文。普通永久输出冲突仍不能刷新。原请求键恢复不自动发送新模型调用；失败输入和旧记录保留。

## 精确数据与公共接口

`VerticalClient`统一v2凭据、Command和原请求恢复；W03继续用唯一WorkspaceClient/journal。角色和反馈部件只使用注入adapter，不持有token。`turns.display`仅在确切公开回复实际可见后记录，不能把轮询当展示或理解。

W05：`install_lifecycle`在同一事务保存提交/评审并排反馈job；`create_feedback_handler`消费实际固定subject，使用StoreEvidenceReader与W02授权材料/历史规则端口，经真实WorkerClaim写反馈。`query_at`读取真实三轴历史点并重查当前权限；原作品形成点、提交点与读取点不互换。源文件必须全部对当前调用者可见才作为全文坐标基准，部分不可见则相关来源待核验，不传私有全文或拼假引文。

角色：公共`activated_catalog`及历史来源恢复把创作包零时点映射为真实会话激活；角色获知仍由实际事件/分享决定。此修复处理真实第二轮`reference_time_mismatch`，未重写旧记录或放宽W02引用验证。

`GET /objects/{kind}/{id}/{version}`回跳授权的精确版本，提交后仍可只读。阅读事件引用只支持明确的公开文本投影，不接受任意原始事件quote。

### 给W06的范围

已可用：`career_lab.api.vertical_reads.public_event_history(store, registry, auth, at, since_seq=0, view=None)`；在现有query里传`view`，避免SQLite嵌套事务。它按持久化operation选择已安装projector，返回真正授权的PublicEvent元组；`GET /timeline`也含events。材料目录不冒充阅读，`actions/read_material`保存实际读取及片段；只读材料端点见上。

**尚不可用：** W06请求的同query `public_history(view,page,auth) -> PublicHistoryWindow`完整扫描窗口及全部MaterialReadReceipt尚未实现；`mount_delegations`也未在标准工厂调用，本候选未安装W06 owned包，MCP生产链不能标通过。后续在既有端口上补薄适配与一次挂载，不能另造权限/时钟/队列。具体请求沿项目`完成回执/W06/036-production-mount-request.json`。

## 重现与验证

仅在公共源已固定后运行，实际W02生成器在临时目录生成整包，再拒绝任何业务文件差异，只安装runtime与外层manifest：

```sh
.venv/bin/python -m career_lab.contracts.v2.export --output docs/contracts/expansion-v3
.venv/bin/python docs/integration/rebind_runtime.py --with-w05 --evidence runs/local/rebind-evidence.json
.venv/bin/python docs/integration/check_public.py --artifacts runs/local/new-public-check
.venv/bin/python -m pytest -q --tb=short tests/integration/test_w14_vertical_runtime.py --basetemp=/private/tmp/rolecraft-vertical-check
```

本轮公共回归531通过/1跳过；新增纵切集成10通过；前端152通过/7跳过、72项状态回归通过、构建通过。原第一次公共回归的4条失败及真实追问失败记录均保留。浏览器工作树验证覆盖500→旧索引500→新索引400、容量申请拒绝/批准后30→60、正常命名问题、跨worker追问与草稿重开；不冒充最终冻结候选完整七步验收。
