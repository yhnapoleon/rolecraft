"""Reject embedded credentials and machine-local paths in portable configuration."""

import json
import re
import tomllib
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

import yaml

from career_lab.contracts.v2.core import FileRef, ProtocolError
from career_lab.delegations.credential_fields import CREDENTIAL_ASSIGNMENT, is_credential_field

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
        if any(is_credential_field(str(key)) for key in value):
            raise ProtocolError("registry_credentials_forbidden", status=403)
        for child in value.values():
            _check(child, ancestors)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check(child, ancestors)
    elif isinstance(value, str):
        reject_url_credentials(value)
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise ProtocolError("registry_machine_path_forbidden", status=403)
