"""SMOKE-01..03: real XLM-R base weights through the receiving end (explicit optional check).

Needs the encoder extra and the downloaded ``FacebookAI/xlm-roberta-base`` directory, named
by ``ROLECRAFT_XLMR_DIR`` (``<root>/<40-hex revision>``). It is not collected by the
default gate; when it is run without the directory it fails rather than skipping.
Heads are untrained: this checks loading, splitting, token measurement and abstention,
never model quality.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    model = Path(os.environ.get("ROLECRAFT_XLMR_DIR", ""))
    assert (model / "model.safetensors").is_file(), "set ROLECRAFT_XLMR_DIR to the download"
    out = tmp_path_factory.mktemp("xlmr") / "smoke"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.smoke.xlmr_base",
            "--model-dir",
            str(model),
            "--revision",
            model.name,
            "--out",
            str(out),
            "--variants",
            "pair",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((out / "report.json").read_text())


def test_smoke_01_real_weights_load_as_untrained_synthetic_registration(report: dict) -> None:
    pair = report["variants"]["pair"]
    assert pair["scope"] == "synthetic_fixture"
    assert pair["weights_stage"] == "pretrained_untrained_heads"
    assert pair["kind"] == "huggingface_encoder"
    assert pair["max_tokens"] == 512
    assert pair["load_seconds"] > 0 and pair["peak_rss_mb_after"] > 500


def test_smoke_02_sentences_are_measured_with_the_real_tokenizer_in_both_languages(
    report: dict,
) -> None:
    works = report["variants"]["pair"]["works"]
    assert {row["language"] for row in works} == {"zh", "en"}
    for row in works:
        assert row["sentences"] >= 4
        # One measured journal entry per sentence; real subword counts, not characters.
        assert row["tokens"]["count"] == row["sentences"]
        assert row["tokens"]["min"] > 8
        assert (
            row["second_same_units"] and row["second_review_journal_sentences"] == row["sentences"]
        )


def test_smoke_03_sentences_over_the_limit_abstain_and_the_rest_are_judged(report: dict) -> None:
    works = report["variants"]["pair"]["works"]
    for row in works:
        over = sum(value > 512 for value in row["token_values"])
        assert row["over_limit"] == over
        assert row["unit_statuses"].count("abstained") >= over
        if over == row["sentences"]:
            # Nothing judged: stated plainly, never shown as a model judgement.
            assert (row["status"], row["error_code"]) == ("unavailable", "all_units_abstained")
        else:
            assert row["status"] == "synthetic_mechanism_only"
    # Whole cited materials push sentence inputs past 512 tokens; one quoted fragment does not.
    assert any(row["over_limit"] for row in works if row["citation"] == "whole")
    assert not any(row["over_limit"] for row in works if row["citation"] == "fragments")
    assert report["max_units"]["max_units_now"] == 24
