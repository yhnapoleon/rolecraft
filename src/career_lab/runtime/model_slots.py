"""Per-slot model configuration, read once at startup for the server and the worker.

Four slots: ROLES (the three colleagues), JUDGE (semantic Judge), SUPPORT (support
verification, falls back to JUDGE) and ASSISTANT (knowledge-assistant generation).
Each slot reads ``CAREER_LAB_<SLOT>_{PROVIDER,KEY_FILE,BASE_URL,MODEL,MAX_TOKENS,TIMEOUT}``;
JUDGE and SUPPORT also read ``_INPUT_BYTES``. A value missing for SUPPORT is taken from
JUDGE; one missing for any slot falls back to the shared ``CAREER_LAB_KEY_FILE``,
``CAREER_LAB_BASE_URL``, ``CAREER_LAB_MODEL`` and ``--provider``, then the provider's
defaults. With no slot variable set, every model, request and provenance matches the
single shared configuration. Real adapters never retry; keys are read here only and are
never logged, persisted or included in errors.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from career_lab.contracts.v2.core import ProtocolError, digest
from career_lab.runtime.model_adapter import (
    LocalModel,
    ModelAdapter,
    OpenAICompatibleModel,
    read_key,
)
from career_lab.runtime.roles_v2 import LocalRoleModel

SLOTS = ("ROLES", "JUDGE", "SUPPORT", "ASSISTANT")
PROVIDERS = ("local", "deepseek", "openai", "openai_compatible")
# key file, base URL, model; only the hosted providers have defaults.
PROVIDER_DEFAULTS = {
    "deepseek": ("ds.txt", "https://api.deepseek.com", "deepseek-chat"),
    "openai": ("openai.txt", "https://api.openai.com/v1", "gpt-4.1-mini"),
}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_MAX_TOKENS = 512
DEFAULT_TIMEOUT = 45.0
DEFAULT_INPUT_BYTES = 64000


@dataclass(frozen=True)
class SlotConfig:
    """One slot's resolved, non-secret configuration."""

    slot: str
    provider: str
    base_url: str | None = None
    model: str | None = None
    key_file: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT
    input_bytes: int | None = None

    def fingerprint(self) -> str:
        """Digest of the non-secret fields; the key file is represented only by presence."""
        return digest(
            {
                "provider": self.provider,
                "base_url": self.base_url,
                "model": self.model,
                "key_configured": self.key_file is not None,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "input_bytes": self.input_bytes,
            }
        )[:16]

    def describe(self) -> str:
        model = self.model or "none"
        return (
            f"career-lab model slot {self.slot}: provider={self.provider} model={model} "
            f"fingerprint={self.fingerprint()}"
        )


@dataclass(frozen=True)
class ModelSlots:
    """The models one service instance uses; ``None`` means the slot is not configured.

    ``legacy`` is the v1 application's model: the ROLES adapter, or the local
    extractive model when ROLES is local.
    """

    roles: Any
    judge: ModelAdapter | None
    support: ModelAdapter | None
    assistant: ModelAdapter | None
    legacy: ModelAdapter
    judge_input_bytes: int = DEFAULT_INPUT_BYTES
    support_input_bytes: int = DEFAULT_INPUT_BYTES
    configs: tuple[SlotConfig, ...] = ()

    @classmethod
    def shared(cls, model: Any) -> "ModelSlots":
        """One model for every slot, as callers that pass a single role model expect."""
        if isinstance(model, LocalRoleModel):
            return cls(model, None, None, None, LocalModel())
        return cls(model, model, model, model, model)

    def describe(self) -> tuple[str, ...]:
        return tuple(config.describe() for config in self.configs)


def _number(raw: str | None, default, kind, lower, upper):
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ProtocolError("model_slot_value_invalid", status=503) from None
    if not lower <= value <= upper:
        raise ProtocolError("model_slot_value_invalid", status=503)
    return value


def slot_config(slot: str, provider: str, environ: Mapping[str, str]) -> SlotConfig:
    def value(name: str, shared: str | None = None) -> str | None:
        names = ["CAREER_LAB_" + slot + "_" + name]
        if slot == "SUPPORT":
            names.append("CAREER_LAB_JUDGE_" + name)
        if shared is not None:
            names.append("CAREER_LAB_" + shared)
        return next((environ[n] for n in names if environ.get(n)), None)

    chosen = value("PROVIDER") or provider
    if chosen not in PROVIDERS:
        raise ProtocolError("model_slot_provider_invalid", status=503)
    max_tokens = _number(value("MAX_TOKENS"), DEFAULT_MAX_TOKENS, int, 1, 32768)
    timeout = _number(value("TIMEOUT"), DEFAULT_TIMEOUT, float, 0.001, 120.0)
    input_bytes = (
        _number(value("INPUT_BYTES"), DEFAULT_INPUT_BYTES, int, 512, 16_000_000)
        if slot in ("JUDGE", "SUPPORT")
        else None
    )
    if chosen == "local":
        return SlotConfig(
            slot, chosen, max_tokens=max_tokens, timeout=timeout, input_bytes=input_bytes
        )
    default_key, default_url, default_model = PROVIDER_DEFAULTS.get(chosen, (None, None, None))
    base_url = value("BASE_URL", "BASE_URL") or default_url
    model = value("MODEL", "MODEL") or default_model
    key_file = value("KEY_FILE", "KEY_FILE") or default_key
    if not base_url or not model:
        raise ProtocolError("model_slot_configuration_incomplete", status=503)
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
    except ValueError:
        raise ProtocolError("model_slot_value_invalid", status=503) from None
    if parts.scheme not in ("http", "https") or not host:
        raise ProtocolError("model_slot_value_invalid", status=503)
    if key_file is None and (chosen != "openai_compatible" or host not in LOOPBACK_HOSTS):
        raise ProtocolError("model_slot_key_required", status=503)
    return SlotConfig(slot, chosen, base_url, model, key_file, max_tokens, timeout, input_bytes)


def configured_slots(
    provider: str = "local", environ: Mapping[str, str] | None = None
) -> ModelSlots:
    """Resolve all four slots; identically configured slots share one adapter."""
    environ = os.environ if environ is None else environ
    configs = tuple(slot_config(slot, provider, environ) for slot in SLOTS)
    adapters: dict[tuple, OpenAICompatibleModel] = {}

    def adapter(config: SlotConfig) -> OpenAICompatibleModel | None:
        if config.provider == "local":
            return None
        identity = (
            config.provider,
            config.base_url,
            config.model,
            config.key_file,
            config.max_tokens,
            config.timeout,
        )
        if identity not in adapters:
            key = read_key(Path(config.key_file)) if config.key_file else None
            model = OpenAICompatibleModel(
                key,
                config.base_url,
                config.model,
                timeout=config.timeout,
                retries=0,
                max_tokens=config.max_tokens,
            )
            model.provider = config.provider
            adapters[identity] = model
        return adapters[identity]

    roles, judge, support, assistant = (adapter(config) for config in configs)
    return ModelSlots(
        roles=roles if roles is not None else LocalRoleModel(),
        judge=judge,
        support=support,
        assistant=assistant,
        legacy=roles if roles is not None else LocalModel(),
        judge_input_bytes=configs[1].input_bytes,
        support_input_bytes=configs[2].input_bytes,
        configs=configs,
    )
