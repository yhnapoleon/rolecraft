"""Shared credential field vocabulary for public redaction and portable inputs."""

import base64
import re

CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "access_key",
        "secret_access_key",
        "credential_key",
        "career_lab_credential_key",
        "api_token",
        "authorization",
        "password",
        "passwd",
        "session_token",
        "access_token",
        "refresh_token",
        "token",
        "secret_key",
        "private_key",
        "client_secret",
        "secret",
        "credential",
        "credentials",
        "bearer",
        "cookie",
    }
)


def normalized_field(name: str) -> str:
    return re.sub(r"[-_.\s]", "", name).casefold()


CREDENTIAL_FIELDS = frozenset(normalized_field(name) for name in CREDENTIAL_FIELD_NAMES)


# Words of snake, kebab, dotted, spaced, camel and upper-case names.
_SEGMENT = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def is_credential_field(name: str) -> bool:
    """Vendor prefixes keep the credential suffix: OPENAI_API_KEY, github_token, X-Api-Key."""
    normalized = normalized_field(name)
    if normalized in CREDENTIAL_FIELDS or normalized.endswith(("password", "passwd")):
        return True
    words = [word.casefold() for word in _SEGMENT.findall(name)]
    return any("".join(words[start:]) in CREDENTIAL_FIELDS for start in range(len(words)))


_names = "|".join(
    r"[-_.\s]*".join(re.escape(part) for part in name.split("_"))
    for name in sorted(CREDENTIAL_FIELD_NAMES, key=len, reverse=True)
)
# An underscore may join a vendor prefix (HF_TOKEN=); the name must still end at [:=].
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<![^\W_])(?:" + _names + r")[\"'`]*\s*[:=]\s*\S"
    r"|(?-i:Bearer)\s+[A-Za-z0-9\-._~+/]{16,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_BEARER = re.compile(r"(?i)\s*bearer\s+\S")
_BASIC = re.compile(r"(?i)\s*basic\s+([A-Za-z0-9+/]+={0,2})\s*")


def is_credential_value(value: str) -> bool:
    """HTTP authorization values: any Bearer token, or Basic base64 of user:password."""
    if _BEARER.match(value):
        return True
    basic = _BASIC.fullmatch(value)
    if basic is None:
        return False
    try:
        return b":" in base64.b64decode(basic.group(1), validate=True)
    except ValueError:
        return False
