"""Portable registry inputs reject credentials before persisting any member bytes."""

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from career_lab.contracts.v2.core import FileRef
from career_lab.contracts.v2.research import RuntimeBundle
from career_lab.delegations.credential_fields import is_credential_field
from career_lab.delegations.credentials import redact
from career_lab.registry.v3.store import BundleRegistry

ROOT = Path(__file__).resolve().parents[2]
SECRET = "synthetic-registry-secret-value"
FORMATS = {
    "json": "application/json",
    "yaml": "application/yaml",
    "toml": "application/toml",
    "txt": "text/plain",
}


def member(root: Path, name: str, raw: bytes, media_type: str = "application/json") -> FileRef:
    (root / name).write_bytes(raw)
    return FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest(), media_type=media_type)


def register_config(
    tmp_path: Path, suffix: str, content: str, media_type: str
) -> tuple[subprocess.CompletedProcess[str], Path, FileRef]:
    source = tmp_path / "source"
    source.mkdir()
    safe = member(source, "safe.json", b'{"mode":"fixture"}')
    config = member(source, "model." + suffix, content.encode(), media_type)
    runtime = RuntimeBundle(
        id="portable-runtime",
        revision="example",
        model=config,
        prompts=(safe,),
        acquisition=safe,
        retrieval=safe,
        decision=safe,
        tools=safe,
        source={"base_commit": "2" * 40, "source_digest": "3" * 64},
    )
    root = member(source, "runtime.json", runtime.model_dump_json().encode())
    registry = tmp_path / "registry"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.registry.v3",
            "--registry",
            str(registry),
            "register",
            "--kind",
            "runtime",
            "--source",
            str(source),
            "--manifest",
            root.path,
            "--sha256",
            root.sha256,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, registry, config


@pytest.mark.parametrize("suffix", FORMATS)
@pytest.mark.parametrize(
    "kind", ["token", "refresh_token", "url_userinfo", "CAREER_LAB_CREDENTIAL_KEY"]
)
def test_T1_registry_cli_rejects_credentials_without_persisting_bytes(
    tmp_path: Path, suffix: str, kind: str
) -> None:
    key = "endpoint" if kind == "url_userinfo" else kind
    value = f"https://review-user:{SECRET}@example.invalid/v1" if kind == "url_userinfo" else SECRET
    if suffix == "json":
        content = json.dumps({"settings": {key: value}})
    elif suffix == "yaml":
        content = f'settings:\n  {key}: "{value}"\n'
    else:
        content = f'{key} = "{value}"\n'
    result, registry, _ = register_config(tmp_path, suffix, content, FORMATS[suffix])
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    assert SECRET not in result.stdout + result.stderr
    assert all(
        SECRET.encode() not in file.read_bytes() for file in registry.rglob("*") if file.is_file()
    )


@pytest.mark.parametrize(
    "suffix,media,content",
    [
        (
            "json",
            "application/json",
            '{"path":"models/relative.json","endpoint":"https://example.invalid/v1"}',
        ),
        (
            "yaml",
            "application/yaml",
            "path: models/relative.json\nendpoint: https://example.invalid/v1\n",
        ),
        (
            "toml",
            "application/toml",
            'path = "models/relative.json"\nendpoint = "https://example.invalid/v1"\n',
        ),
        (
            "md",
            "text/markdown",
            "# Method\nRead models/relative.json and https://example.invalid/docs.\n",
        ),
    ],
)
def test_T1_relative_references_and_credential_free_documents_remain_portable(
    tmp_path: Path, suffix: str, media: str, content: str
) -> None:
    result, path, config = register_config(tmp_path, suffix, content, media)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["identity"]
    assert BundleRegistry(path).resolve_file(identity, config) == content.encode()


