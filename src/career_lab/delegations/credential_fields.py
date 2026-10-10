"""Shared credential vocabulary and secret shapes for public redaction and portable inputs."""

import base64
import json
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
        "pwd",
        "session_token",
        "access_token",
        "refresh_token",
        "token",
        "secret_key",
        "private_key",
        "client_secret",
        "secret",
        "credential",
    }
)
# Collections in which every text entry is a secret: key pools and secret maps.
COLLECTION_FIELD_NAMES = frozenset({"secrets", "api_keys", "passwords", "credentials"})
# HTTP words that also end OpenAPI security-scheme names (HTTPBearer, APIKeyCookie) match
# only as the whole field name.
WHOLE_FIELD_NAMES = frozenset({"bearer", "cookie"})
# Tokenizer configuration fields hold vocabulary strings such as "</s>", not credentials.
TOKENIZER_FIELD_NAMES = frozenset(
    {"eos_token", "pad_token", "bos_token", "unk_token", "sep_token", "cls_token", "mask_token"}
)


def normalized_field(name: str) -> str:
    return re.sub(r"[-_.\s]", "", name).casefold()


SUFFIX_FIELDS = frozenset(
    normalized_field(name) for name in CREDENTIAL_FIELD_NAMES | COLLECTION_FIELD_NAMES
)
COLLECTION_FIELDS = frozenset(normalized_field(name) for name in COLLECTION_FIELD_NAMES)
WHOLE_FIELDS = frozenset(normalized_field(name) for name in WHOLE_FIELD_NAMES)

# Words of snake, kebab, dotted, spaced, camel and upper-case names.
_SEGMENT = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
# Environment and header conventions: AZURE_OPENAI_KEY, X-API-KEY, Ocp-Apim-Subscription-Key.
_PROVIDER_KEY = re.compile(r"[A-Z0-9]+(?:[_-][A-Z0-9]+)*[_-]KEY|(?:[A-Z][A-Za-z0-9]*-)+Key")


def _ends_with(name: str, fields: frozenset[str]) -> bool:
    words = [word.casefold() for word in _SEGMENT.findall(name)]
    return any("".join(words[start:]) in fields for start in range(len(words)))


def is_credential_field(name: str) -> bool:
    """Vendor prefixes keep the credential suffix: OPENAI_API_KEY, github_token, X-Api-Key."""
    last = name.rsplit(None, 1)[-1] if name.strip() else name
    if last.casefold() in TOKENIZER_FIELD_NAMES:
        return False
    normalized = normalized_field(name)
    if normalized in SUFFIX_FIELDS | WHOLE_FIELDS or normalized.endswith(("password", "passwd")):
        return True
    return bool(_PROVIDER_KEY.fullmatch(last)) or _ends_with(name, SUFFIX_FIELDS)


def is_collection_field(name: str) -> bool:
    return _ends_with(name, COLLECTION_FIELDS)


# Provider formats; a digit is required where a prefix could also begin an ordinary word.
_SECRET_SHAPE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"(?:sk-|hf_)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{30,})"
)
# A JWS header names its algorithm; the signature segment may be detached.
_JWT = re.compile(r"(?<![A-Za-z0-9_-])(eyJ[A-Za-z0-9_-]{6,})\.[A-Za-z0-9_-]{4,}")


def has_secret_shape(text: str) -> bool:
    if _SECRET_SHAPE.search(text):
        return True
    for match in _JWT.finditer(text):
        header = match.group(1)
        try:
            decoded = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
        except ValueError:
            continue
        if isinstance(decoded, dict) and "alg" in decoded:
            return True
    return False


_TOKEN68 = r"[A-Za-z0-9\-._~+/]{16,}=*"
_BEARER = re.compile(r"(?i)\s*bearer\s+" + _TOKEN68 + r"(?:\s|$)")
_BASIC = re.compile(r"(?i)\s*basic\s+([A-Za-z0-9+/]+={0,2})\s*")


def is_credential_value(value: str) -> bool:
    """A Bearer token, Basic base64 of user:password, or a well-known secret format."""
    if _BEARER.match(value) or has_secret_shape(value):
        return True
    basic = _BASIC.fullmatch(value)
    if basic is None:
        return False
    try:
        return b":" in base64.b64decode(basic.group(1), validate=True)
    except ValueError:
        return False


_WORD = r"[A-Za-z_][\w.-]*"
# Up to four words before ":" or "="; the value is only looked at, so the scan continues there.
_ASSIGNMENT = re.compile(
    rf"(?<![\w.-])(?P<name>{_WORD}(?:[ \t]+{_WORD}){{0,3}})[\"'`]*[ \t]*[:=][ \t]*"
    r"(?=(?P<value>[^\s,;]*))"
)
# Raw text keeps the HTTP spelling "Bearer"; lower-case "bearer" is ordinary prose.
_RAW_CREDENTIAL = re.compile(
    r"Bearer\s+" + _TOKEN68 + r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_NOT_SECRET = re.compile(r"(?i)null|true|false|none|~|-?\d+(?:\.\d+)?")


def _assigned_text(value: str) -> bool:
    """Assignments of null, booleans, numbers, structures or empty strings hold no secret."""
    text = value.rstrip(",;)}]").strip("\"'`")
    return bool(text) and not text.startswith(("{", "[")) and not _NOT_SECRET.fullmatch(text)


def has_credential_text(text: str) -> bool:
    """Scan unparsed text, including comments, for credential assignments and secret formats."""
    if _RAW_CREDENTIAL.search(text) or has_secret_shape(text):
        return True
    return any(
        is_credential_field(match["name"]) and _assigned_text(match["value"])
        for match in _ASSIGNMENT.finditer(text)
    )
