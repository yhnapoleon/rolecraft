"""Render the frozen experiment results without changing models or selection."""
import csv
import json
from pathlib import Path


def main():
    root=Path('runs/controlled-v2')
    dev=json.loads((root/'development.json').read_text(encoding='utf-8'))
    test=json.loads((root/'confirmatory.json').read_text(encoding='utf-8'))
    records=[]
    for name in dev['e1']:
        d,t=dev['e1'][name],test['e1'][name]
        records.append(dict(candidate=name,dev_macro_f1=d['metrics']['macro_f1'],test_macro_f1=t['metrics']['macro_f1'],
            test_accuracy=t['metrics']['accuracy'],test_false_deduction=t['metrics']['false_deduction'],test_false_pass=t['metrics']['false_pass'],
            test_joint=t['metrics']['joint_correctness'],test_evidence_f1=t['mean_evidence_f1'],coverage=t['answer_coverage'],p95_seconds=t['metrics']['p95_seconds']))
    with Path('docs/reports/controlled-v2-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=records[0]);writer.writeheader();writer.writerows(records)
    lines=['# 场景数据与课程三项实验结果 v2','','执行日期：2026-10-03。已完成四项中的可自动执行工程与受控实验；人工双标尚未完成。',
        '', '## 四项交付', '',
        '| 项目 | 已完成 | 尚待完成 |','|---|---|---|',
        '| 1 场景矩阵/规范 | 6能力族、24逻辑结构、分区、G0/G1/G2规范 | 独立真实业务场景有效性审查 |',
        '| 2 首批100项 | 多证据样本、验证器、两份盲标CSV、导入与分歧统计 | 真人标注与裁决；当前paired=0 |',
        '| 3 正式数据/实验 | 1152项G0，576/288/288，监督学习/ML-DL/Ensemble，E1/E5/E6 | G1语义数据与多训练seed复核 |',
        '| 4 冻结/test/集成 | dev选型、hash冻结、正式test、真实HTTP辅助接口 | 自动评分部署门槛未达，维持人工复核 |',
        '', '## E1：固定单seed的受控数据结果', '',
        '| 候选 | dev Macro-F1 | test Macro-F1 | test准确率 | 误扣分率 | 错误放行率 | joint | 覆盖率 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        lines.append(f"| {r['candidate']} | {r['dev_macro_f1']:.4f} | {r['test_macro_f1']:.4f} | {r['test_accuracy']:.4f} | {r['test_false_deduction']:.4f} | {r['test_false_pass']:.4f} | {r['test_joint']:.4f} | {r['coverage']:.4f} |")
    lines+=['','融合alpha=0，结果与线性模型一致，没有增益。MLP训练最终loss约0.0265，但dev/test明显较弱，提示过拟合。一次seed不支持稳定性结论。',
        '', 'rules仅覆盖容量/资源两族，其余明确弃权并计入端到端失败分母；低误扣分不代表全面可用。规则与程序gold验证器同源，其成绩只说明受控规则适用性。hybrid在已覆盖结构用规则，其余用融合分类器。',
        '', '学习模型引用全部候选，额外引用导致joint correctness为0；这真实暴露证据选择尚未学会的问题。不能只报告标签F1而隐藏证据质量。',
        '', '## E5：检索影响','','| 候选 | oracle test F1 | retrieved test F1 |','|---|---:|---:|']
    for name in ('ensemble','hybrid'):
        lines.append(f"| {name} | {test['e1'][name]['metrics']['macro_f1']:.4f} | {test['e5'][name]['metrics']['macro_f1']:.4f} |")
    lines+=['','检索最多返回4条，候选包为8条；结构化条件所需字段可能被漏检。该结果评价端到端损失，不把检索缺失改写成新的gold。',
        '', '## E6：稳健性','','| 候选 | 表达/排序一致率 | 两种表达均判对 | 相反事实对均判对 | 纯排序不变率 |','|---|---:|---:|---:|---:|']
    for name,e in test['e6'].items():
        lines.append(f"| {name} | {e['style_and_order_agreement']:.4f} | {e['style_pair_joint_accuracy']:.4f} | {e['opposite_fact_pair_joint_accuracy']:.4f} | {e['pure_order_invariance']:.4f} |")
    lines+=['','表达对同时改变干扰文本和顺序；事实对可能改变多个字段。词袋模型天然排序不变，不能用该项高分宣称普遍稳健。',
        '', '## 冻结与产品接入', '',f"冻结ID：`{test['freeze_id']}`。候选仅按dev选为`{test['selected']}`；未按test更换候选。",'',
        '预先冻结的数值门槛为Macro-F1≥0.8、误扣分率≤0.1、joint≥0.6，且必须完成人工语义验证。当前数值和人工门槛均未通过，不部署正式自动评分。',
        '', 'POST /sessions/{id}/relation-checks已接入当前8502服务；真实HTTP返回200，使用learner历史可见材料，固定freeze/model/input hash。mode=shadow、review_required=true、affects_score=false，重复取回一致且不修改会话状态。源材料不包含技术私有备忘或未来版本。',
        '', '## 证据与后续', '',
        '- 81 tests通过（含PostgreSQL），见controlled-v2-final-tests.xml；独立审查与回归见controlled-v2-review.md。',
        '- 逐类precision/recall/F1、混淆矩阵、按模板置信区间、paired差值、p95和训练成本见controlled-v2-dev.json及controlled-v2-test.json。',
        '- 实际HTTP验证见controlled-v2-live-shadow.json。复现命令与标注步骤见../data/experiments-v2-runbook.md。',
        '- 两位真实成员应先独立完成data/annotation/v2-pilot中的前30项，再裁决标准并补全100项。当前没有人类标注结果。',
        '- 下一轮优先改进语义数据和证据选择；已看过的test不能继续充当新的未见选型集。需要新版本和新的未见模板来支持进一步确认性结论。',
        '- 无Git提交；用不可变数据目录、模型hash、冻结清单和本地报告保留版本。前端和SFT/GRPO仍按范围排除。','']
    Path('docs/reports/controlled-v2-results.md').write_text('\n'.join(lines),encoding='utf-8')
    print('docs/reports/controlled-v2-results.md')


if __name__=='__main__':main()
