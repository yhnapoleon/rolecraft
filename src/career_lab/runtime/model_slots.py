"""Per-slot model configuration, read once at startup for the server and the worker.

Four slots: ROLES (the three colleagues), JUDGE (semantic Judge), SUPPORT (support
verification) and ASSISTANT (knowledge-assistant generation).

A slot's identity (provider, key file, base URL, model) always comes from one layer,
never a mix, so a key is only ever sent to the endpoint it was configured with:

- ``CAREER_LAB_<SLOT>_PROVIDER`` set: the identity comes only from that slot's own
  ``_KEY_FILE``, ``_BASE_URL`` and ``_MODEL``, else the provider's own defaults
  (DeepSeek/OpenAI key file name, base URL and model);
- unset, SUPPORT takes the whole JUDGE slot;
- unset otherwise, the slot takes the whole shared layer: ``--provider`` with the shared
  ``CAREER_LAB_KEY_FILE``, ``CAREER_LAB_BASE_URL`` and ``CAREER_LAB_MODEL``.

Identity variables on a slot without its own provider refuse to start. Budgets
(``_MAX_TOKENS``, ``_TIMEOUT``, JUDGE/SUPPORT ``_INPUT_BYTES``) are per slot; SUPPORT
without its own provider takes JUDGE's budget for values it does not set. Dedicated
JUDGE/SUPPORT identities default to 2048 output tokens for structured citations;
ROLES/ASSISTANT and the legacy shared layer retain 512. Explicit budgets always win. With no slot
variable set, every model, request and provenance matches the single shared
configuration. ``openai_compatible`` may omit a key only on a loopback host, and then
sends no Authorization header. Real adapters never retry; keys are read here only and are
never logged, persisted or included in errors.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

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
PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "deepseek": ("ds.txt", "https://api.deepseek.com", "deepseek-chat"),
    "openai": ("openai.txt", "https://api.openai.com/v1", "gpt-4.1-mini"),
}
IDENTITY_VARIABLES = ("KEY_FILE", "BASE_URL", "MODEL")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_MAX_TOKENS = 512
DEFAULT_EVALUATION_MAX_TOKENS = 2048
DEFAULT_TIMEOUT = 45.0
DEFAULT_INPUT_BYTES = 64000

Source = Literal["slot", "shared"]
AdapterKey = tuple[str, str | None, str | None, str | None, int, float]


def public_url(url: str) -> str:
    """Scheme, host, port and path only: no user information, query or fragment."""
    parts = urlsplit(url.rstrip("/"))
    host = parts.hostname or ""
    netloc = ("[" + host + "]" if ":" in host else host) + (
        ":" + str(parts.port) if parts.port else ""
    )
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


@dataclass(frozen=True)
class SlotConfig:
    """One slot's resolved, non-secret configuration and the layer its identity came from."""

    slot: str
    provider: str
    base_url: str | None = None
    model: str | None = None
    key_file: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT
    input_bytes: int | None = None
    source: Source = "shared"

    @property
    def recorded_base_url(self) -> str | None:
        """Endpoint feedback provenance records: slot-configured identities only.

        The shared layer records none, exactly as before slots existed.
        """
        if self.source != "slot" or self.base_url is None:
            return None
        return public_url(self.base_url)

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

    def config(self, slot: str) -> SlotConfig | None:
        return next((config for config in self.configs if config.slot == slot), None)

    def recorded_base_url(self, slot: str) -> str | None:
        config = self.config(slot)
        return None if config is None else config.recorded_base_url

    def describe(self) -> tuple[str, ...]:
        return tuple(config.describe() for config in self.configs)


def _number(
    raw: str | None,
    default: float,
    kind: Callable[[str], float],
    lower: float,
    upper: float,
) -> Any:
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ProtocolError("model_slot_value_invalid", status=503) from None
    if not lower <= value <= upper:
        raise ProtocolError("model_slot_value_invalid", status=503)
    return value


def _variable(environ: Mapping[str, str], name: str) -> str | None:
    return environ.get("CAREER_LAB_" + name) or None


