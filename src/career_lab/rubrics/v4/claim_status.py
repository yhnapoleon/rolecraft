"""Shared temporal distinction for our reviewer and its support check."""


def claim_status_guide(language):
    if language == "en":
        return (
            " Distinguish information already in existing records, proposals for future "
            "collection, and claims that collection is complete. A field missing from "
            "existing records alone cannot refute a proposal to collect it later. "
            "Check the proposed method and responsibility for collection separately. "
            "Claims that a field already exists or collection is complete still require "
            "evidence; never treat a proposal as a verified result."
        )
    return (
        " 区分现有记录中已有的信息、提议以后采集的信息，以及声称已经完成采集的情况。"
        "仅凭现有资料缺少某个字段，不能否定以后采集该字段的提议。"
        "提议的方法及采集责任归属应另行核对。"
        "声称字段已经存在或采集已经完成，仍须有依据；不能把提议当成已验证结果。"
    )
