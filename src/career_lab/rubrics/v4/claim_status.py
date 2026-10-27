"""Shared temporal distinction for our reviewer and its support check."""


def claim_status_guide(language):
    if language == "en":
        return (
            " Distinguish existing records, proposed collection and claimed completion. "
            "A proposal to collect actual handling time later does not claim that SD-120 "
            "already contains it, nor that it has already been collected. A missing field "
            "alone cannot refute that proposal. Check the proposed method and its unresolved "
            "ownership separately. Claims that a field exists or collection is complete "
            "still require evidence; never treat a proposal as a verified result."
        )
    return (
        " 区分现有记录、拟议采集与声称已完成。提出另行采集实际工时，"
        "不代表声称 SD-120 已有该字段，也不代表声称已经采集。"
        "仅凭现有资料缺少字段，不能否定未来采集的提议；应另行核对提议的方法及责任归属未知。"
        "声称现有字段或已经完成采集仍须有依据，不能把提议当成已验证结果。"
    )
