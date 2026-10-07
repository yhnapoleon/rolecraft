# 中文纵切部分候选：启动和接续

2026-10-07 16:37用户纠正：v4是唯一用户界面。92aed63将独立接线页替代v4根入口的做法已撤回。本文记录后端与开发自测边界。当前是 W14 部分候选，完整七步、录屏和最终验收没有宣称通过。源码身份与精确模块输入以项目接口预览中的 `w14-native-vertical-20261007/manifest.json` 为准。

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

正常根入口为 `http://127.0.0.1:18830/`，**默认v4（app/ui.js）**，`?v2=1`也进入v4。当前v4数据桥仍使用v1；接下来在原工作板、文件夹、同事与反馈位置接入v2，旧v1记录仍可读。独立接线页仅在开发服务器的 `?dev-v2=1` 可打开，标明“开发自测”，不作为用户入口或纵切验收依据，不再增加功能。生产构建不启用此参数。独立QA可改成自己的空数据库及未占用端口，并同步修改前端代理；不要复用旧工作树的数据库/凭据。

## v4容器约定与三步接线

以下为046确认的实施约定，尚未实现的部分不计通过。复用043在项目产品实操QA中的原位映射。`LiveWorkbench`保留为v4唯一界面数据门面：会话显式分流v1/v2，新练习创建v2；旧v1从原记录和原凭据读取，不隐式迁移、不混写。模块只拿同一会话的数据/命令adapter；v2只有一套凭据、完整Command与恢复journal。复用现有transport/客户端逻辑，但不把开发页的独立恢复账本逐个带进v4。

| 步骤/部件 | v4现有容器 | 数据、命令和生命周期 | 本步正常UI验收 |
|---|---|---|---|
| 1：岗位、会话、工作板 | renderCareers/renderEntry；`#ws-stage`与原工作板/任务卡 | 创建固定zh/en工作语言的v2会话，UI语言切换不改历史；原v1会话读路径保留。会话切换时解绑订阅，先保全草稿。 | 根入口创建新练习，刷新重开仍是同一v2；旧v1作品/凭据不变，没有另一个工作台。 |
| 1：材料、配置、试用 | taskView的`#ws-object`、docBody/bench；sheetConfig | 授权材料与确切引用走统一query；配置、真实试用、索引更新走同一Command恢复。版本和实际配置由服务器给出；不预填F01，不替用户挑工作项，不搬入客户端推算版本。 | 原位置读资料、c0测试、显式改配置与重测；真实源/索引差异和旧引用保留，刷新后读回。 |
| 2：W03事项/作品/分享 | 原任务卡、work-folder、workView的`.work-grid`/`.paper.editor`、`#editor-title`/`#editor-body` | 统一adapter接事项、草稿、版本、分享及撤回；绑定确切productRef。W03 native-v4只挂编辑/分享功能，不重复页眉、作品导航或外层壳；原文件夹/目录仍负责选择。卸载前保存草稿并解除监听。 | 本机与服务端保存可区分；分享v2后保存v3，同事仍只收到v2；可撤回，不把附文当分享；草稿、光标与冲突保留。 |
| 2：调查工作纸 | 原investigation-view及`#ws-object`对应作品区域 | 保留原布局、块身份和任务关联，使用真实material/test引用与统一版本保存，不另起调查表单。 | 对照真实旧测试和新资料，修改后重测，原文/原引用及历史版本不改写。 |
| 2：W04同事/申请 | `#ws-rail .rail-body`下railTeam/railChat、`#chat-input`；sheetResources | 原人物选择、头像、颜色、会话composer保留；模块去掉重复人物导航/标题与独立shell。turn、公开历史、显示回执、申请决定经统一adapter；只在回复实际显示后记display。申请必须真实决定成功才生效。 | 三同事在原侧栏真实保存/恢复/追问；普通输入不改写；版本分享可追溯；批准前后资源明确。 |
| 3：W05提交/反馈/修订 | `#sheet`内sheetDeliver/`#live-deliver`；`.review-main`、`.review-side`及原反馈侧栏 | 模块按surface=submission/feedback提供原生内容，去掉独立页头/导航。替换旧六字段协议为明确作品版本与决定；分段反馈/补证/修订走统一命令。反馈用自身semantic_status/条目来源，装046固定的完整14项输入，不复用同事mode。引用回跳沿review-side。 | 原交付入口完成提交→worker反馈→确切依据→异议补证→修订重交，旧记录不改写；停做/暂缓不过度裁决。 |
| 3：W06 Agent | 原railAgent、`.agent-conn`、`.agent-log`与任务包/回传/采用位置 | 按044的v4-agent-mount-request接授权、MCP观察/操作/回传/撤销；模块只接原槽位，不创建独立面板或第二权限/队列。公共history/mount可先单独交付，不等本步UI齐。 | 原Agent区能授权、真实读取/回传、恢复、采用及撤销；执行、采用、验证分开呈现。 |

所有模块沿`docs/design/frontend-style.md`及现有CSS变量，不挂`WorkspacePanel.tsx`或`recovery-browser.tsx`早期React页，不把独立CSS与新导航原样覆盖v4。相关切片验浅/深色、小屏、键盘和草稿恢复。v4负责路由、选择态、焦点/动效及mount/destroy；模块负责自身业务内容，不能创建顶层应用或另一套恢复流程。

公共接口同步项属于同一数据层任务：objects读取移入Gateway Operation（turns.display已有正式Operation，保留统一入口）；完整Command和只读恢复从同一账本取；工作语言固定到会话/任务上下文；绑定046固定的W02/W05准确输入后真实重绑场景，记录冻结期必要变更理由。每个可测切片独立提交并给043在v4根入口验证。

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

下述接线页浏览器结果只作开发自测，不能计入v4纵切通过。本轮公共回归531通过/1跳过；新增纵切集成10通过；前端152通过/7跳过、72项状态回归通过、构建通过。原第一次公共回归的4条失败及真实追问失败记录均保留。浏览器工作树验证覆盖500→旧索引500→新索引400、容量申请拒绝/批准后30→60、正常命名问题、跨worker追问与草稿重开；不冒充最终冻结候选完整七步验收。