@pytest.mark.parametrize("with_credentials", [False, True])
def test_T1_ipv6_url_authority_uses_the_same_credential_boundary(
    tmp_path: Path, with_credentials: bool
) -> None:
    authority = f"user:{SECRET}@" if with_credentials else ""
    content = json.dumps({"endpoint": f"http://{authority}[::1]:8080/api"})
    result, registry, _ = register_config(tmp_path, "json", content, "application/json")
    if with_credentials:
        assert result.returncode != 0
        assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
        assert all(
            SECRET.encode() not in file.read_bytes()
            for file in registry.rglob("*")
            if file.is_file()
        )
    else:
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("suffix", FORMATS)
@pytest.mark.parametrize("punctuation", [")", "'", "`", "}"])
def test_T1_url_userinfo_punctuation_cannot_truncate_credential_detection(
    tmp_path: Path, suffix: str, punctuation: str
) -> None:
    value = f"https://review-user:{SECRET}{punctuation}tail@example.invalid/v1"
    if suffix == "json":
        content = json.dumps({"endpoint": value})
    elif suffix == "yaml":
        content = f'endpoint: "{value}"\n'
    else:
        content = f'endpoint = "{value}"\n'
    result, registry, _ = register_config(tmp_path, suffix, content, FORMATS[suffix])
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    assert SECRET not in result.stdout + result.stderr
    assert all(
        SECRET.encode() not in file.read_bytes() for file in registry.rglob("*") if file.is_file()
    )


def test_T1_separate_json_email_field_is_not_url_userinfo(tmp_path: Path) -> None:
    content = '{"endpoint":"https://example.invalid","contact":"reviewer@example.invalid"}'
    result, registry, config = register_config(tmp_path, "json", content, "application/json")
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["identity"]
    assert BundleRegistry(registry).resolve_file(identity, config) == content.encode()


@pytest.mark.parametrize("suffix", ["json", "yaml", "toml"])
def test_T1_url_credentials_in_mapping_keys_are_rejected(tmp_path: Path, suffix: str) -> None:
    endpoint = f"https://review-user:{SECRET}@example.invalid/v1"
    if suffix == "json":
        content = json.dumps({"endpoints": {endpoint: {"enabled": True}}})
    elif suffix == "yaml":
        content = f'endpoints:\n  "{endpoint}":\n    enabled: true\n'
    else:
        content = f'[endpoints."{endpoint}"]\nenabled = true\n'
    result, registry, _ = register_config(tmp_path, suffix, content, FORMATS[suffix])
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    assert SECRET not in result.stdout + result.stderr
    assert all(
        SECRET.encode() not in file.read_bytes() for file in registry.rglob("*") if file.is_file()
    )


URL_SECRET = f"https://review-user:{SECRET}@example.invalid/v1"
BASIC_SECRET = base64.b64encode(f"review-user:{SECRET}".encode()).decode()

