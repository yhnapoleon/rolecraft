"""Reject embedded credentials and machine-local paths in portable configuration."""

import json
import re
import tomllib
from pathlib import PurePosixPath, PureWindowsPath

import yaml

from career_lab.contracts.v2.core import FileRef, ProtocolError

CREDENTIAL_FIELDS = frozenset(
    {"apikey", "authorization", "password", "sessiontoken", "accesstoken", "secretkey", "secret"}
)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|authorization|password|session[_-]?token|access[_-]?token|"
    r"secret[_-]?key)[\"']?\s*[:=]\s*\S|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
MACHINE_PATH = re.compile(
    r"(?<![\w./\\:-])/(?:Users|home|private|tmp|Volumes|etc|root|var|opt|usr|mnt)/\S+"
)
TEXT_MEDIA_TYPES = frozenset(
    {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "application/toml",
        "text/toml",
        "text/plain",
        "text/markdown",
    }
)


def validate_portability(raw: bytes, ref: FileRef) -> None:
    """Inspect text even when mislabeled; opaque configuration fails closed."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("registry_member_format_unsupported") from exc
    if CREDENTIAL_ASSIGNMENT.search(text):
        raise ProtocolError("registry_credentials_forbidden", status=403)
    if MACHINE_PATH.search(text):
        raise ProtocolError("registry_machine_path_forbidden", status=403)
    try:
        value = json.loads(text)
    except ValueError:
        if ref.media_type not in TEXT_MEDIA_TYPES:
            raise ProtocolError("registry_member_format_unsupported") from None
        value = _structured_text(text, ref)
    _check(value, frozenset())


def _structured_text(text: str, ref: FileRef) -> object:
    if ref.media_type in {"text/plain", "text/markdown"}:
        return text
    try:
        if "toml" in ref.media_type or ref.path.endswith((".toml", ".lock")):
            return tomllib.loads(text)
        return yaml.safe_load(text)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        raise ProtocolError("registry_configuration_invalid") from exc


def _check(value: object, ancestors: frozenset[int]) -> None:
    if isinstance(value, (dict, list, tuple)):
        if id(value) in ancestors or len(ancestors) >= 64:
            raise ProtocolError("registry_configuration_invalid")
        ancestors = ancestors | {id(value)}
    if isinstance(value, dict):
        fields = {str(key).lower().replace("-", "").replace("_", "") for key in value}
        if fields & CREDENTIAL_FIELDS:
            raise ProtocolError("registry_credentials_forbidden", status=403)
        for child in value.values():
            _check(child, ancestors)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check(child, ancestors)
    elif isinstance(value, str) and (
        PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
    ):
        raise ProtocolError("registry_machine_path_forbidden", status=403)
