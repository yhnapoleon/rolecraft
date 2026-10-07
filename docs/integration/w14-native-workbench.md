# v4 公共数据层与模块接线

本页是032的实现与复现入口。v4（app/ui.js）是唯一用户界面；独立vertical-workbench只保留DEV下的`?dev-v2=1`诊断入口，不加功能、不作为产品验收依据。本批是M1部分实现，不能称M1或整包完成。

## 当前实际结果

- 正常根入口创建固定工作语言的v2会话，凭据仍只由WorkspaceStore管理；`protocol`明确区分旧v1与新v2。旧v1会话及本机作品保留原路径，未自动迁移。
- LiveWorkbench/V4LiveData把真实v2材料、配置、试用投影到原v4。设置在服务器验证base并产生下一版本，客户端不加版本、不预填测试问题、不替用户选择工作项。
- V4DataHost是v2唯一Command/恢复journal及模块draft服务；模块不拿token/raw transport。recover只GET，retry是主动新尝试；网络/5xx保留未确认，存储失败不发送命令并保全草稿。workspace_imports preview经原只读handler，不能借query执行apply。
- objects.read走Gateway；workbench.read在一个授权view返回固定语言、三轴点、独立roles/feedback/assistant语义状态、材料和timeline。当前provider local，模型语义均“等待模型接入”。
- W02真实ScenarioFactAdapter已接W05完整14项规则/反馈和实际历史，提交→worker反馈→修订回归通过。全文证明只接受原文件每个片段均公开、身份/时间/原文全部吻合的确切全文；不删除或缩短证明规避验证。
- W06已在标准serve/worker装配，PublicHistoryWindow在当前查询事务内读实际公开事件和材料读取回执；目录不冒充已获取知识。端口离开事务后失效。v4授权状态列表、凭据一次性配置导出与真实Codex实操尚未接通。host将delegations.create/revoke明确置为不可用并在派发前拒绝：W06控制面返回含私密token且尚无统一事务回执，不能当普通Command发送后误报失败、再重试签发第二份授权。

## 复现

原c15数据库完整保留。本批通过SQLite backup建了新副本，旧v1记录随副本可读；未改签旧v2场景。实际进程：

```sh
.venv/bin/career-lab serve --host 127.0.0.1 --port 18832 --database-url sqlite:///runs/local/expansion-v3/W14/20261007-032-v4-host/v4-host.db --provider local
.venv/bin/career-lab worker --database-url sqlite:///runs/local/expansion-v3/W14/20261007-032-v4-host/v4-host.db --provider local
```

在apps/web运行`ROLECRAFT_API_TARGET=http://127.0.0.1:18832 npm run dev -- --port 18830`，打开`http://127.0.0.1:18830/`。独立QA使用自己的端口/浏览器profile和数据库，避免同源练习选择互相影响。当前只装了中文运行包；英文请求明确返回work_language_unavailable，不静默改成中文。

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

### 模块独占slot与统一host类型

共享类型在`apps/web/src/v4-host.ts`（`V4HostAdapter`、`V4SlotContext`、`V4SlotHandle`），基础wire类型现由公共`contracts-v2.ts`导出，不再依赖W03目录。`v4-data-host.ts`已实现统一命令/草稿journal、只读recover和主动retry，`v4-operations.ts`集中维护业务操作到正式路由的映射；已接入LiveWorkbench的新v2会话、材料、配置和试用；模块原位挂载尚未完成。模块不拿token或raw transport，不构造Command/envelope、猜版本或维护第二恢复流程；只调用host.query/command/recover/retry及同一draft存储。`command`只收业务意图，`recover`只恢复旧请求，真实重试必须单独显式动作。工作语言从固定session读取，界面语言独立；反馈自己的semantic_status通过反馈DTO读取。

| 实施线 | 专属slot文件（由046按此登记放行） | 032提供的真实nodes与数据 | 模块作者须自己完成/去掉 |
|---|---|---|---|
| W03／047 | `apps/web/src/features/workspace/native-v4/v4-slot.ts`，辅助文件限同目录 | 工作板事项区、任务卡操作、`#ws-object`中原编辑/调查节点、文件夹节点；currentTask/currentProduct、任务/作品/版本/分享数据与统一commands/drafts | 实现事项/编辑/调查/分享事件和原位渲染、冲突/草稿保全、解绑；去掉组件自带页头、独立作品导航和整页shell。不要改根ui.js。 |
| W04／039 | `apps/web/src/features/roles-native/v4-slot.ts`、`v4-request-slot.ts`，辅助文件限同目录 | 原railTeam/railChat的people/thread/composer节点、申请弹窗节点；确切role/task/share上下文、请求/回复/展示/业务决定数据与commands | 实现原同事区发送/恢复/显示回执和申请结果事件/渲染；保留host人物选择及头像样式，不重复人物导航/标题或另起面板。 |
| W05／040 | `apps/web/src/features/feedback-native/v4-slot.ts`，辅助文件限同目录 | sheetDeliver的原表单节点；review-main/review-side节点；surface=submission或feedback，确切产品/提交/反馈、独立semantic_status、原文回跳及draft/command | 实现两surface的原位内容、提交/补证/修订事件和解绑；去掉独立页头/导航/全局选择态，不自存反馈请求日志。 |
| W06／044 | `apps/web/src/features/agent-native/v4-slot.ts`，辅助文件限同目录（新slot范围，不沿用旧“无前端组件”限制） | `railAgent .agent-conn .conn-ways`、`.agent-log`和原任务包/回传/采用位置；准确refs、真实授权状态/到期/能力、委托callbacks、操作/回传结果 | 自己完成授权/MCP连接/撤销/日志/回传的slot胶水和渲染；沿用原Agent布局，去掉独立连接页或模块导航，不改根ui.js、不复制凭据。 |

