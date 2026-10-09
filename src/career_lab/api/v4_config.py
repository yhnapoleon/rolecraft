"""Apply v4 settings against an exact server configuration, without client versions."""

from career_lab.api.modules import Operation
from career_lab.contracts.v2 import V2, ObjectRef, AssistantConfig, ProtocolError


class SettingsInput(V2):
    base: ObjectRef
    settings: dict


def install_settings(registry, module):
    def apply(view, command, auth):
        body = SettingsInput.model_validate(command.payload)
        config = module.snapshot(view).config
        current = ObjectRef(
            session_id=auth.session_id,
            kind="config",
            object_id=config.id,
            version=config.version,
            config_version=config.config_version,
        )
        if body.base != current:
            raise ProtocolError("object_version_conflict", status=409)
        allowed = {
            "participants",
            "domains",
            "launch_day",
            "update_strategy",
            "fallback",
            "work_items",
            "scope_filter",
            "freshness_guard",
            "manual_domains",
            "prohibited_topics",
            "min_score",
            "retrieval_limit",
            "chunk_size",
            "generator",
        }
        if not body.settings or set(body.settings) - allowed:
            raise ProtocolError("invalid_settings", status=422)
        changed = AssistantConfig.model_validate(
            config.model_dump(mode="json")
            | body.settings
            | {"version": config.version + 1, "config_version": config.config_version + 1}
        )
        internal = command.model_copy(
            update={
                "operation": "apply_config",
                "payload": {"tool": "apply_config", "config": changed.model_dump(mode="json")},
            }
        )
        return module.action(view, internal, auth)

    registry.register(
        Operation(
            "configuration.apply", "act", SettingsInput, apply, event_projector=module.project_event
        )
    )
