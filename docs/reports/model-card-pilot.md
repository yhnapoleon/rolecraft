# CPU relation baseline pilot 模型卡

用途：验证关系分类的训练、概率融合和独立评价链路。禁止直接替换criterion产品评价器；当前注册记录全部为relation_eval_only、deployment_eligible=false。

输入：claim与candidate_evidence文本拼接，不读取gold、引用来源映射或私有场景字段。输出标签顺序固定SUPPORTED、CONTRADICTED、INSUFFICIENT；引用采用全部候选的朴素基线，没有学习证据选择。候选很多时可能出现无关引用，不能据准确率宣称引用质量可靠。

线性模型为char 1–3gram TF-IDF（最多4000特征）+ balanced LogisticRegression。编码器为binary char 1–2gram（最多2000特征）+ MLP(32,16)、tanh、lbfgs。两者随机种子5002，max_iter=500；MLP不使用预训练权重。融合为alpha×encoder+(1-alpha)×linear；在dev网格{0,.25,.5,.75,1}选Macro-F1。

数据：中文合成G0 pilot train45项、dev30项，按因果模板隔离；test15项未参与训练或选型。vectorizer只拟合train；训练过程不读取test gold。英语ContractNLI pilot作为独立导入验证，未混入此次模型训练。

结果：线性Macro-F1=0.7660818713；MLP=0.6666666667；融合=0.7660818713，alpha=0。线性开发集false deduction=0.4、false pass=0.3；MLP对应两者为0，但整体准确率更低，不能用单项指标宣称可靠。开发集只有两个模板，置信区间与切片只用于pilot诊断。没有独立test结论、没有SFT/RL比较、没有学习效果结论。

完整指标见task-09-e1-dev.json。本地权重及SHA-256、训练输入ID、数据hash、alpha搜索记录位于runs/models/pilot-v1；源代码包通过README命令重建，不分发joblib二进制。仅加载本地可信joblib产物。
