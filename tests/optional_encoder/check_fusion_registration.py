"""FUS-01 prediction side: a linear return fused with a CPU micro-BERT encoder return.

Explicit optional check (needs ``uv sync --locked --extra encoder``); the filename keeps it
outside default pytest discovery. The encoder is 146's tiny v3 return: a locally randomly
initialised BERT given one optimisation step on synthetic examples; no download, no
quality claim.
"""

import json
import socket
from pathlib import Path

import numpy as np
import pytest
import torch

from career_lab.contracts.v2.core import FileRef
from career_lab.models.v3 import registry_cli
from career_lab.models.v3.registry import load_registration
from tests.optional_encoder.tiny_return import tiny_encoder_return
from tests.support.linear_return import selection_record, write_linear_return
from tests.unit.test_w08_models import examples

DATASET = {"dataset_id": "rolecraft-synthetic-fusion-check", "dataset_manifest_sha256": "f" * 64}


def cli(capsys: pytest.CaptureFixture[str], *argv: object) -> dict:
    code = registry_cli.main([str(value) for value in argv])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0, out
    return out


def registration_args(registration: dict) -> list[object]:
    return [
        "--registration-path",
        registration["path"],
        "--registration-hash",
        registration["sha256"],
    ]


def encoder_registration(tmp_path: Path, capsys, registry: Path) -> dict:
    checkpoint = tmp_path / "checkpoint"
    returned = tiny_encoder_return(checkpoint, variant="pair", dataset=DATASET)
    out = cli(
        capsys,
        "register",
        "--registry",
        registry,
        "--bundle-root",
        checkpoint,
        "--bundle-path",
        returned.path,
        "--bundle-hash",
        returned.sha256,
        "--scope",
        "synthetic_fixture",
    )
    return out["registration"]


def test_fus_01_linear_and_micro_bert_fusion_loads_and_predicts_on_cpu(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("optional fusion mechanism check must remain offline")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    torch.set_num_threads(1)
    registry = tmp_path / "registry"
    encoder = encoder_registration(tmp_path, capsys, registry)
    linear_root = tmp_path / "linear"
    linear_ref = write_linear_return(
        linear_root,
        dataset_id=DATASET["dataset_id"],
        dataset_sha=DATASET["dataset_manifest_sha256"],
    )
    linear = cli(
        capsys,
        "register",
        "--registry",
        registry,
        "--bundle-root",
        linear_root,
        "--bundle-path",
        linear_ref.path,
        "--bundle-hash",
        linear_ref.sha256,
        "--scope",
        "synthetic_fixture",
    )["registration"]
    left = cli(capsys, "describe", "--registry", registry, *registration_args(linear))
    right = cli(capsys, "describe", "--registry", registry, *registration_args(encoder))
    assert right["kind"] == "huggingface_encoder"
    assert right["dataset"]["dataset_manifest_sha256"] == left["dataset"]["dataset_manifest_sha256"]
    selection = tmp_path / "fusion-selection.json"
    selection.write_text(json.dumps(selection_record(left, right, alpha=0.25, threshold=0.5)))
    fusion = cli(
        capsys,
        "register-fusion",
        "--registry",
        registry,
        "--left-path",
        linear["path"],
        "--left-hash",
        linear["sha256"],
        "--right-path",
        encoder["path"],
        "--right-hash",
        encoder["sha256"],
        "--selection",
        selection,
        "--scope",
        "synthetic_fixture",
    )["registration"]
    identity = cli(capsys, "describe", "--registry", registry, *registration_args(fusion))
    assert [c["kind"] for c in identity["components"]] == ["linear", "huggingface_encoder"]
    item = examples("dev")[0].item
    (tmp_path / "item.json").write_text(item.model_dump_json())

    def predict(registration: dict, request: str) -> dict:
        return cli(
            capsys,
            "predict",
            "--registry",
            registry,
            *registration_args(registration),
            "--journal",
            tmp_path / "journal",
            "--request-id",
            request,
            "--input",
            tmp_path / "item.json",
            "--language",
            "en",
            "--allow-synthetic",
        )["prediction"]

    a, b, fused = predict(linear, "linear"), predict(encoder, "encoder"), predict(fusion, "fused")
    assert fused["status"] == "ok" and fused["model_revision"] == identity["model_revision"]
    expected = 0.75 * np.array(a["probabilities"]) + 0.25 * np.array(b["probabilities"])
    assert np.allclose(fused["probabilities"], expected, rtol=0, atol=1e-9)
    model, _ = load_registration(registry, FileRef.model_validate(fusion))
    size = model.measure(item)
    assert size.limit == 256 and size.tokens is not None
