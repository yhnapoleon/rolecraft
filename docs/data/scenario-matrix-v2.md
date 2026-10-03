# 场景覆盖矩阵 v2

24个结构模板；每族2个train、1个dev、1个test。仅改数值/表达不增加模板数量。

| 能力族 | 模板 | 分区 | 因果结构 |
|---|---|---|---|
| capacity | capacity_limit | train | 生效容量边界：(参与人数不大于生效容量) |
| capacity | capacity_dual_limit | train | 业务容量与安全限额同时约束：(参与人数不大于较小值(生效容量、安全限额)) |
| capacity | capacity_occupied | dev | 已有用户占用剩余席位：((参与人数加已占用席位)不大于生效容量) |
| capacity | capacity_group_quota | test | 分组配额与总峰值双重约束：((参与人数不大于甲组配额)且(峰值人数不大于(甲组配额加乙组配额))) |
| resources | resources_sum | train | 开发与测试成本相加：((开发工作量加测试工作量)不大于可用人日) |
| resources | resources_dependency | train | 成本与依赖均需满足：((开发工作量不大于可用人日)且(依赖就绪标记等于1)) |
| resources | resources_parallel | dev | 并行任务关键路径加准备成本：((较大值(并行甲工作量、并行乙工作量)加准备工作量)不大于可用人日) |
| resources | resources_grant | test | 追加资源抵消剩余预算不足：((开发工作量加人工兜底工作量)不大于(剩余人日加追加人日)) |
| time | time_deadline | train | 交付不得超过截止日：(计划上线日不大于有效截止日) |
| time | time_index | train | 当前源版本与索引版本一致：(索引版本等于源文档版本) |
| time | time_delay | dev | 更新后等待索引延迟：((政策更新日加索引延迟天数)不大于观测日) |
| time | time_valid_window | test | 批准在上线时已生效且未失效：((批准生效日不大于计划上线日)且(计划上线日不大于批准失效日)) |
| testing | testing_coverage | train | 实际测试数覆盖最低要求：(要求测试数不大于已执行测试数) |
| testing | testing_config | train | 测试覆盖同一提交配置：((1不大于已执行测试数)且(被测配置版本等于提交配置版本)) |
| testing | testing_risk | dev | 功能失败率阈值与风险用例：((失败用例数不大于允许失败数)且(风险用例执行标记等于1)) |
| testing | testing_categories | test | 两个类别独立达到覆盖要求：((甲类所需用例数不大于甲类已测数)且(乙类所需用例数不大于乙类已测数)) |
| scope | scope_allow | train | 在开放知识范围内：(范围内标记等于1) |
| scope | scope_deny | train | 开放范围不能覆盖禁止项：((范围内标记等于1)且(禁止自动回答标记等于0)) |
| scope | scope_dynamic | dev | 动态内容需要实时同步：((范围内标记等于1)且((动态知识标记等于0)或(实时同步标记等于1))) |
| scope | scope_privacy | test | 公开材料或有授权的私有材料：((范围内标记等于1)且((私有材料标记等于0)或(授权标记等于1))) |
| alternatives | alternatives_manual | train | 禁止自动回答时接受人工转接：((禁止自动回答标记等于0)或(人工转接标记等于1)) |
| alternatives | alternatives_postpone | train | 按期交付或有效延期路径：((计划上线日不大于有效截止日)或(延期获批标记等于1)) |
| alternatives | alternatives_narrow | dev | 原方案合规或缩小人数后的路径：((参与人数不大于生效容量)或((缩小范围标记等于1)且(小范围人数不大于生效容量))) |
| alternatives | alternatives_synchronise | test | 稳定知识或实时同步加足够资源：((动态知识标记等于0)或((实时同步标记等于1)且((开发工作量加人工兜底工作量)不大于可用人日))) |
