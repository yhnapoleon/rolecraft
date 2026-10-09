# v4 原位工作台运行与验证

2026-10-07，052主流程检查点。v4仍为唯一用户入口；开发外壳不作为验收。最新精确输入在[v4-fixed-inputs.json](https://github.com/yhnapoleon/rolecraft/blob/2c07160b5e829ac08afb8a31667440bbda72df73/docs/integration/v4-fixed-inputs.json)。原032 c18输入和运行证据保存在对应交接/回执。

## 当前原位能力

统一host挂W03作品/事项，W04三同事与资源申请，W05普通评审、正式提交、分段反馈、异议补证与修订。资源审批安装W04协商到W02真实规则：请求和生效条款分别保存；应用条件由服务器确认。14项反馈使用W02实际历史事实，业务回应引用真实审批决定。反馈失败可恢复原结果并由用户显式重新请求，没有自动模型重试。

场景历史内容按原manifest、逐文件hash与原文span验证；不执行旧运行代码，不改签旧绑定。旧会话原记录只读，原作品/回复/提交/反馈继续可读，界面提供中英文说明和新练习入口。新会话工作语言在创建时固定；单一API/worker按绑定选择中英运行时。

## 固定准备与启动

从本工作区根目录执行。每次源码或冻结契约变更后使用新的输出目录，保留旧目录与数据库。生成器只重新生成runtime与外层manifest，任何业务文件差异都报错。

```sh
.venv/bin/python docs/integration/archive_scenarios.py d34d695 a5779ea 92aed63
.venv/bin/python docs/integration/prepare_scenarios.py --output runs/local/prepared/<unique-build>
CAREER_LAB_SCENARIO_CATALOG="$PWD/runs/local/prepared/<unique-build>/catalog.json" .venv/bin/python -m career_lab.cli serve --host 127.0.0.1 --port 18832 --database-url "sqlite:///$PWD/runs/local/<unique-db>.db" --provider local
# 等API初始化完成后另启worker，使用同一个catalog和数据库
CAREER_LAB_SCENARIO_CATALOG="$PWD/runs/local/prepared/<unique-build>/catalog.json" .venv/bin/python -m career_lab.cli worker --database-url "sqlite:///$PWD/runs/local/<unique-db>.db" --provider local
# 在apps/web运行
ROLECRAFT_API_TARGET=http://127.0.0.1:18832 npm run dev -- --port 18830 --strictPort
```

默认历史目录`runs/local/scenario-archive`应与数据库一同保留；可用`CAREER_LAB_SCENARIO_ARCHIVE`指定持久位置。目录以原场景hash命名，新运行时启动会保存当前内容。既有开发库需要先按实际来源提交导入旧版本，不能用最新内容替换旧hash。缺少原件时保留浏览器记录并显示可理解的恢复说明，不能宣称该版本已恢复。

本轮独立浏览器入口为19530/API19532，主地址18830/API18832保持可用。进程、精确catalog和数据库在`runs/local/expansion-v3/W14/20261007-052-mainflow/`的两份processes文件中；日志、失败记录、截图与操作记录同目录。不要同时初始化同一个全新SQLite库的API与worker。

## 验证边界

21项标准组合/双语/历史恢复/协商/契约测试、63项反馈权限与溯源检查、213项前端测试（另7项跳过）、72项状态回归和完整构建通过。作者实操已覆盖政策500→500→400、100→60协商、版本分享撤回、正式暂缓提交、异议补证、修订、普通评审及显式失败恢复；逐步修复期间有不同源码切片，不能合称一个固定候选的完整A/B通过。

中文A/B仍需在本检查点完整复跑和截图；英文完整浏览器工作、补练新会话关联、W06控制面挂载、W04真实模型持久调用/立场端口、干净环境、小屏/键盘/深浅色、SQ和各包AC均尚未完整验收。真实provider、模型训练与外部数据未到位。此检查点是partial，不是M-A或整包完成；不标待Claude纵切审。

## 容器与所有权

`v4-mounts.ts`只管理原DOM的生命周期；`v4-data-host.ts`持有唯一请求日志与草稿，`v4-live-data.ts`/`workbench-live.ts`投影服务端数据。各feature仍在原包工作区修改后按准确提交原字节继承。v4原任务表单/纸面/分享，原同事thread/composer，原res-form，原提交sheet和review-main/side分别挂自有slot。引用按objects.read经过Gateway读取确切版本；选补证只用已实际打开材料的原引用，不把目录当作阅读证据。

本地任务分支commit已授权；不push/merge/部署。reviewed/integrated留独立审查。