# Cases from the 118 review: the first eleven were already rejected, the next nine were
# accepted with the secret persisted, and the remainder cover the value and pair rules.
REJECTED = {
    "json-token": ("json", "application/json", json.dumps({"model": {"token": SECRET}})),
    "json-refresh_token": ("json", "application/json", json.dumps({"refresh_token": SECRET})),
    "json-url-userinfo": ("json", "application/json", json.dumps({"endpoint": URL_SECRET})),
    "yaml-token": ("yaml", "application/yaml", f"token: {SECRET}\n"),
    "yaml-url-userinfo": ("yaml", "application/yaml", f"endpoint: {URL_SECRET}\n"),
    "toml-refresh_token": ("toml", "application/toml", f'refresh_token = "{SECRET}"\n'),
    "txt-url-userinfo": ("txt", "text/plain", f"Use {URL_SECRET} for calls\n"),
    "md-url-userinfo": ("md", "text/markdown", f"# Ops\nEndpoint <{URL_SECRET}>\n"),
    "json-unicode-escaped-token-key": (
        "json",
        "application/json",
        '{"to\\u006ben": "' + SECRET + '"}',
    ),
    "json-url-in-key": ("json", "application/json", json.dumps({URL_SECRET: "x"})),
    "txt-pem-private-key": (
        "txt",
        "text/plain",
        "-----BEGIN PRIVATE KEY-----\n" + SECRET + "\n-----END PRIVATE KEY-----\n",
    ),
    "json-OPENAI_API_KEY": ("json", "application/json", json.dumps({"OPENAI_API_KEY": SECRET})),
    "yaml-openai_api_key": ("yaml", "application/yaml", f"openai_api_key: {SECRET}\n"),
    "env-OPENAI_API_KEY": ("txt", "text/plain", f"OPENAI_API_KEY={SECRET}\n"),
    "env-HF_TOKEN": ("txt", "text/plain", f"HF_TOKEN={SECRET}\n"),
    "json-github_token": ("json", "application/json", json.dumps({"github_token": SECRET})),
    "json-auth_token": ("json", "application/json", json.dumps({"auth_token": SECRET})),
    "json-passwd": ("json", "application/json", json.dumps({"passwd": SECRET})),
    "toml-aws_secret_access_key": (
        "toml",
        "application/toml",
        f'aws_secret_access_key = "{SECRET}"\n',
    ),
    "json-authorization-header-pair": (
        "json",
        "application/json",
        json.dumps({"headers": [["Authorization", "Bearer " + SECRET]]}),
    ),
    "json-api-key-header-pair": (
        "json",
        "application/json",
        json.dumps({"headers": [["X-Api-Key", SECRET]]}),
    ),
    "yaml-named-header-value": (
        "yaml",
        "application/yaml",
        f"headers:\n  - name: X-Api-Key\n    value: {SECRET}\n",
    ),
    "json-bearer-value": (
        "json",
        "application/json",
        json.dumps({"headers": {"X-Auth": "Bearer " + SECRET}}),
    ),
    "json-basic-value": (
        "json",
        "application/json",
        json.dumps({"headers": {"X-Auth": "Basic " + BASIC_SECRET}}),
    ),
    "md-inline-bearer-header": (
        "md",
        "text/markdown",
        f"# Calls\nSend `X-Auth: Bearer {SECRET}` with each call.\n",
    ),
    "json-camel-vendor-key": ("json", "application/json", json.dumps({"openaiApiKey": SECRET})),
    "env-DB_PASSWORD": ("txt", "text/plain", f"DB_PASSWORD={SECRET}\n"),
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_T1_credential_spellings_are_rejected_without_persisting_or_echoing(
    tmp_path: Path, case: str
) -> None:
    assert_rejected(tmp_path, *REJECTED[case], (SECRET, BASIC_SECRET))


def assert_rejected(
    tmp_path: Path, suffix: str, media: str, content: str, markers: tuple[str, ...]
) -> None:
    result, registry, _ = register_config(tmp_path, suffix, content, media)
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    for marker in markers:
        assert marker not in result.stdout + result.stderr
        assert all(
            marker.encode() not in file.read_bytes()
            for file in registry.rglob("*")
            if file.is_file()
        )


JWT_SECRET = "eyJhbGciOiJIUzI1NiJ9." + SECRET + ".c2lnbmF0dXJl"
SHAPED_SECRET = "sk-proj-" + SECRET + "-2026"

# Second 118 review: realistic provider spellings that still reached the registry.
SECOND_REVIEW_REJECTED = {
    "env-AZURE_OPENAI_KEY": ("txt", "text/plain", f"AZURE_OPENAI_KEY={SECRET}\n"),
    "env-OPENAI_KEY": ("txt", "text/plain", f"OPENAI_KEY={SECRET}\n"),
    "json-Ocp-Apim-Subscription-Key": (
        "json",
        "application/json",
        json.dumps({"headers": {"Ocp-Apim-Subscription-Key": SECRET}}),
    ),
    "json-provider-key-shaped": (
        "json",
        "application/json",
        json.dumps({"provider": "openai", "key": SHAPED_SECRET}),
    ),
    "json-provider-key-plain": (
        "json",
        "application/json",
        json.dumps({"provider": "openai", "key": SECRET}),
    ),
    "yaml-api_keys-list": ("yaml", "application/yaml", f"api_keys:\n  - {SECRET}\n"),
    "yaml-secrets-mapping": ("yaml", "application/yaml", f"secrets:\n  openai: {SECRET}\n"),
    "yaml-passwords-list": ("yaml", "application/yaml", f"passwords:\n  - {SECRET}\n"),
    "json-pwd": (
        "json",
        "application/json",
        json.dumps({"db": {"user": "reviewer", "pwd": SECRET}}),
    ),
    "json-jwt-under-auth": ("json", "application/json", json.dumps({"auth": JWT_SECRET})),
    "md-jwt-in-prose": ("md", "text/markdown", f"# Calls\nReuse {JWT_SECRET} for calls.\n"),
}


@pytest.mark.parametrize("case", sorted(SECOND_REVIEW_REJECTED))
def test_T1_provider_key_spellings_are_rejected_without_persisting_or_echoing(
    tmp_path: Path, case: str
) -> None:
    assert_rejected(tmp_path, *SECOND_REVIEW_REJECTED[case], (SECRET,))


# Well-known secret formats are rejected under any field name. Synthetic, not real keys.
SHAPED_VALUES = {
    "openai": "sk-proj-" + "synthetic0value" * 2,
    "anthropic": "sk-ant-" + "synthetic0value" * 2,
    "github-classic": "ghp_" + "Synthetic0Value" * 3,
    "github-fine-grained": "github_pat_" + "Synthetic0Value" * 3,
    "hugging-face": "hf_" + "Synthetic0Value" * 2,
    "aws-access-key": "AKIA" + "SYNTHETIC0VALUE0",
    "slack": "xoxb-" + "0123456789-synthetic",
    "google": "AIza" + "Synthetic0Value" * 3,
}


@pytest.mark.parametrize("shape", sorted(SHAPED_VALUES))
@pytest.mark.parametrize("suffix", ["json", "txt"])
def test_T1_secret_shaped_values_are_rejected_under_neutral_names(
    tmp_path: Path, shape: str, suffix: str
) -> None:
    value = SHAPED_VALUES[shape]
    if suffix == "json":
        content = json.dumps({"connection": {"note": value}})
    else:
        content = f"Use {value} for the call.\n"
    assert_rejected(tmp_path, suffix, FORMATS[suffix], content, (value,))


PUBLISHED_OPENAPI = json.loads((ROOT / "docs/contracts/expansion-v3/openapi.json").read_text())
OPENAPI_SCHEME = {
    "openapi": "3.1.0",
    "components": {"securitySchemes": {"HTTPBearer": {"type": "http", "scheme": "bearer"}}},
    "security": [{"HTTPBearer": []}],
}
TOKENIZER_FIELDS = {
    "eos_token": "</s>",
    "pad_token": "<pad>",
    "bos_token": "<s>",
    "unk_token": "<unk>",
    "sep_token": "[SEP]",
    "cls_token": "[CLS]",
    "mask_token": "[MASK]",
}

# Non-secret documents that the second review found rejected after suffix matching.
ACCEPTED_DOCUMENTS = {
    "json-null-page-token": ("json", "application/json", json.dumps({"next_page_token": None})),
    "json-false-secret-flag": ("json", "application/json", json.dumps({"is_secret": False})),
    "json-tokenizer-special-tokens": ("json", "application/json", json.dumps(TOKENIZER_FIELDS)),
    "yaml-tokenizer-special-tokens": (
        "yaml",
        "application/yaml",
        "".join(f"{key}: {json.dumps(value)}\n" for key, value in TOKENIZER_FIELDS.items()),
    ),
    "json-bearer-prose": (
        "json",
        "application/json",
        json.dumps({"note": "Bearer of the final decision"}),
    ),
    "json-openapi-bearer-scheme": ("json", "application/json", json.dumps(OPENAPI_SCHEME)),
    "json-published-openapi-components": (
        "json",
        "application/json",
        json.dumps({key: value for key, value in PUBLISHED_OPENAPI.items() if key != "paths"}),
    ),
    "json-sort-key": (
        "json",
        "application/json",
        json.dumps({"sort": {"key": "created_at", "order": "desc"}}),
    ),
    "json-words-with-key-prefixes": (
        "json",
        "application/json",
        json.dumps({"note": "risk-assessment-2024-quarterly-review and task-0123456789abcdef"}),
    ),
}


@pytest.mark.parametrize("case", sorted(ACCEPTED_DOCUMENTS))
def test_T1_non_secret_documents_register_and_round_trip(tmp_path: Path, case: str) -> None:
    suffix, media, content = ACCEPTED_DOCUMENTS[case]
    result, registry, config = register_config(tmp_path, suffix, content, media)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["identity"]
    assert BundleRegistry(registry).resolve_file(identity, config) == content.encode()


def test_T1_published_openapi_passes_the_credential_layer(tmp_path: Path) -> None:
    content = json.dumps(PUBLISHED_OPENAPI, indent=2)
    result, _, _ = register_config(tmp_path, "json", content, "application/json")
    # Its "/sessions/..." route keys remain subject to the separate machine-path rule.
    assert json.loads(result.stdout)["error"] == "registry_machine_path_forbidden"


ALLOWED_FIELDS = {
    "max_tokens": 4096,
    "token_budget": 2000,
    "token_count": 3,
    "credential_id": "reference-credential",
    "CAREER_LAB_CREDENTIAL_KEY_ID": "deployment-key-v1",
    "aws_access_key_id": "public-key-identifier",
    "summary": "Basic coverage of the brief",
}


@pytest.mark.parametrize(
    "suffix,media,content",
    [
        ("json", "application/json", json.dumps({"settings": ALLOWED_FIELDS})),
        (
            "yaml",
            "application/yaml",
            "settings:\n"
            + "".join(f"  {key}: {json.dumps(value)}\n" for key, value in ALLOWED_FIELDS.items()),
        ),
        (
            "toml",
            "application/toml",
            "[settings]\n"
            + "".join(f"{key} = {json.dumps(value)}\n" for key, value in ALLOWED_FIELDS.items()),
        ),
        (
            "txt",
            "text/plain",
            "".join(f"{key}={value}\n" for key, value in ALLOWED_FIELDS.items()),
        ),
    ],
)
def test_T1_non_secret_token_and_key_identifier_fields_remain_portable(
    tmp_path: Path, suffix: str, media: str, content: str
) -> None:
    result, registry, config = register_config(tmp_path, suffix, content, media)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["identity"]
    assert BundleRegistry(registry).resolve_file(identity, config) == content.encode()


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "openai_api_key",
        "HF_TOKEN",
        "github_token",
        "auth_token",
        "passwd",
        "DB_PASSWORD",
        "aws_secret_access_key",
        "X-Api-Key",
        "apiKey",
        "openaiApiKey",
        "Authorization",
        "AZURE_OPENAI_KEY",
        "OPENAI_KEY",
        "X-API-KEY",
        "Ocp-Apim-Subscription-Key",
        "pwd",
        "secrets",
        "api_keys",
        "passwords",
    ],
)
def test_T1_shared_vocabulary_matches_credential_name_suffixes(name: str) -> None:
    assert is_credential_field(name)


