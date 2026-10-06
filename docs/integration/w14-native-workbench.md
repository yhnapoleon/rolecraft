# 原生工作台的 Gateway 接线边界

产品入口继续使用 `src/workbench-entry.ts` 加 `src/app/ui.js` 的原生 DOM 工作台，沿用 frontend-style。W03 的独立 React 面板不挂入此入口。

`LiveWorkbench.gatewayTransport(attempt)` 从已有 WorkspaceStore 在每次请求时取得该 attempt 的凭据，返回 `createGatewayTransport`。凭据不复制到任务、作品、导出包或第二份会话仓储。传输入口支持 GET/POST/PATCH/DELETE，只允许同源、同会话路径；写操作须已有完整 v2 Command，不能在传输时补造协议、请求键或业务版本。

返回 PublicTransactionResult 和公开读取包装保持原样。消费者负责解析其业务 DTO，并继续使用模块唯一的请求/草稿记录。网络中断、无法解析的正文或旧协议成功形状返回 response_unconfirmed；已知403/409等拒绝保留服务端code与正文。传输层不重试、不自行刷新版本、不把未知结果记为失败保存。

此入口提供网络接线能力，现有事项/作品操作尚未改为调用W03客户端；旧v1会话也不会被隐式转换成v2会话。后续须在固定W02/W03输入和相应公共接口到位后，将原生事件动作接至真实模块，并保持本机草稿、明确保存、冲突比较、导入预览和准确版本分享。RoleReply真实渲染后才调用显式turns.display；生成完成或轮询不表示已经展示，更不表示用户理解。

目前的验证包括TypeScript/生产构建、传输与凭据边界、真实HTTP的Gateway PATCH/幂等/请求恢复/409及既有前端回归。HTTP任务handler是明确的公共协议夹具，只验证网络与公共事务，不代替W03业务、真实模型或最终产品QA。
