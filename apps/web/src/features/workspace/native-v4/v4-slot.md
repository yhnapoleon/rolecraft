# W03 v4 插槽接线

接口输入：032 已提交的 `a276074949ab7d2a367d6ac06f5b15363cdf3dae`，`apps/web/src/v4-host.ts` SHA-256 `fcad815cfc89576bc727bf30e3230bc1273adbf45013b50e8db732a5655d62d1`。以该文件及项目固定容器约定为准；本文件只明确 W03 实际 nodes 和本线语义，不另建公共类型。

`mount({host, nodes})` 返回 `update(snapshot)` / `destroy()`，别名 `mountWorkspaceSlot`。原 v4 决定布局、导航、纸面、文件夹动效和会话；本槽只绑定传入节点。没有凭据、raw transport、Command 构造、全局 root 或独立恢复日志。不要再同时挂 r9 的独立 `mount(container, WorkspaceClient)`，也不要挂 React 面板。

## 传入的原节点

节点全部可选，宿主按当前 v4 surface 传入；至少有一个节点。

| nodes 键 | 原位节点与职责 |
|---|---|
| title / body / purpose | 原 `#editor-title`、`#editor-body`、`[data-edit=purpose]`；绑定输入，不重建这些元素 |
| saveStatus | 原 `[data-save]`；显示本机草稿、权威保存、冲突或请求待确认 |
| actions | 原作品操作区的独占内部容器；保存、另存、比较、确切引用、只读恢复、显式重试、移除/恢复、采用；不含页头/导航 |
| sharing | 原作品分享/同事可见说明区域的内部容器；确切版本、接收者、问题和当前分享/撤回 |
| versions | 原作品历史区域；按需读取已保存版本，正文只读，引用交 `host.openReference` |
| investigation | 原 investigation workpaper 的节点；绑定原 question/review 控件和 `investigation-review-save`。`data-w03-block-text=<确切块ID>` 可绑定已有块的文字输入；保留其他块、ID、引用和原版结构，不另建调查表单 |
| taskTitle / taskGoal / newTask | 原新增事项控件及确认按钮；输入先存 host draft，明确点击后才写服务端 |
| tasks0 / tasks1 / tasks2 | 原三个优先级列中的 `.cards`；只给对应列表内部，不给整个工作板。按实际 task 数据渲染本列卡片与排序/暂放操作 |
| taskList | 单个列表 surface 的替代入口；与上述三个列入口二选一，不能同时传入重复列表 |
| newTitle / newBody / newPurpose / newKind / newProduct | 原作品起草控件和明确新建按钮；kind 沿 text/plan/test_plan/options/investigation，保存内容不因 kind 丢弃；缺失 kind 取 text |
| folder | 原 work-folder 事件面；只把实际 `data-folder-card` 对应的服务端作品传给 host.selectProduct，不新建作品导航或文件夹壳 |
| import | 原旧存档导入区域的内部容器；选择文件/练习/对象 → 只读 preview → 明确 apply，不自动全选 |

宿主对 v2 区域应停止旧 v1 写入事件路由；本槽在自身输入、按钮上阻止已接管事件继续冒泡。原有 v1 练习继续由原路径处理。原渲染器在替换节点前应 `flushDrafts`，保存焦点/选区，再 `destroy` 旧槽。不要把整个 `.paper.editor` 传为 actions/sharing，不要覆盖宿主输入节点。

## host 读写边界

读操作：`work_items.list`、`work_products.list`、`work_products.versions.list`，传 `cursor/limit` 与确切 product_id。槽接收直接 owned Page DTO，或冻结的 V2Response/Gateway read shell；不接受猜测的任意嵌套对象。多页 as_of 必须相同，跨会话对象/错误作品历史/不完整范围却称 private 均拒绝。读取期间变化只提示重读，不重发写操作。

写操作复用已冻结的业务 operation：事项 create/update/batch，作品 create/versions.create，shares.create/change 和 adopt。只传业务 payload。对象 expected_head/expected_revision 取实际已读取版本；顶层 Command、请求键与三轴版本绑定由宿主提供。正文、structured_payload、证据引用、task、legacy、source_return_id 都保留；编辑不把普通文字升级为业务批准、分享、执行或评分。

旧存档预览调用 `host.query('workspace_imports', {...input, mode:'preview'})`。这是已有 Operation 的 `preview_handler`，宿主必须映射到只读预览，不能当成 apply，也不能另造 preview operation。apply 用 `host.command('workspace_imports', {...input, mode:'apply', preview_storage_revision:真实预览值})`。input 来自原有 buildBrowserImport 纯函数；会话凭据、密钥键和未完成请求字段排除，只发送明确勾选的对象。host draft 只保存选择ID和已准备的脱敏输入/预览，不存未选中的私人作品。改变已恢复的选择时重新选择原存档；不删除原文件或浏览器记录。真实 id_map / version_map / unresolved 由服务端返回，旧测试不伪装为新练习运行。

`workspace` 的 host draft 键以 sessionId 开头，保存编辑草稿的 baseVersion/token/value，创建表单文字、分享问题与导入选择。`request-pointer` 只存宿主返回的 requestId、状态、operation 以及用于确认草稿的标识，不存 Command/payload、重试次数或第二本网络日志。`recover` 仅响应用户点击并读取原请求；`retry` 仅在用户主动点击时调用。失败、未确认和needs_context不会自动重发。保存中继续输入时，旧ACK不得清除新token的文字；比较确认也绑定所看head和草稿token。

## 验证边界

`slot-controller.test.ts` 检查单一host边界、冲突、迟到响应和权限数据形状；`import-slot.test.ts` 检查真实v4导出结构、只选择指定对象、凭据排除和预览身份。现有开发页 `native-v4/demo.html?slot=1` 是明确标注的合成host夹具，没有HTTP/worker/模型；它用于检查原输入节点、草稿/光标、卸载挂载、事项排序和只读恢复调用次数。原 `demo.html` 无参数仍是先前真实HTTP部件夹具，两者证据不可混记。

本槽不生成模型判断，保存/分享事实不贴语义评价标签。三同事/助手/Judge 的“等待模型接入”和“规则核实”由对应业务槽按真实DTO展示。正式v4根入口、真实W02/W05提交组合、完整中英文工作语言、受限Agent显式移除权限和全部AC仍须准确组合验证；开发夹具和作者单测不能替代这些证据。


## 已提交宿主实现的适配核对

只读核对了032的 `44d6df0`：query当前返回已拆出的owned DTO；recover返回完整只读RequestResult，其中 `response.result` 为原事务结果。W03同时校验请求ID、会话、operation、completed与read_only，再处理保存确认；不会把RequestResult壳当作已保存正文。

`44d6df0` 的 readRoute 尚不支持 `workspace_imports` 的只读preview。M3需要032补这一真实host能力；W03保持现有Operation及preview_handler语义，不用command预览伪造事务成功、不自造路由。普通作品/事项与分享不依赖此导入补齐。共享类型后续迁移到contracts-v2属于032；W03不创作该公共文件。
