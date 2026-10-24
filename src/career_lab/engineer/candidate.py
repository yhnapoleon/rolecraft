"""Candidate settings an engineer may change: supported configuration fields only.

A candidate is a difference applied to the ticket's baseline configuration. It passes the
same strict configuration validation as a CLI submission; nothing is executed or fetched.
"""

import json
from typing import Any, get_args

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.policy import validate_config

# Assistant behavior only. Identity, versions, the pilot plan (participants, launch_day),
# the score calibration reference and the model generator are not engineering settings.
EDITABLE_FIELDS = (
    "domains",
    "scope_filter",
    "update_strategy",
    "fallback",
    "freshness_guard",
    "work_items",
    "manual_domains",
    "prohibited_topics",
    "retrieval_limit",
    "chunk_size",
    "min_score",
)
# Topics are short phrases; the bound also keeps every engineer view within an Agent's tool
# result (see session.py).
MAX_TOPICS = 10
MAX_TOPIC_LENGTH = 40


def supported_settings(config: C.AssistantConfig) -> dict[str, Any]:
    value = config.model_dump(mode="json")
    return {name: value[name] for name in EDITABLE_FIELDS}


def choices(name: str) -> list[str]:
    return list(get_args(C.AssistantConfig.model_fields[name].annotation))


def editable_fields(package: Any) -> list[dict[str, Any]]:
    domains = sorted(package.bundle.domains)
    costs = dict(package.rules["work_costs"])
    return [
        {"field": "domains", "type": "set", "choices": domains},
        {"field": "scope_filter", "type": "boolean"},
        {"field": "update_strategy", "type": "choice", "choices": choices("update_strategy")},
        {"field": "fallback", "type": "choice", "choices": choices("fallback")},
        {"field": "freshness_guard", "type": "choice", "choices": choices("freshness_guard")},
        {"field": "work_items", "type": "set", "choices": list(costs), "costs": costs},
        {"field": "manual_domains", "type": "set", "choices": domains},
        {
            "field": "prohibited_topics",
            "type": "text_list",
            "max_items": MAX_TOPICS,
            "max_length": MAX_TOPIC_LENGTH,
        },
        {"field": "retrieval_limit", "type": "integer", "minimum": 1, "maximum": 20},
        {"field": "chunk_size", "type": "integer", "minimum": 1, "maximum": 4000},
        {"field": "min_score", "type": "number", "minimum": 0},
    ]


def plain_topic(text: str) -> bool:
    """A topic is a short phrase matched as text; never a URL, path or command line."""
    stripped = text.strip()
    return (
        0 < len(stripped) <= MAX_TOPIC_LENGTH
        and stripped.isprintable()
        and "://" not in stripped
        and "\\" not in stripped
        and not stripped.startswith(("/", "~", "./", "../", "$", "`"))
    )


def candidate_config(
    package: Any, baseline: C.AssistantConfig, changes: dict[str, Any], session_id: str
) -> C.AssistantConfig:
    if not isinstance(changes, dict) or set(changes) - set(EDITABLE_FIELDS):
        raise C.ProtocolError("engineer_setting_not_editable")
    try:
        candidate = C.AssistantConfig.model_validate_json(
            json.dumps({**baseline.model_dump(mode="json"), **changes}, allow_nan=False),
            strict=True,
        )
    except (ValidationError, ValueError):
        raise C.ProtocolError("engineer_setting_value_invalid") from None
    topics = candidate.prohibited_topics
    if len(topics) > MAX_TOPICS or not all(plain_topic(topic) for topic in topics):
        raise C.ProtocolError("engineer_setting_value_invalid")
    validate_config(package, candidate, session_id)
    return candidate


def settings_diff(before: C.AssistantConfig, after: C.AssistantConfig) -> dict[str, Any]:
    old, new = supported_settings(before), supported_settings(after)
    return {
        name: {"before": old[name], "after": new[name]}
        for name in EDITABLE_FIELDS
        if old[name] != new[name]
    }
