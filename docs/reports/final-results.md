# 本轮后端工程结果

实施截至2026-10-03。范围为实施计划中可本地执行的非前端、非后训练部分。各Task逐项记录见 implementation-progress.md；原计划的人工、训练和课程交付条目未被自动勾选。

## 已实现

场景协议与三套场景、状态事件和历史权限、事务与幂等、持久化 jobs/租约/重试、角色工具回合、检索及版本化测试、成果提交、固定快照证据组装、确定性规则和保守反馈、数据发布审计、独立 Eval、CPU监督基线及融合、候选注册、反馈证据链接、过程回放、演示和源代码打包。

角色对话已用用户本地密钥完成 DeepSeek 真实调用以及 HTTP→独立worker→结果取回。模型调用可能因失败重试产生重复费用，但状态提交保证幂等。OpenAI 适配器未实调。PostgreSQL已进行事务测试和容器实际重启恢复；不是只做内存假数据库测试。

## 验证与结果

- 最终本机全套 **67 tests通过**，含真实PostgreSQL；见 [task-14-tests.xml](https://github.com/yhnapoleon/rolecraft/blob/2c07160b5e829ac08afb8a31667440bbda72df73/docs/reports/task-14-tests.xml)。一条上游依赖弃用警告。
- 独立解压环境安装及8条复现命令均通过，66 tests通过、1项PostgreSQL测试因未配置而跳过；重建训练与E1 dev得到相同Macro-F1，见task-14-clean-install.json。
- 最新真实HTTP服务通过扩容/延期、当前政策检索、提交、独立worker反馈及重复回放；见task-14-live-final.json。服务仍监听本机8502。
- 主场景、紧急期限、15人容量变体均完成提交与重开数据库回放；见 task-14-demo-*.json。
- 审批API测试覆盖合法扩容/延期路径、无待处理申请拒绝、重复请求恢复与改写冲突；模型仍无批准工具。
- 90条中文合成pilot按因果模板拆分45/30/15。另导入85条真实公开ContractNLI train关系样本；来源与许可证见 task-07-public-source.json。
- E1开发集Macro-F1：线性0.7661、MLP0.6667、融合0.7661。融合alpha=0，没有增益，不能包装为性能提升；详见 task-09-e1-dev.json。
- relation模型候选全部 deployment_eligible=false；criterion产品反馈使用rules-v2和待核验语义项，没有冒充训练完成的完整Judge。

独立代码审查发现旧配置测试误计、日志缺失误判、待核验PARTIAL上界偏低、获批方案缺少API入口。均已修复并加入回归。额外修复过期末次job不终止、训练审计不应读取test gold，以及事件发生前不应扣政策更新测试分。规则修订固定为rules-v2，已有rules-v1反馈保留原版本。

## 仍需条件或人工完成

- 前端、SFT和GRPO按用户范围排除；没有下载底座或启动GPU任务。
- 正式数据800–1500条、双人标注、真实用户试用与学习效果对照待完成。
- 后训练候选比较、最终独立test和完整语义Judge质量验收待完成。当前pilot不能支持正式泛化或产品可靠性结论。
- 两次课程slides、10–15分钟录屏、个人贡献报告及peer review未制作；源码演示不等于这些课程交付。
- 未初始化Git、未创建提交、未部署公开服务。源代码发布包是本地交付物，敏感文件不随包分发。

启动和复现步骤见根目录README；压缩包的逐文件hash记录在release-manifest.json，干净解压环境的实测结果见task-14-clean-install.json。
