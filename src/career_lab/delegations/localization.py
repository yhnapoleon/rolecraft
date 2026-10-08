"""Presentation only. Callers must supply the server-bound work language.

No language inference, evidence translation, authority, locale persistence or
public DTO extension lives here. Wiring waits for the common language contract.
"""

DESCRIPTIONS = {
    "zh": {
        "read": "读取当前获准的工作区数据。",
        "act": "执行明确委托的工作动作。",
        "submit": "执行单独授权的正式提交动作。",
    },
    "en": {
        "read": "Read currently authorized workspace data.",
        "act": "Perform explicitly delegated work actions.",
        "submit": "Perform a separately authorized formal submission.",
    },
}


def tool_description(work_language, capability):
    if work_language not in DESCRIPTIONS or capability not in DESCRIPTIONS[work_language]:
        raise ValueError("bound work language and known capability required")
    return DESCRIPTIONS[work_language][capability]


def source_text(fragment):
    """Preserve the authorized source verbatim; a translated gloss is not evidence."""
    return fragment.text
