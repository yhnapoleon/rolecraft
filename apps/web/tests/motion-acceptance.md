# 资料连续展开与作品文件夹验收

2026-10-05，024。实现位于现有工作台源码，基于 `origin/main` `10759075edd2cff289417c05719b4f903c98c3a2`，分支 `feat/document-folder-motion`。以下保留 024 独立阶段的验收与参考证据；其代码现已与 023 调查工作纸整合，最新组合验证见[前端说明](../README.md#025-整合验证)。未部署或购买。

## 如何体验

打开 <http://127.0.0.1:18530/#/work>。本轮独立浏览器练习包含三份标题以“验收示例”开头的合成作品，另有一份用于移除边界验证的合成作品留在“已移除作品”。这些内容不是真人研究或真实项目判断。其他浏览器的存档按来源隔离；首次打开需接手工作，在事项中建立至少两份作品才能看到文件夹。

1. 工作板 → 资料 → 点击任一资料卡；观察纸面、标题和图标连续进入原文档。点“工作板”或 Escape 返回原卡；可在展开途中返回并再次打开。
2. 工作板 → “回应政策问答的开放请求” → 点击墨色文件夹；作品从来源位置飞出，横向平铺。点击任一完整卡片进入对应原作品，包括待检查的 Agent 测试计划。
3. 再点来源文件夹、“收起”或 Escape，卡片回收到来源位置。桌面三张同时可读；更多作品或窄屏使用横向滚动。键盘 ArrowDown 打开，左右键与 Home/End 选择，Enter 打开，Escape 收回并恢复来源焦点。

## 官方参考、许可与明确差异

| 对象 | 核对结果与实现取舍 |
|---|---|
| [Motion JS App Store](https://motion.dev/examples/js-app-store-layout) | 实际打开官方演示，操作展开、Escape 回收和快速打断。公开教程指定共享元素 FLIP、`duration: 0.5`、`ease: [0.39, 0.14, 0.26, 1]`；该曲线无弹簧过冲。完整示例源码及 `animateLayout` 属于 Motion+，未取得或购买。 |
| [Motion layout 文档](https://motion.dev/docs/layout-animations) | `animateLayout` 为 Motion+ 能力。这里自行实现矩形测量、独立纸面层与子内容反向缩放，用公开时长/曲线，不导入或复制私有运行时代码。 |
| [animateView](https://motion.dev/docs/animate-view) | 原生快照过渡的中断行为与即时可反向布局不同，因此资料核心转场没有改成普通快照淡入或排队切换。 |
| [React Bits Folder](https://reactbits.dev/components/folder) | 实际操作开合，读取固定版本 [JSX](https://github.com/DavidHDev/react-bits/blob/ca44b3f9ee180676a06d7de8ec6bea84cddff85b/src/content/Components/Folder/Folder.jsx)、[CSS](https://github.com/DavidHDev/react-bits/blob/ca44b3f9ee180676a06d7de8ec6bea84cddff85b/src/content/Components/Folder/Folder.css) 及 [Tailwind 变体](https://github.com/DavidHDev/react-bits/blob/ca44b3f9ee180676a06d7de8ec6bea84cddff85b/src/tailwind/Components/Folder/Folder.jsx)。保留名义 100×80 封面、左右 `skew(±15deg) scaleY(.6)`、300ms ease-in-out 与抬升 8px/200ms ease-in；入口统一缩为 .68。 |
| Folder 许可 | 官方为 MIT + Commons Clause；完整版权与许可保存在 [react-bits-folder.txt](../licenses/react-bits-folder.txt)。本次作为产品内组件集成，不单独分发或出售组件。 |

产品保持既有冷灰画布、玻璃层、纸面、字体、圆角和角色/状态色。Motion 原例是图片卡到居中模态框；这里是既有纸面资料卡到工作台内原文档，团队栏保留。标题从原卡 15px 到文档 24px，正文保持正常比例，通过纸面裁切揭示；不是原例图片内容的像素级复制。

Folder 官网 CSS 变体写入但未使用 `--magnet-x/y`，官方 Tailwind 变体包含中心距离 × .15 的位移。最初移植曾补齐该跟手机制。用户在本轮真实预览后明确要求每张作品可读、横向平铺、各自打开并再次点击收回；最终纸卡不再使用重叠扇形或随鼠标摆动，采用宽 236px、间距 18px（窄屏 14px）的稳定阅读位置。封面保留原形变，飞出/回收采用 500ms 同一曲线，并从当前呈现矩形反向。这是本轮明确变更后的交互，不宣称与原三纸扇形完全相同。

## 动态与截图证据

以下 GIF 由本轮真实浏览器截图帧组成，无生成的中间画面；约 10fps，只用于看路径和层次，顺滑度仍以可操作预览为准。帧序列和采集时间在同目录 `frames/`。

- [实际作品飞出与收回](screenshots/motion-024/folder-open-close.gif)
- [实际资料展开](screenshots/motion-024/document-expand.gif) · [390px 资料展开](screenshots/motion-024/document-mobile-expand.gif)
- [官方 Motion 原演示展开](screenshots/motion-024/motion-reference.gif)
- [桌面作品卡](screenshots/motion-024/folder-desktop.jpg) · [390px 作品卡](screenshots/motion-024/folder-mobile-390.jpg) · [390px 文档](screenshots/motion-024/document-mobile-390.jpg)
- [资料中途反向几何](screenshots/motion-024/document-interruption.json) · [作品束中途反向几何](screenshots/motion-024/folder-interruption.json)

## 已验证

| 检查 | 结果 |
|---|---|
| 原有前端回归与新增检查 | `ROLECRAFT_TEST_API=http://127.0.0.1:18532 npm test`：89 项 Vitest（含 6 项真实 HTTP/worker）与 67 项状态行为回归通过。覆盖现有 Agent 测试作品、调查视图、恢复及交付。 |
| 构建 | TypeScript/Vite 构建、`git diff --check` 通过。 |
| 项目入口检查 | 四入口已回读；项目检查脚本仅保留本轮开始前已有的“未约定的根目录：rolecraft”错误。新增本地链接与章节锚点未报错，未借此任务调整无关目录规则。 |
| 资料动态 | 实测纸面轮廓扩展、标题/图标移动、正文裁切、反向、原卡位置与焦点；约 85ms 间隔连续开/关/开时保留中间几何，没有先跳到终点。文档代理层独立于后端刷新，异步阅读动作继续沿用。 |
| 作品语义 | 0/1 份保持原事项卡；2/3/4 份实际创建并体验。完整长标题、待检查 Agent 计划、全部作品横向选择、指定作品打开、合成第四份作品移除后不再列出均核对。无嵌套按钮。 |
| 作品动态 | 实测封面开合、各卡从同一来源飞出、横排、回收、快速反向；关闭后无遗留浮层。 |
| 键盘 | ArrowDown 开文件夹，方向键/Home/End 转焦并滚动，Enter 打开确切作品，Escape/收起回到来源。重挂载纸卡后保留焦点，刷新使用稳定控件 ID。 |
| 拖动冲突 | 实际从文件夹向另一列拖动后，事项仍在原列，`draggable` 恢复为 true，无残留 dragging 状态。Alt+左/右实际将合成事项移到先做再恢复随后，原拖动代码保持。 |
| 响应式 | 实测 1440×900 与 390×844 CSS 视口；手机作品横滑，完整标题可读，页面无横向溢出。修复浏览器聚焦时外层 body 滚动导致工具栏被裁切的问题，仅工作台内部滚动。 |
| 减弱动态 | 通过系统无障碍开关实际测试，`prefers-reduced-motion` 为 true：资料无飞行层，标题获得焦点；作品立即就位，3 张实际卡、0 张飞行卡。测试后恢复原 off 设置。 |

验收使用本轮独立 SQLite 和明确标注的合成作品。没有对用户原有作品、18510/18512 服务或其数据库做破坏性测试。原后端、API、数据结构、现有配色与组件 CSS 没有修改；`ui.js` 增加局部入口及导航同步。资料阅读仍是实际后端业务动作；忙碌时沿用既有错误提示，不伪造已读成功。

边界：实际 UI 为 Chromium/IAB，未测试 Safari、Firefox、真实触屏或读屏软件，也未在系统暗色下重复完整视觉流程。原生工具未提供视频录制，交付的是截图帧序列/GIF；不将单张截图或仅使用同一曲线视为完整动态一致性证明。

## 实现与运行

- `src/app/document-motion.js/.css`：共享矩形动画、反向、滚动回位、焦点、实际 DOM 与背景克隆隔离。文档内容反向缩放避免变形；动画刷新时重新核对终点。
- `src/app/work-folder.js/.css`：真实作品投影、封面、非模态横向纸卡、飞出/回收、键盘、拖动保护、重绘同步。没有引入 React 重写或新生产依赖。
- `src/app/ui.js`：原 `docGrid/docBody/taskCard`、路由和后渲染接入；保留已有阅读、引用、版本比较及原作品工作台。

前端开发：`ROLECRAFT_API_TARGET=http://127.0.0.1:18532 npm run dev -- --port 18530`。

API 与 worker 均须指向本工作区源码及同一独立数据库，例如在仓库根分别运行：

```sh
PYTHONPATH="$PWD/src" /private/tmp/rolecraft-web-python/bin/python -m career_lab.cli serve --host 127.0.0.1 --port 18532 --database-url sqlite:////private/tmp/rolecraft-motion-024-validation.db --provider local
PYTHONPATH="$PWD/src" /private/tmp/rolecraft-web-python/bin/python -m career_lab.cli worker --database-url sqlite:////private/tmp/rolecraft-motion-024-validation.db --provider local
```

本机实际 checkout、机器和数据库登记以所属 ISY5002 项目的资料导航为准；临时工作区与服务不会自动跨设备同步。