@pytest.mark.parametrize(
    "name",
    [
        *ALLOWED_FIELDS,
        *TOKENIZER_FIELDS,
        "idempotency_key",
        "token_limit",
        "key",
        "sort_key",
        "HTTPBearer",
        "OAuth2PasswordBearer",
        "APIKeyCookie",
    ],
)
def test_T1_shared_vocabulary_keeps_non_secret_names(name: str) -> None:
    assert not is_credential_field(name)


def test_T1_public_redaction_uses_the_same_suffix_vocabulary() -> None:
    assert redact(
        {
            "OPENAI_API_KEY": SECRET,
            "AZURE_OPENAI_KEY": SECRET,
            "max_tokens": 4096,
            "HTTPBearer": [],
            "eos_token": "</s>",
        },
        None,
    ) == {
        "OPENAI_API_KEY": "[REDACTED]",
        "AZURE_OPENAI_KEY": "[REDACTED]",
        "max_tokens": 4096,
        "HTTPBearer": [],
        "eos_token": "</s>",
    }


def test_T1_published_openapi_flags_only_the_session_token_property() -> None:
    flagged, pending = set(), [PUBLISHED_OPENAPI]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            flagged.update(key for key in item if is_credential_field(key))
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    # PracticeSession.token was already redacted by the original five-name vocabulary.
    assert flagged == {"token"}
