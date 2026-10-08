"""Reject embedded credentials and machine-local paths in portable configuration."""

import json
from pathlib import PurePosixPath, PureWindowsPath

import yaml

from career_lab.contracts.v2.core import FileRef, ProtocolError

CREDENTIAL_FIELDS = frozenset(
    {
        "api_key",
        "authorization",
        "password",
        "session_token",
        "access_token",
        "secret_key",
        "secret",
    }
)


def validate_portability(raw: bytes, ref: FileRef) -> None:
    """Configuration bytes are data, never executable or a model registration."""
    if ref.media_type in {"application/yaml", "application/x-yaml", "text/yaml"}:
        value = yaml.safe_load(raw)
    else:
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            if ref.media_type == "application/json":
                raise ProtocolError("registry_json_invalid") from None
            return
    _check(value)


def _check(value: object) -> None:
    if isinstance(value, dict):
        fields = {str(key).lower().replace("-", "_") for key in value}
        if fields & CREDENTIAL_FIELDS:
            raise ProtocolError("registry_credentials_forbidden", status=403)
        for child in value.values():
            _check(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check(child)
    elif isinstance(value, str) and (
        PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
    ):
        raise ProtocolError("registry_machine_path_forbidden", status=403)
