# v4 Agent 原位插槽

入口 `mountV4AgentSlot(context)`，消费已审 `v4-host.ts`；当前按032指定的d34d695原字节继承v4-host.ts/contracts-v2.ts，只返回 `update/destroy`。组件不持凭据、transport、Command或恢复账本；输入草稿与一个原请求指针存入host的同一draft服务。未改根`ui.js`、页面、导航或全局CSS。

## 宿主节点

- `nodes.connection`：原`railAgent .agent-conn .conn-ways`内专供MCP控制的插入点。host只替换原MCP未接入占位行，保留手动任务包按钮。
- `nodes.activity`：原`.agent-log`标题下的真实记录插入点。组件不增加外层标题，不把旧示例当实际记录。
- `nodes.returns`：原“带回来”区域的服务端作品插入点。手动粘贴/上传/预览表单仍由v4保留。

只append/remove自身根节点；无顶层应用、路由或第二套人物/作品导航。`destroy`只解除监听、订阅和自身节点；不会签发、撤销、采用或提交。host在根重绘前按共享约定flush草稿。

## 操作与数据

`available`必须来自权威能力。没有接口时显示未接入/待核实，不能拿mock或浏览器缓存宣称已连接。

| host操作 | slot消费内容/发出的业务意图 |
|---|---|
| `query('delegations.list')` | `items`为当前session的公开委托，复用DelegationGrant的id/executor/capabilities/expires_at/revoked。可选`agent_label`供显示，`effective_status=active/expired/revoked`须为当前权威结果；缺该结果显示“状态待核实”，不按本机时钟推断有效。不得带token。此读取尚需公共实现冻结，类型在这里仅约定slot消费投影。 |
| `query('timeline')` | `events`为授权PublicEvent；只取type、可信executor、refs及公开summary/semantic_status/verification。不显示原始对象或内部payload，不从空窗口推断未操作。 |
| `query('work_products.list')` | `items`为授权WorkProductVersion；只展示外部Agent作者/执行者的未移除作品，版本与采用状态取服务器。支持显式读取next_cursor；不推算新版本。 |
| `command('delegations.create')` | 名称、明确选定的范围、read或read+act、到期时点。默认只读；整个工作区需主动选择。不授予submit，人工检查采用与正式提交分别走原入口。 |
| `command('delegations.revoke')` | 确切delegation_id；成功后回读当前委托状态，原作品与日志保留。 |
| `command('work_products.adopt')` | 确切product_id/product_version/expected_head和adopted，全部版本来自读取结果；不自动提交。打开作品用host.selectProduct，依据回跳用host.openReference。 |

list/timeline/workspace支持直接结果及现有V2Response嵌套外壳。跨session、私有引用或身份不匹配拒绝展示。名称、正文摘要、状态均以textContent渲染。界面语言变更只更新文案，不改工作语言、输入、光标或历史。

**连接配置由host安全提供。** 签发后的凭据由host负责一次性安全配置展示/导出，不能传入组件、draft或普通请求记录；本组件不读取command.result。host应在已确认签发后提供连接配置控件，不能把“创建授权”自动等同真实MCP已连接。该控件和权威委托状态尚须032正式接入。

**恢复语义：** host.command必须先持久化唯一请求并对已派发的不确定结果返回带requestId的unconfirmed/pending/failed/needs_context；组件只保留该指针。刷新只query，恢复只host.recover，host.retry只在用户明确点击时调用。若host反常抛错而没有返回请求ID，组件保存dispatchUnknown并禁用新动作，避免生成新键重复执行；host从唯一账本确认结果后才能清除此draft标记并重新挂载。组件不会自己猜请求或清除未知结果。

草稿保存失败时保留可编辑文字、禁用业务动作；明确输入再次成功保存后恢复。会话切换销毁旧slot；旧查询/命令响应不得回填新会话。模型未接入的明确semantic_status显示“等待模型接入”，明确rule_verified/rules_verified显示“规则核实”；其余不猜。

## 作者验证与实际边界

6项数据/意图测试及16项受控Chromium交互/布局检查通过；含默认read、范围、同键恢复、显式重试、撤销回读、确切版本采用、host手动流程保留、草稿/光标、旧响应隔离、存储失败保全、纯键盘、1080/390px、浅/深色及中英文案。深色采样等待真实主题文字颜色稳定，旧采样和失败日志保留。

浏览器fixture使用真实v4 CSS与Agent区DOM形状、受控V4HostAdapter；它不是新产品页面，也不是正式v4根入口/API通过。最终必须由032薄挂载后，在v4根入口核验真实委托、MCP、返回作品、采用与撤销，以及安全配置导出。M1的同事务history/标准mount/W02重绑和M3真实Codex双语仍未完成。

```sh
# apps/web
npx vitest run src/features/agent-native/model.test.ts
npm run build
# checkout根；先在自己的隔离端口启动Vite
W06_VITE_ORIGIN=http://127.0.0.1:19460 W06_BROWSER_EVIDENCE=/absolute/private/evidence node apps/web/src/features/agent-native/v4-slot.browser.mjs
```

浏览器工具使用本机Playwright；未在项目安装时须用CODEX_NODE_MODULES指定bundled依赖目录。不下载浏览器或新增依赖。实际产物/失败日志从本包回执进入。


2026-10-07 d34d695兼容核对：host.query直接业务DTO已支持；host.recover.result完整RequestResult不由组件拆解，只看host归一化status/requestId。新增可选semantic.roles/feedback/assistant互相独立，Agent权限与动作不使用其中一个状态冒充其他模块的判断。当前公共host明确禁用delegations.create/revoke，slot据available禁用按钮；待权威控制面正式接入后再做真实根入口验证。
