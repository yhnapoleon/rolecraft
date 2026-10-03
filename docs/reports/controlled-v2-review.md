# 独立审查与修复记录

2026-10-03；审查在正式freeze/test之前完成。独立只读reviewer，未代写实现或修改数据。无Critical。

1. Important：freeze未核对dev来源。现保存数据/模型/源码/实际run身份并在freeze核验，registry逐文件验证。不同manifest或模型不允许套用原dev分数。
2. Important：逐项结果未被绑定。现冻结使用到的dev manifest、predictions、trials、metrics、report及E6数据，修改字节即拒绝。
3. Important：G0 proof未核验claim/缺失条件。现核对允许的claim渲染、输入hash、模板/分区/根身份、gold ID、最小证据与missing_requirement。反转结论后不能保留原标签。
4. 原Minor重评为Important：CSV展示材料可被改写但沿用旧hash，会污染人工真值。现导入时核对claim和candidate_evidence原文。
5. 自查修复：规则弃权不可计为正确INSUFFICIENT；新增abstained字段，grader与端到端指标计失败并单列coverage，混淆矩阵显式NO_PREDICTION。grader升为independent-v2、规则升为restricted-rules-v2.1，重新运行dev。

上述回归均先观察失败再修复，最终81 tests通过（含PostgreSQL）；报告controlled-v2-final-tests.xml。没有保留未修复的小项。

Ruling: reviewer不评价人工一致性或真实业务可靠性——当前没有人类标注或用户研究，因此继续pending，不能自动部署评分；代价是本轮仅能给出受控合成结论。
Ruling: 24模板是作者定义的逻辑结构，不声称24个独立真实场景——规范明确要求后续人工审查语义近重复；代价是泛化范围有限。

工作区无Git，本轮保留文件与报告hash，没有声称建立提交或远程发布。
