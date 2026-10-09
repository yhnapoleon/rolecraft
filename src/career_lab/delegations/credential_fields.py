"""Shared credential field vocabulary for public redaction and portable inputs."""

import re

CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "career_lab_credential_key",
        "api_token",
        "authorization",
        "password",
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


def is_credential_field(name: str) -> bool:
    return normalized_field(name) in CREDENTIAL_FIELDS


_names = "|".join(
    r"[-_.\s]*".join(re.escape(part) for part in name.split("_"))
    for name in sorted(CREDENTIAL_FIELD_NAMES, key=len, reverse=True)
)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<!\w)(?:" + _names + r")[\"'`]*\s*[:=]\s*\S"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
