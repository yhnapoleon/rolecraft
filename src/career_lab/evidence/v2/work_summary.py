"""Describe observed work, never infer reasoning quality or unseen effort."""


def work_summary(totals, verified_sources, records, language):
    zh = language == "zh"
    activities = []
    for key, cn, en in [
        ("material_read", "读过材料", "read materials"),
        ("test_run", "实际运行测试", "run tests"),
        ("question_sent", "向同事提问", "asked colleagues"),
    ]:
        if totals[key]["verified_records"] > 0:
            activities.append(cn if zh else en)
    if activities:
        opening = (
            ("记录显示，你已经" + "、".join(activities) + "。")
            if zh
            else ("The records show that you have " + ", ".join(activities) + ".")
        )
        if any(r["executor"]["kind"] == "external_agent" for r in records):
            opening += (
                "其中包含Agent代办，执行归属保留。"
                if zh
                else " Some actions were performed by an Agent; their attribution is retained."
            )
    elif all(
        totals[k]["status"] == "complete" for k in ("material_read", "test_run", "question_sent")
    ):
        opening = (
            "这段完整记录中尚未看到读取材料、运行测试或向同事提问；当前作品和决定仍保留。"
            if zh
            else "This complete record contains no material reads, test runs, or questions to colleagues; your work and decision are retained."
        )
    else:
        opening = (
            "当前可查记录尚未展示调查、测试或求助过程，记录不完整，不能据此认定你没有做过。"
            if zh
            else "The available records do not yet show investigation, testing, or requests for help. They are incomplete and do not establish that these activities never occurred."
        )
    evidence = (
        (
            "作品已关联可回查的原始依据。"
            if zh
            else "The work links to original evidence that can be inspected."
        )
        if verified_sources
        else (
            "作品暂未关联已核对的原始依据，可以补上具体来源。"
            if zh
            else "The work does not yet link to verified original evidence; you can add specific sources."
        )
    )
    boundary = (
        "这些记录说明做过什么、引用来自哪里；停止或暂缓是否理由充分，需要另外核验理由与证据的关系。"
        if zh
        else "These records establish observed actions and source provenance. Whether a stop or deferral is well reasoned requires a separate check of the reasoning and its supporting evidence."
    )
    return [opening, evidence, boundary]