032只维护根ui.js的薄挂载和数据适配、workbench-entry、LiveWorkbench/统一session与command数据层。根渲染前保全host草稿和焦点，旧slot先destroy；afterRender对实际存在的nodes执行mount/update。模块输入先进入同一host draft存储，输入焦点中不得重建编辑节点；切换会话/路由解除订阅，不在mount/destroy时自动生成、分享或提交。模块可并行实现slot及自有样式对齐，具体范围以046更新后的登记为准。039树里未提交W03文件不得引入或由039提交；本树只继承固定owned哈希。

本轮中文纵切按用户17:16决定保存截图与实际操作记录；最终验收再录屏。共享接口和模块组合仅依据准确commit/场景hash/契约与当前mode验证，开发自测页成功不计v4通过。

所有模块沿`docs/design/frontend-style.md`及现有CSS变量，不挂`WorkspacePanel.tsx`或`recovery-browser.tsx`早期React页，不把独立CSS与新导航原样覆盖v4。相关切片验浅/深色、小屏、键盘和草稿恢复。v4负责路由、选择态、焦点/动效及mount/destroy；模块负责自身业务内容，不能创建顶层应用或另一套恢复流程。

宿主返回约定：`query`返回正式Gateway读取结果中的业务DTO；`command`返回`{requestId,status,result}`，其中result为业务结果。`recover`/`retry`的恢复结果包含原RequestResult及jobs；恢复只GET，网络/5xx后的未确认命令会阻止新的写入。服务器明确返回request_not_found后，只有用户主动retry才用新边界和新请求键重新尝试。模型任务仅通过用户主动的jobs.refresh重试；旧命令保持不变。draft写失败保留内存文字，flushDrafts补存，模块不得在失败时销毁唯一输入。

snapshot新增独立`semantic.roles/feedback/assistant`状态，值为waiting_model/model/unavailable；未取得正式workbench.read时三项均unavailable，不从同事mode推断反馈能力。query映射、只读导入预览、统一journal、正式session/context与LiveWorkbench切换已实现；模块原位挂载仍在实施。semantic字段为兼容a276消费者保持可选，实际host始终提供三项状态。

公共接口同步项属于同一数据层任务：objects读取已移入Gateway Operation（turns.display保留统一入口）；完整Command和只读恢复从同一账本取；工作语言固定到会话/任务上下文；绑定046固定的W02/W05准确输入后真实重绑场景，记录冻结期必要变更理由。每个可测切片独立提交并给043在v4根入口验证。

## 固定输入与验证边界

准确模块输入及逐文件SHA见[v4-fixed-inputs.json](v4-fixed-inputs.json)。W02 a8ec5b8、W03 0dced28、W04 a5a94fa、W05 81828f6、W06 8e8a63d；仅复制各自owned文件，没有复制他人的公共层或未提交活动树。W03/W06新slot已继承，尚未挂进正常v4。

原位已实操：创建中文v2练习；打开真实委托；测试c0取得500元原文；从练习列表重开并刷新后保留测试；原设置将人数20改为12，服务器产生config v1、政策源v2/索引v1，原c0测试保持500元。旧v1调查作品仍可见。截图、操作记录与数据库核对进入`runs/local/expansion-v3/W14/20261007-032-v4-host/`，不是七步验收。

本批后端组合/契约16项通过；前端与状态回归结果见同目录日志。Vite打包通过，但完整npm build当前被W03 slot-controller.test.ts三处Mock返回status被推宽为string的TypeScript错误阻挡（15、23、24行）。未改owner文件、排除测试或放宽V4CommandResult掩盖错误。W03/W06作者另报告公共host继承受自动审批阻挡；其状态不由032伪造更改。

## 接下来

1. 完成W03原位薄挂载、确切任务/作品选择和草稿生命周期；只有插槽接管对应写路径后才启用v4-workspace-projection，避免用服务端空列表覆盖尚在本机的作品。原本机作品编辑当前继续保全，不能称服务端作品保存已完成。
2. 继承039/040的准确slot提交，完成同事/申请、作品提交到反馈/补证/修订；中文七步A/B截图与操作记录。
3. 完成W06授权列表/控制面恢复/一次性私密配置导出，补W04真实模型持久调用端口；英文真实重绑、AC15补练、干净环境和小屏验证。
4. 外部真实模型配置到位后只改配置复验，核对单次调用与全部AC；当前不新增线上费用、不声称模型质量已验证。

只在本人分支本地commit。没有push、merge、PR或部署。整包reviewed/integrated留最终独立验收。
