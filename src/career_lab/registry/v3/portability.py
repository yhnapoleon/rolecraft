"""Reject embedded credentials and machine-local paths in portable configuration."""

import json
import re
import tomllib
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

import yaml

from career_lab.contracts.v2.core import FileRef, ProtocolError
from career_lab.delegations.credential_fields import (
    CREDENTIAL_ASSIGNMENT,
    is_credential_field,
    is_credential_value,
)

# Keep authority punctuation intact; splitting before @ can conceal URL userinfo.
URI = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|//)[^\s<>]+")


def reject_url_credentials(value: str) -> None:
    for candidate in URI.findall(value):
        try:
            url = urlsplit(candidate)
            if url.username is not None or url.password is not None:
                raise ProtocolError("registry_credentials_forbidden", status=403)
        except ValueError as error:
            if isinstance(error, ProtocolError):
                raise
            raise ProtocolError("registry_configuration_invalid") from None


MACHINE_PATH = re.compile(
    r"(?<![\w./\\:-])(?:/(?:Users|home|private|tmp|Volumes|etc|root|var|opt|usr|mnt)/\S+"
    r"|[A-Za-z]:[\\/]\S+|\\\\[^\s\\]+\\\S+)"
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
    suffix = PurePosixPath(ref.path).suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        if "toml" in ref.media_type or suffix in {".toml", ".lock"}:
            return tomllib.loads(text)
        if suffix in {".yaml", ".yml"} or "yaml" in ref.media_type:
            return yaml.safe_load(text)
        return text
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        raise ProtocolError("registry_configuration_invalid") from exc


def _check(value: object, ancestors: frozenset[int]) -> None:
    if isinstance(value, (dict, list, tuple)):
        if id(value) in ancestors or len(ancestors) >= 64:
            raise ProtocolError("registry_configuration_invalid")
        ancestors = ancestors | {id(value)}
    if isinstance(value, dict):
        if any(is_credential_field(str(key)) for key in value) or _named_credential(value):
            raise ProtocolError("registry_credentials_forbidden", status=403)
        for key, child in value.items():
            _check(key, ancestors)
            _check(child, ancestors)
    elif isinstance(value, (list, tuple)):
        if _credential_pair(value):
            raise ProtocolError("registry_credentials_forbidden", status=403)
        for child in value:
            _check(child, ancestors)
    elif isinstance(value, str):
        if is_credential_value(value):
            raise ProtocolError("registry_credentials_forbidden", status=403)
        reject_url_credentials(value)
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise ProtocolError("registry_machine_path_forbidden", status=403)


def _credential_pair(value: list | tuple) -> bool:
    """Header pairs such as ["Authorization", "..."] carry the secret beside its name."""
    return (
        len(value) == 2
        and all(isinstance(part, str) for part in value)
        and is_credential_field(value[0])
        and bool(value[1].strip())
    )


def _named_credential(value: dict) -> bool:
    """Name/value header records such as {"name": "X-Api-Key", "value": "..."}."""
    secret = value.get("value")
    return (
        isinstance(secret, str)
        and bool(secret.strip())
        and any(
            isinstance(value.get(label), str) and is_credential_field(value[label])
            for label in ("name", "key", "header")
        )
    )
