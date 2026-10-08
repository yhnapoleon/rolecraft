"""Versioned, finite logical micro-scenarios; these are not human semantic gold."""

from dataclasses import dataclass


def evaluate(expr, facts):
    if isinstance(expr, str):
        return facts.get(expr)
    if isinstance(expr, (int, bool)):
        return expr
    op, *args = expr
    values = [evaluate(a, facts) for a in args]
    if op == "and":
        return False if False in values else None if None in values else True
    if op == "or":
        return True if True in values else None if None in values else False
    if None in values:
        return None
    if op == "le":
        return values[0] <= values[1]
    if op == "eq":
        return values[0] == values[1]
    if op == "add":
        return sum(values)
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    raise ValueError("unknown expression operator")


def variables(expr):
    if isinstance(expr, str):
        return {expr}
    if isinstance(expr, (int, bool)):
        return set()
    return set().union(*(variables(a) for a in expr[1:]))


FIELDS = dict(
    participants="参与人数",
    capacity="生效容量",
    security_limit="安全限额",
    reserved="已占用席位",
    peak="峰值人数",
    quota_a="甲组配额",
    quota_b="乙组配额",
    approved="主管批准标记",
    effective_day="批准生效日",
    launch="计划上线日",
    dev="开发工作量",
    test="测试工作量",
    budget="可用人日",
    fallback="人工兜底工作量",
    parallel_a="并行甲工作量",
    parallel_b="并行乙工作量",
    setup="准备工作量",
    remaining="剩余人日",
    dependency="依赖就绪标记",
    deadline="有效截止日",
    index="索引版本",
    source="源文档版本",
    observed="观测日",
    updated="政策更新日",
    delay="索引延迟天数",
    expiry="批准失效日",
    tests="已执行测试数",
    required="要求测试数",
    tested_config="被测配置版本",
    config="提交配置版本",
    required_a="甲类所需用例数",
    required_b="乙类所需用例数",
    tested_a="甲类已测数",
    tested_b="乙类已测数",
    failures="失败用例数",
    tolerance="允许失败数",
    risk_test="风险用例执行标记",
    allowed="范围内标记",
    blocked="禁止自动回答标记",
    dynamic="动态知识标记",
    realtime="实时同步标记",
    consent="授权标记",
    private="私有材料标记",
    manual="人工转接标记",
    narrowed="缩小范围标记",
    extension="延期获批标记",
    small="小范围人数",
    grant="追加人日",
)


def expression_text(expr):
    if isinstance(expr, str):
        return FIELDS[expr]
    if isinstance(expr, int):
        return str(expr)
    op, *args = expr
    rendered = [expression_text(a) for a in args]
    if op in ("le", "eq", "add", "and", "or"):
        return (
            "("
            + {"le": "不大于", "eq": "等于", "add": "加", "and": "且", "or": "或"}[op].join(
                rendered
            )
            + ")"
        )
    return ("较小值" if op == "min" else "较大值") + "(" + "、".join(rendered) + ")"


@dataclass(frozen=True)
class Template:
    id: str
    family: str
    split: str
    description: str
    expression: tuple


# Two train structures, one dev structure, one held-out test structure per family.
_MATRIX = {
    "capacity": [
        ("limit", "生效容量边界", ("le", "participants", "capacity")),
        (
            "dual_limit",
            "业务容量与安全限额同时约束",
            ("le", "participants", ("min", "capacity", "security_limit")),
        ),
        (
            "occupied",
            "已有用户占用剩余席位",
            ("le", ("add", "participants", "reserved"), "capacity"),
        ),
        (
            "group_quota",
            "分组配额与总峰值双重约束",
            (
                "and",
                ("le", "participants", "quota_a"),
                ("le", "peak", ("add", "quota_a", "quota_b")),
            ),
        ),
    ],
    "resources": [
        ("sum", "开发与测试成本相加", ("le", ("add", "dev", "test"), "budget")),
        (
            "dependency",
            "成本与依赖均需满足",
            ("and", ("le", "dev", "budget"), ("eq", "dependency", 1)),
        ),
        (
            "parallel",
            "并行任务关键路径加准备成本",
            ("le", ("add", ("max", "parallel_a", "parallel_b"), "setup"), "budget"),
        ),
        (
            "grant",
            "追加资源抵消剩余预算不足",
            ("le", ("add", "dev", "fallback"), ("add", "remaining", "grant")),
        ),
    ],
    "time": [
        ("deadline", "交付不得超过截止日", ("le", "launch", "deadline")),
        ("index", "当前源版本与索引版本一致", ("eq", "index", "source")),
        ("delay", "更新后等待索引延迟", ("le", ("add", "updated", "delay"), "observed")),
        (
            "valid_window",
            "批准在上线时已生效且未失效",
            ("and", ("le", "effective_day", "launch"), ("le", "launch", "expiry")),
        ),
    ],
    "testing": [
        ("coverage", "实际测试数覆盖最低要求", ("le", "required", "tests")),
        (
            "config",
            "测试覆盖同一提交配置",
            ("and", ("le", 1, "tests"), ("eq", "tested_config", "config")),
        ),
        (
            "risk",
            "功能失败率阈值与风险用例",
            ("and", ("le", "failures", "tolerance"), ("eq", "risk_test", 1)),
        ),
        (
            "categories",
            "两个类别独立达到覆盖要求",
            ("and", ("le", "required_a", "tested_a"), ("le", "required_b", "tested_b")),
        ),
    ],
    "scope": [
        ("allow", "在开放知识范围内", ("eq", "allowed", 1)),
        ("deny", "开放范围不能覆盖禁止项", ("and", ("eq", "allowed", 1), ("eq", "blocked", 0))),
        (
            "dynamic",
            "动态内容需要实时同步",
            ("and", ("eq", "allowed", 1), ("or", ("eq", "dynamic", 0), ("eq", "realtime", 1))),
        ),
        (
            "privacy",
            "公开材料或有授权的私有材料",
            ("and", ("eq", "allowed", 1), ("or", ("eq", "private", 0), ("eq", "consent", 1))),
        ),
    ],
    "alternatives": [
        ("manual", "禁止自动回答时接受人工转接", ("or", ("eq", "blocked", 0), ("eq", "manual", 1))),
        (
            "postpone",
            "按期交付或有效延期路径",
            ("or", ("le", "launch", "deadline"), ("eq", "extension", 1)),
        ),
        (
            "narrow",
            "原方案合规或缩小人数后的路径",
            (
                "or",
                ("le", "participants", "capacity"),
                ("and", ("eq", "narrowed", 1), ("le", "small", "capacity")),
            ),
        ),
        (
            "synchronise",
            "稳定知识或实时同步加足够资源",
            (
                "or",
                ("eq", "dynamic", 0),
                ("and", ("eq", "realtime", 1), ("le", ("add", "dev", "fallback"), "budget")),
            ),
        ),
    ],
}
TEMPLATES = tuple(
    Template(f"{family}_{name}", family, ("train", "train", "dev", "test")[i], description, expr)
    for family, rows in _MATRIX.items()
    for i, (name, description, expr) in enumerate(rows)
)
