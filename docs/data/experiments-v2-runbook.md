# 场景数据与三项课程实验 v2

## 覆盖与边界

本轮实现监督学习、ML/DL、Hybrid/Ensemble三项技术在同一relation任务上的实际训练、评价与辅助API接入。没有进行SFT/GRPO，也没有前端。程序可验证G0数据不等于人工语义gold或学习效果证据。

场景矩阵：scenario-matrix-v2.md；标注规范：annotation-guide-v2.md。6能力族、24个明确逻辑结构；每族2个train/1个dev/1个test。每结构8个事实根，每根支持/矛盾/缺失×2种表达，共1152项（576/288/288）。8条候选材料、多个最小充分集合、中性随机ID与排序。不同表达不是独立样本；事实反转对可能改变多个字段，不声称单因素因果实验。

输入明确给出逻辑条件，是受控推理任务。有限规则仅覆盖容量/资源，其解析器与G0验证器同源，属于已知规则适用性对照，成绩不能当作独立规则推理发现。其余能力使用学习模型；规则弃权单独计coverage，不能把弃权当作材料INSUFFICIENT。

## 复现顺序

使用项目根目录、Python3.12及uv.lock。数据/模型输出已存在时不要覆盖，另建版本或直接读取现有产物。脚本prepare_experiments当前使用固定v2目录，一次构建后重复执行会明确拒绝。

```powershell
uv sync --locked --python 3.12
uv run python scripts/prepare_experiments.py pilot
uv run python scripts/prepare_experiments.py annotations
uv run python scripts/prepare_experiments.py release
uv run career-lab train-baselines --manifest data/releases/controlled-v2/manifest.json --output runs/models/controlled-v2
uv run python scripts/run_controlled_experiments.py dev
# 在dev上选择并冻结所有配置/代码/模型/数据manifest之后，才执行test：
uv run python scripts/run_controlled_experiments.py freeze
uv run python scripts/run_controlled_experiments.py test
```

freeze不可覆盖；已完成test重跑返回验证过的原报告，不借此重新选型。冻结后代码或模型漂移会拒绝执行。继续开发应开新实验版本，已看过的测试结果不得再称未见数据。

输出runs/controlled-v2包含development、freeze、confirmatory、registry和每个run的manifest/predictions/errors/metrics/report；docs/reports保存可分发的汇总。学习模型概率顺序固定。融合alpha只由dev选择；所有模型仍使用固定单训练seed5002，未声称多seed稳定性。

E1比较常量、线性、MLP、融合、有限规则和混合；E5比较oracle/retrieved（top4）；E6输出表达与排序联合扰动、纯证据顺序反转、相反事实对同时判对率。反转排序对词袋模型天然不改变特征，这个结果不能证明广义稳健性。

MLP使用LBFGS，记录真实fit秒数、最终loss和迭代数，不伪造不存在的逐epoch曲线。另报每类precision/recall/F1、混淆矩阵、误扣分/错误放行、证据F1、joint correctness、coverage、p95、按模板bootstrap及paired差值。只有6个评测模板，置信区间仅描述本样本。

## 人工标注待办

文件data/annotation/v2-pilot/annotator-a.csv和annotator-b.csv为100项盲标表，含train/dev、不含封存test。先独立完成前30条；填表方式见annotation-guide-v2.md。运行annotations命令导入并输出分歧，不自动发布G1。当前表为空，paired=0、kappa=null。

人工标注是尚未完成的外部工作。程序生成两个标注者身份或调用两个模型投票，不能替代真实双标。工作表已加入忽略规则，不随源代码发布包分发。

## 产品辅助接口

```powershell
$env:CAREER_LAB_STUDY='runs/controlled-v2'
uv run career-lab serve --port 8502 --provider deepseek
```

使用会话Bearer token调用POST /sessions/{id}/relation-checks，正文为claim、request_id及可选as_of_seq。服务端从该历史时点的learner可见材料和配置组装证据，不接受客户端gold；返回冻结ID、模型版本、输入hash、来源、mode=shadow、review_required=true、affects_score=false。重复请求读取原结果，不修改状态与rubric评分。未配置study返回503。

即使合成test数值达到门槛，人工验证门槛仍未满足；当前不启用正式自动评分。自由文本产品材料与受控训练语法存在分布差异，返回结果是供人工检查的实验建议，不是可靠职业评价。
