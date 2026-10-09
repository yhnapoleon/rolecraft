# Task 1 实施记录

日期：2026-10-02（Asia/Shanghai）

依据：`docs/plans/career-training-implementation-plan.md` Task 1；技术设计第3、5、11节；原有 `judge-case-bundle.json`。用户本轮已要求按计划开始实施，排除前端。

## 决策与范围

- 首轮落实一个可验证模块：场景与协议。后续模块依赖接口但本轮不预先建立空目录或空服务。
- 公共字段统一使用实施计划命名；评价样例中的 `criterion_id` 接受为 `criterion` 的输入别名。
- Python要求>=3.11，使用本机已有3.12.13实施并锁依赖。训练环境仍由后续GPU冒烟测试决定。
- 延期路径的实时同步5人日加人工fallback 1人日共6人日，资源批准事件将总预算设置为6并延期至第10天；人数扩容是另一独立事件。
- 场景包加载全部事实与未来版本，属于world-private。可见性声明的静态校验已实现，运行时权限与as-of投影属于Task 2。
- 类型层阻止gold字段混入EvidencePackage及候选证据。文本中的语义泄漏、prompt白名单与input_hash计算留到Task 5，不能把当前测试宣称为完整泄漏防御。
- `check_solution` 仅用于作者假设路径验证；不对外作为审批、实时规则引擎或评分接口。
- 已存在课程资料但没有Git仓库。本轮保存文件与内容hash，未初始化仓库、创建worktree或提交；不将原始课程资料自动纳入版本库。

## 执行证据

1. 先写计划指定的两个测试文件，首次运行因缺少 `career_lab` 模块出现2个导入错误，符合“缺失loader/定义”时失败的验收步骤。
2. 实现后首次运行14项通过、6项在创建临时目录时失败，根因是系统共享 `pytest-of-13736` 无读取权限。改用项目内 `.pytest_cache/tmp`，保留正常tmp_path测试逻辑。
3. `uv run pytest -q`：20 passed。覆盖两条合理路径、全拒绝反例、容量29/30/31边界、资源审批、动态政策风险、缺失依赖、gold隔离、CLI及材料版本验证。
4. `uv run python -m career_lab.cli scenario validate scenarios/pm_pilot/v1/scenario.yaml`：退出码0，valid=true；3角色、8材料版本、12原子项。
5. 场景hash：`9959ecb5e89576ee63049f17d6b65322be74088c7a389ce6a1c651bfebb8e4fe`。

## 审查与最终验证

- 增加两项一致性回归：事实账本中的数字必须与初始约束一致；最小人数不能大于初始容量。两项先失败再修复，全量22项通过。
- 独立只读审查确认1项P2：同一事件可激活同一材料的两个版本。新增回归测试复现失败，再增加按material_id去重校验；修复后全量通过。
- 审查的非阻塞边界：仅包含政策且全部转人工的方案可能通过局部可行性检查，但不代表有助手价值或rubric达标。保留由Task 6按业务目标与交付评价，此处不将局部可行性升级为任务成功结论。
- 最终命令 `uv run pytest -q --junitxml=docs/reports/task-01-tests.xml`：**23 passed in 1.79s**，退出码0；机器可读记录见 [task-01-tests.xml](https://github.com/yhnapoleon/rolecraft/blob/2c07160b5e829ac08afb8a31667440bbda72df73/docs/reports/task-01-tests.xml)。
- 最终场景CLI校验退出码0，hash、角色、材料与rubric数量保持一致。
- `uv build --quiet` 成功生成Python wheel与sdist。此构建验证Python包，不是课程完整发布包；运行示例仍需工作区中的独立场景目录。
- 代码验证完成，Git归档未做，后续直接消费者为Task 2状态引擎与事件存储。

上述“可行”仅指场景作者约束验证，不代表已完成真实用户试用或模型效果评价。