def _endpoint(
    slot: str,
    provider: str,
    key_file: str | None,
    base_url: str | None,
    model: str | None,
    source: Source,
) -> SlotConfig:
    """Validate one layer's identity; budgets are filled in by the caller."""
    if provider not in PROVIDERS:
        raise ProtocolError("model_slot_provider_invalid", status=503)
    if provider == "local":
        return SlotConfig(slot, provider, source=source)
    default_key, default_url, default_model = PROVIDER_DEFAULTS.get(provider, (None, None, None))
    key_file = key_file or default_key
    base_url = base_url or default_url
    model = model or default_model
    if not base_url or not model:
        raise ProtocolError("model_slot_configuration_incomplete", status=503)
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
    except ValueError:
        raise ProtocolError("model_slot_value_invalid", status=503) from None
    if parts.scheme not in ("http", "https") or not host:
        raise ProtocolError("model_slot_value_invalid", status=503)
    if key_file is None and (provider != "openai_compatible" or host not in LOOPBACK_HOSTS):
        raise ProtocolError("model_slot_key_required", status=503)
    return SlotConfig(slot, provider, base_url, model, key_file, source=source)


def slot_config(
    slot: str,
    provider: str,
    environ: Mapping[str, str],
    judge: SlotConfig | None = None,
) -> SlotConfig:
    """Resolve one slot; SUPPORT needs the already resolved JUDGE slot."""
    own = _variable(environ, slot + "_PROVIDER")
    if own is None and any(_variable(environ, slot + "_" + n) for n in IDENTITY_VARIABLES):
        raise ProtocolError("model_slot_provider_required", status=503)
    inherits = own is None and slot == "SUPPORT"
    if inherits:
        if judge is None:
            raise ValueError("SUPPORT resolves after JUDGE")
        identity = replace(judge, slot=slot)
    elif own is not None:
        identity = _endpoint(
            slot,
            own,
            _variable(environ, slot + "_KEY_FILE"),
            _variable(environ, slot + "_BASE_URL"),
            _variable(environ, slot + "_MODEL"),
            "slot",
        )
    else:
        identity = _endpoint(
            slot,
            provider,
            _variable(environ, "KEY_FILE"),
            _variable(environ, "BASE_URL"),
            _variable(environ, "MODEL"),
            "shared",
        )
    inherited = judge if inherits else None
    default_tokens = (
        DEFAULT_EVALUATION_MAX_TOKENS
        if identity.source == "slot" and slot in {"JUDGE", "SUPPORT"}
        else DEFAULT_MAX_TOKENS
    )
    max_tokens = _number(
        _variable(environ, slot + "_MAX_TOKENS"),
        inherited.max_tokens if inherited else default_tokens,
        int,
        1,
        32768,
    )
    timeout = _number(
        _variable(environ, slot + "_TIMEOUT"),
        inherited.timeout if inherited else DEFAULT_TIMEOUT,
        float,
        0.001,
        120.0,
    )
    input_bytes = None
    if slot in ("JUDGE", "SUPPORT"):
        input_bytes = _number(
            _variable(environ, slot + "_INPUT_BYTES"),
            inherited.input_bytes if inherited and inherited.input_bytes else DEFAULT_INPUT_BYTES,
            int,
            512,
            16_000_000,
        )
    return replace(identity, max_tokens=max_tokens, timeout=timeout, input_bytes=input_bytes)


def configured_slots(
    provider: str = "local", environ: Mapping[str, str] | None = None
) -> ModelSlots:
    """Resolve all four slots; identically configured slots share one adapter."""
    environ = os.environ if environ is None else environ
    resolved: dict[str, SlotConfig] = {}
    for slot in SLOTS:
        resolved[slot] = slot_config(slot, provider, environ, resolved.get("JUDGE"))
    adapters: dict[AdapterKey, OpenAICompatibleModel] = {}

    def adapter(config: SlotConfig) -> OpenAICompatibleModel | None:
        if config.provider == "local" or config.base_url is None or config.model is None:
            return None
        key = (
            config.provider,
            config.base_url,
            config.model,
            config.key_file,
            config.max_tokens,
            config.timeout,
        )
        if key not in adapters:
            secret = read_key(Path(config.key_file)) if config.key_file else None
            model = OpenAICompatibleModel(
                secret,
                config.base_url,
                config.model,
                timeout=config.timeout,
                retries=0,
                max_tokens=config.max_tokens,
            )
            model.provider = config.provider
            adapters[key] = model
        return adapters[key]

    roles = adapter(resolved["ROLES"])
    return ModelSlots(
        roles=roles if roles is not None else LocalRoleModel(),
        judge=adapter(resolved["JUDGE"]),
        support=adapter(resolved["SUPPORT"]),
        assistant=adapter(resolved["ASSISTANT"]),
        legacy=roles if roles is not None else LocalModel(),
        judge_input_bytes=resolved["JUDGE"].input_bytes or DEFAULT_INPUT_BYTES,
        support_input_bytes=resolved["SUPPORT"].input_bytes or DEFAULT_INPUT_BYTES,
        configs=tuple(resolved[slot] for slot in SLOTS),
    )
