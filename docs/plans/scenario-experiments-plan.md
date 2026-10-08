# 场景数据与课程实验实施计划

2026-10-03，用户授权按四项顺序执行。继承前端与SFT/GRPO排除范围。

1. 场景覆盖矩阵与标注规范：6能力族×4种因果结构，固定模板分区；声明G0/G1/G2，定义充分证据与缺失条件。
2. 首批100项及人工工作包：受控事实→材料→正反/缺失/改写；自动核验；两份盲标表、导入和分歧统计。没有人类结果时如实标记pending。
3. 正式受控合成v2：24模板×8事实根×6派生=1152项；线性、MLP、融合、规则与混合的E1/E5/E6；先dev，固定选择与文件hash。
4. 冻结后一次test：报告逐类指标、证据、误扣分、覆盖率与成本；未过质量门槛或缺少人工核验，不替换正式criterion评分，接入可追溯的relation影子检查API。

验收：每项有实际命令和报告；旧v1不覆盖；test不用于训练、调权重、选阈值；relation不能变成criterion总分；人工工作不伪造完成。

Ruling: 当前目录没有Git仓库，沿用用户指定目录和追加进度记录，不建立独立worktree或虚构提交。代价：历史靠原版本文件与hash追踪。
Ruling: 人工双标不阻止G0工程与受控实验；任何G1/真人质量结论保持待完成。代价：本轮结果只证明合成分布上的表现，不能升级为产品可靠性结论。
Pre-flight: Task1模板/事实协议供Task2生成器使用；Task2输出既有EvidencePackage/GoldAnnotation/lineage供Task3；Task3冻结模型/数据hash供Task4。新生成器不更改旧v1数据。影子API用服务端可见材料，绝不接收gold。

## 进度

- Task 1：完成。矩阵与规范已写入docs/data；test_scenario_catalog.py 2 passed，包含三值逻辑与边界测试。
- Task 2：工程部分完成，人工双标待完成。100项盲标工作包及校验/导入已生成；全量71 passed/1 skipped。
- Task 3：完成受控实验与最终回归（81 tests通过）。1152项/24模板，576/288/288；CPU三模型+有限规则+混合，E1/E5/E6与逐类指标已输出[controlled-v2-dev.json](https://github.com/yhnapoleon/rolecraft/blob/2c07160b5e829ac08afb8a31667440bbda72df73/docs/reports/controlled-v2-dev.json)。融合alpha=0，无增益。
- Task 4：完成冻结、正式合成test和真实HTTP影子接入。混合test Macro-F1=0.6496、误扣分率0.3333，未过自动评分门槛；人工验证仍pending。

## Review focus

检查模板是否仅换数字而虚增、gold是否泄漏、充分集合与缺失条件是否正确、test是否参与选择、冻结是否包含所有决定性文件、影子API是否泄漏角色材料或覆盖正式评分。

Final review: 完成一次独立审查，3项Important与1项由Minor重评的问题均RED→GREEN修复；另修复弃权计分。81 tests通过，无未修复minor。详见../reports/controlled-v2-review.md。
