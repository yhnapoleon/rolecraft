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
    suffix, media, content = REJECTED[case]
    result, registry, _ = register_config(tmp_path, suffix, content, media)
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    for marker in (SECRET, BASIC_SECRET):
        assert marker not in result.stdout + result.stderr
        assert all(
            marker.encode() not in file.read_bytes()
            for file in registry.rglob("*")
            if file.is_file()
        )


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
    ],
)
def test_T1_shared_vocabulary_matches_credential_name_suffixes(name: str) -> None:
    assert is_credential_field(name)


@pytest.mark.parametrize("name", [*ALLOWED_FIELDS, "idempotency_key", "token_limit"])
def test_T1_shared_vocabulary_keeps_non_secret_names(name: str) -> None:
    assert not is_credential_field(name)


def test_T1_public_redaction_uses_the_same_suffix_vocabulary() -> None:
    assert redact({"OPENAI_API_KEY": SECRET, "max_tokens": 4096}, None) == {
        "OPENAI_API_KEY": "[REDACTED]",
        "max_tokens": 4096,
    }
