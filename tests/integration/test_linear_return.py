"""LIN-01..04, LIN-06 and RT-01 through the registry CLI and normal feedback.

Every registration here is synthetic_fixture mechanism evidence: constructed weights or
weights fitted on in-repo synthetic examples. No model quality claim.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier

from career_lab.contracts.v2.core import digest
from career_lab.models.v3 import registry_cli
from career_lab.models.v3.core import INPUT
from career_lab.models.v3.linear import pair_text, text
from career_lab.contracts.v2.core import FileRef
from tests.support.linear_return import (
    DELETE,
    LABELS,
    MECHANISM_DATASET,
    VOCABULARY,
    constructed_model,
    feedback_report,
    golden_rows,
    json_bytes,
    reference_module,
    sha,
    text_sha,
    write_linear_return,
)
from tests.unit.test_w08_models import examples

# The twelve model inputs of the frozen fixture-20261007-v2 package (train then dev).
FIXTURE_V2_INPUT_HASHES = {
    "982e1c0c76cc364d2809a0ed7707d634616bfcc5ee6e2cf52445f8611d93361f",
    "e613f2a94b4fcb60a67d22cd89a55f200b55167afa4d38ab37953847f0d6bf26",
    "6b562221cb641ff623d7a6103ee5640bb13e9820bdc459e38e951dd9a719dc0d",
    "136410d28814bf2c8f908904e82743407379923a1724e1d512b0b357bca01018",
    "8da94ffd320eb768b6bbfb14b9bd74fd951b5e6fcde65a9100ce9e74c6844712",
    "69b7066d10e6f3ab569294cb89bf9aebc339f668313d6e366df0fd571689bd76",
    "d11512cab5fe2b8430ff62395bc4aed6fc537907c80bf0d609d15d648b9161fd",
    "b570b828b986cc42d38be553c451e843edaa7ccd917327f90cbe1e6addd9e70c",
    "80ed26e73a4d2225a69ada6b54bf129584916ddc4ec9201f042e5a3f65fdf643",
    "a368573a7dcc46f30671397ceaf72ae64bf576b1a7b785a4c479bedae7b17bed",
    "029d48ddeaf6d853c309222a193fbf2a88e1217b7acf7dba7e4532749c315a31",
    "f35df2624549d62d1e4d9d2986eb9036606403dad6088b77d718b6d8b4e35608",
}


def test_lin_03_golden_vectors_cover_fixture_v2_and_both_languages() -> None:
    rows = golden_rows()
    fixture = {row["input_hash"] for row in rows if row["source"] == "fixture-20261007-v2"}
    assert fixture == FIXTURE_V2_INPUT_HASHES
    synthetic = [row for row in rows if row["source"] == "synthetic"]
    assert {row["language"] for row in synthetic} == {"zh", "en"}
    assert len({row["input_hash"] for row in rows}) == len(rows)


def test_lin_03_product_and_reference_feature_text_match_every_golden_vector() -> None:
    reference = reference_module("linear_text_v1")
    for row in golden_rows():
        model_input = row["model_input"]
        assert digest(model_input) == row["input_hash"], row["sample"]
        item = INPUT.validate_python(model_input)
        candidates = item.evidence.candidate_evidence
        raw_candidates = model_input["evidence"]["candidate_evidence"]
        assert text_sha(text(item)) == row["relation_text_sha256"], row["sample"]
        assert text_sha(reference.relation_text(model_input)) == row["relation_text_sha256"]
        assert {c.id: text_sha(pair_text(item, c)) for c in candidates} == row["pair_text_sha256"]
        assert {
            c["id"]: text_sha(reference.pair_text(model_input, c)) for c in raw_candidates
        } == row["pair_text_sha256"], row["sample"]


def test_lin_03_reference_text_follows_the_published_template_literally() -> None:
    reference = reference_module("linear_text_v1")
    row = next(r for r in golden_rows() if r["sample"] == "synthetic-zh-open-validity")
    model_input = row["model_input"]
    first = model_input["evidence"]["candidate_evidence"][0]
    assert reference.relation_text(model_input) == (
        "探索\n"
        "试点版本是 2\n"
        "reference time 2; temporal scope known\n"
        '{"版本": 2}\n'
        "observed 1; valid from 0; valid until open\n"
        "会议记录：版本尚未确认\n"
        "observed 1; valid from 0; valid until 3"
    )
    assert reference.pair_text(model_input, first) == (
        "试点版本是 2\n"
        "reference time 2; temporal scope known\n"
        "[EVIDENCE]\n"
        '{"版本": 2}\n'
        "observed 1; valid from 0; valid until open"
    )


def cli(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, dict]:
    code = registry_cli.main([str(value) for value in argv])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def register(capsys, registry: Path, root: Path, ref, scope="synthetic_fixture"):
    return cli(
        capsys,
        "register",
        "--registry",
        registry,
        "--bundle-root",
        root,
        "--bundle-path",
        ref.path,
        "--bundle-hash",
        ref.sha256,
        "--scope",
        scope,
    )


def sample(name: str) -> dict:
    return next(row for row in golden_rows() if row["sample"] == name)["model_input"]


LANGUAGE_SAMPLES = {"zh": "synthetic-zh-open-validity", "en": "synthetic-en-capacity"}


def expected_prediction(model_input: dict) -> tuple[np.ndarray, list[str]]:
    """Independent oracle: reference text, raw sklearn counts and NumPy TF-IDF arithmetic."""
    reference = reference_module("linear_text_v1")
    _, arrays = constructed_model()
    counts = CountVectorizer(analyzer="char", ngram_range=(1, 2), vocabulary=VOCABULARY)

    def features(value: str) -> np.ndarray:
        row = counts.transform([value]).toarray()[0] * arrays["idf"]
        norm = np.linalg.norm(row)
        return row / norm if norm else row

    logits = features(reference.relation_text(model_input)) @ arrays["coef"].T + arrays["intercept"]
    probabilities = np.exp(logits - logits.max())
    probabilities /= probabilities.sum()
    selected = []
    for candidate in model_input["evidence"]["candidate_evidence"]:
        score = features(reference.pair_text(model_input, candidate)) @ arrays["evidence_coef"]
        if 1 / (1 + np.exp(-(score + arrays["evidence_intercept"][0]))) >= 0.5:
            selected.append(candidate["id"])
    return probabilities, selected


@pytest.mark.parametrize("language", ["zh", "en"])
def test_lin_01_valid_linear_return_registers_describes_and_predicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], language: str
) -> None:
    root, registry = tmp_path / "return", tmp_path / "registry"
    ref = write_linear_return(root, label_tiers=["G0"])
    revision = json.loads((root / ref.path).read_bytes())["model_revision"]
    code, out = register(capsys, registry, root, ref)
    assert code == 0, out
    registration = out["registration"]
    assert registration["path"].startswith("linear-")
    assert out["quality_validated"] is False and out["training_performed"] is False
    code, identity = cli(
        capsys,
        "describe",
        "--registry",
        registry,
        "--registration-path",
        registration["path"],
        "--registration-hash",
        registration["sha256"],
    )
    assert code == 0, identity
    assert identity == {
        "id": registration["path"].split("/")[0],
        "model_revision": revision,
        "scope": "synthetic_fixture",
        "quality_validated": False,
        "kind": "linear",
        "dataset": {
            "dataset_id": MECHANISM_DATASET,
            "dataset_manifest_sha256": "d" * 64,
            "label_tiers": ["G0"],
        },
    }
    model_input = sample(LANGUAGE_SAMPLES[language])
    item = tmp_path / "item.json"
    item.write_text(json.dumps(model_input, ensure_ascii=False))
    code, result = cli(
        capsys,
        "predict",
        "--registry",
        registry,
        "--registration-path",
        registration["path"],
        "--registration-hash",
        registration["sha256"],
        "--journal",
        tmp_path / "journal",
        "--request-id",
        "lin-01-" + language,
        "--input",
        item,
        "--language",
        language,
        "--allow-synthetic",
    )
    assert code == 0, result
    assert result["status"] == "completed"
    assert result["semantic_status"] == "synthetic_mechanism_only"
    assert result["affects_score"] is False and result["quality_validated"] is False
    prediction = result["prediction"]
    probabilities, selected = expected_prediction(model_input)
    assert prediction["status"] == "ok" and prediction["model_revision"] == revision
    assert np.allclose(prediction["probabilities"], probabilities, rtol=0, atol=1e-12)
    assert (
        prediction["label"]
        == ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"][int(np.argmax(probabilities))]
    )
    assert prediction["evidence_ids"] == selected
    assert result["public_prediction"]["status"] == "unavailable"


def vectorizer(**changes: object) -> dict:
    value = dict(constructed_model()[0]["vectorizer"])
    value.update(changes)
    return value


def head(**changes: object) -> dict:
    return {"kind": "pair_logistic", "vectorizer": "shared", "threshold": 0.5} | changes


LIN_02_CASES = {
    "manifest_label_order": (
        {"manifest": {"label_order": LABELS[::-1]}},
        "model_return_task_or_labels_invalid",
    ),
    "criterion_task_domain": (
        {"manifest": {"task_type": "criterion"}},
        "model_return_task_or_labels_invalid",
    ),
    "classifier_label_order": (
        {"model": {"classifier": {"kind": "multinomial_logistic", "label_order": LABELS[::-1]}}},
        "linear_return_labels_invalid",
    ),
    "one_vs_rest_classifier": (
        {"model": {"classifier": {"kind": "one_vs_rest_logistic", "label_order": LABELS}}},
        "linear_return_labels_invalid",
    ),
    "coef_shape": ({"arrays": {"coef": np.zeros((3, 5))}}, "linear_return_array_shape_invalid"),
    "evidence_coef_shape": (
        {"arrays": {"evidence_coef": np.zeros(4)}},
        "linear_return_array_shape_invalid",
    ),
    "missing_idf": ({"arrays": {"idf": DELETE}}, "linear_return_arrays_invalid"),
    "pickled_object_array": (
        {"arrays": {"coef": np.array([{"code": "anything"}], dtype=object)}},
        "linear_return_arrays_invalid",
    ),
    "nonfinite_weights": (
        {"arrays": {"intercept": np.array([0.0, np.nan, 0.0])}},
        "linear_return_array_values_invalid",
    ),
    "custom_analyzer": (
        {"model": {"vectorizer": vectorizer(analyzer="my_package.tokenize:analyzer")}},
        "linear_vectorizer_unsupported",
    ),
    "callable_tokenizer": (
        {"model": {"vectorizer": vectorizer(tokenizer="my_package.tokenize")}},
        "linear_vectorizer_unsupported",
    ),
    "non_default_token_pattern": (
        {"model": {"vectorizer": vectorizer(token_pattern=r"\S+")}},
        "linear_vectorizer_unsupported",
    ),
    "vocabulary_index_gap": (
        {"model": {"vectorizer": vectorizer(vocabulary={"2": 0, "1": 2})}},
        "linear_vocabulary_invalid",
    ),
    "missing_evidence_head": (
        {"model": {"evidence_head": DELETE}},
        "linear_return_evidence_head_required",
    ),
    "evidence_head_kind": (
        {"model": {"evidence_head": head(kind="pooled_attention")}},
        "linear_evidence_head_unsupported",
    ),
    "evidence_threshold_range": (
        {"model": {"evidence_head": head(threshold=1.5)}},
        "linear_evidence_head_unsupported",
    ),
    "text_template": (
        {"model": {"text_template": "producer-custom-text"}},
        "linear_text_template_unsupported",
    ),
    "unknown_model_field": ({"model": {"pickle": "model.pkl"}}, "linear_return_model_invalid"),
    "model_revision": (
        {"manifest": {"model_revision": "linear-return:" + "0" * 64}},
        "linear_return_revision_mismatch",
    ),
    "member_set": (
        {
            "manifest": {
                "checkpoint_files": {
                    "linear/model.json": "0" * 64,
                    "linear/arrays.npz": "0" * 64,
                    "linear/vectorizer.pkl": "0" * 64,
                }
            }
        },
        "linear_return_member_set_mismatch",
    ),
    "artifact_protocol": (
        {"manifest": {"artifact_protocol": "rolecraft-linear-return-v0"}},
        "linear_return_protocol_invalid",
    ),
    "label_tiers": ({"label_tiers": ["G0", "human-gold"]}, "linear_return_label_tiers_invalid"),
    "incomplete_declaration": ({"manifest": {"completed": False}}, "model_return_incomplete"),
}


@pytest.mark.parametrize("case", sorted(LIN_02_CASES))
def test_lin_02_malformed_linear_returns_are_refused_before_registration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    changes, expected = LIN_02_CASES[case]
    root, registry = tmp_path / "return", tmp_path / "registry"
    ref = write_linear_return(root, **changes)
    code, out = register(capsys, registry, root, ref)
    assert (code, out["error"]) == (2, expected)
    assert out["quality_validated"] is False
    assert not list(registry.glob("linear-*"))


FIXTURE_V2_MANIFEST = "5c8f0d5be05e3b39c1599e7fd3a92e46e413dc571248c59f827818f5ee231858"


@pytest.mark.parametrize(
    "dataset",
    [
        {"dataset_id": "rolecraft-fixture-20261007-v2", "dataset_sha": FIXTURE_V2_MANIFEST},
        {"dataset_id": "renamed-handoff", "dataset_sha": FIXTURE_V2_MANIFEST},
        {"dataset_id": "Team-FIXTURE-relations", "dataset_sha": "e" * 64},
    ],
    ids=["fixture_v2", "fixture_v2_renamed", "fixture_named"],
)
def test_lin_06_fixture_data_cannot_be_registered_as_external(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], dataset: dict
) -> None:
    root, registry = tmp_path / "return", tmp_path / "registry"
    ref = write_linear_return(root, **dataset)
    code, out = register(capsys, registry, root, ref, scope="external_candidate")
    assert (code, out["error"]) == (2, "fixture_cannot_be_registered_as_external")
    assert not list(registry.glob("linear-*"))
    code, out = register(capsys, registry, root, ref, scope="synthetic_fixture")
    assert code == 0, out


def test_lin_06_external_candidate_needs_non_fixture_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, registry = tmp_path / "return", tmp_path / "registry"
    ref = write_linear_return(root, dataset_id="team-relations-2026", dataset_sha="e" * 64)
    code, out = register(capsys, registry, root, ref, scope="external_candidate")
    assert code == 0, out
    registration = out["registration"]
    code, identity = cli(
        capsys,
        "describe",
        "--registry",
        registry,
        "--registration-path",
        registration["path"],
        "--registration-hash",
        registration["sha256"],
    )
    assert identity["scope"] == "external_candidate"
    assert identity["quality_validated"] is False


def fitted_mechanism(evidence: str) -> dict:
    """Fit sklearn objects on in-repo synthetic fixture examples (mechanism sample only)."""
    reference = reference_module("linear_text_v1")
    rows = examples("train", 2)
    inputs = [row.item.model_dump(mode="json") for row in rows]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), sublinear_tf=True)
    features = vectorizer.fit_transform([reference.relation_text(item) for item in inputs])
    classifier = LogisticRegression(max_iter=500, random_state=5002).fit(
        features, [row.annotation.final.label for row in rows]
    )
    pairs, gold = [], []
    for row, item in zip(rows, inputs, strict=True):
        for candidate in item["evidence"]["candidate_evidence"]:
            pairs.append(reference.pair_text(item, candidate))
            gold.append(int(candidate["id"] in row.annotation.final.evidence_ids))
    evidence_vectorizer = None
    if evidence == "independent_word_no_idf":
        evidence_vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), use_idf=False)
        pair_features = evidence_vectorizer.fit_transform(pairs)
    else:
        pair_features = vectorizer.transform(pairs)
    evidence_classifier = LogisticRegression(max_iter=500, random_state=5002).fit(
        pair_features, gold
    )
    return {
        "vectorizer": vectorizer,
        "classifier": classifier,
        "evidence_classifier": evidence_classifier,
        "evidence_vectorizer": evidence_vectorizer,
    }


def dev_inputs(path: Path) -> list[dict]:
    """Synthetic dev records, the fixture v2 inputs and the bilingual golden samples."""
    records = [
        {
            "record_id": row.record_id,
            "input_hash": digest(row.item),
            "model_input": row.item.model_dump(mode="json"),
        }
        for row in examples("dev", 2)
    ] + [
        {
            "record_id": row["sample"],
            "input_hash": row["input_hash"],
            "model_input": row["model_input"],
        }
        for row in golden_rows()
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    return records


def mechanism_dataset(path: Path) -> str:
    raw = json_bytes(
        {
            "dataset_id": MECHANISM_DATASET,
            "schema_version": 1,
            "status": "FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA",
            "task_type": "relation",
            "label_order": LABELS,
            "splits": {"train": {"records": 6, "label_tiers": {"G0": 6}}},
        }
    )
    path.write_bytes(raw)
    return sha(raw)


@pytest.mark.parametrize("evidence", ["shared_char_wb", "independent_word_no_idf"])
def test_lin_04_export_script_round_trips_through_registration_and_prediction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], evidence: str
) -> None:
    exporter = reference_module("export_sklearn_linear")
    records = dev_inputs(tmp_path / "dev.inputs.jsonl")
    dataset_sha = mechanism_dataset(tmp_path / "dataset-manifest.json")
    target = tmp_path / "return"
    result = exporter.export_linear_return(
        target,
        **fitted_mechanism(evidence),
        evidence_threshold=0.5,
        dataset_manifest=tmp_path / "dataset-manifest.json",
        dev_inputs=tmp_path / "dev.inputs.jsonl",
        training_notes_file="notes.md",
        training={"seed": 5002, "scope": "mechanism sample fitted on synthetic fixture"},
    )
    manifest = json.loads((target / "checkpoint-manifest.json").read_bytes())
    assert manifest["artifact_kind"] == "linear"
    assert manifest["dataset_manifest_sha256"] == dataset_sha
    assert manifest["label_tiers"] == ["G0"]
    assert manifest["model_revision"] == result["model_revision"]
    exported = {
        row["record_id"]: row
        for row in map(json.loads, (target / "predictions.dev.jsonl").read_text().splitlines())
    }
    assert set(exported) == {r["record_id"] for r in records}
    assert {row["status"] for row in exported.values()} == {"ok", "abstained"}
    ref = {"path": "checkpoint-manifest.json", "sha256": result["manifest_sha256"]}
    code, out = cli(
        capsys,
        "register",
        "--registry",
        tmp_path / "registry",
        "--bundle-root",
        target,
        "--bundle-path",
        ref["path"],
        "--bundle-hash",
        ref["sha256"],
        "--scope",
        "synthetic_fixture",
    )
    assert code == 0, out
    registration = out["registration"]
    worst = 0.0
    for index, record in enumerate(records):
        item = tmp_path / f"item-{index}.json"
        item.write_text(json.dumps(record["model_input"], ensure_ascii=False))
        code, outcome = cli(
            capsys,
            "predict",
            "--registry",
            tmp_path / "registry",
            "--registration-path",
            registration["path"],
            "--registration-hash",
            registration["sha256"],
            "--journal",
            tmp_path / "journal",
            "--request-id",
            f"lin-04-{index}",
            "--input",
            item,
            "--language",
            "en",
            "--allow-synthetic",
        )
        assert code == 0, outcome
        product, producer = outcome["prediction"], exported[record["record_id"]]
        assert product["model_revision"] == producer["model_revision"] == result["model_revision"]
        assert product["input_hash"] == producer["input_hash"]
        assert product["status"] == producer["status"], record["record_id"]
        assert product["label"] == producer["label"], record["record_id"]
        assert set(product["evidence_ids"]) == set(producer["evidence_ids"]), record["record_id"]
        if producer["status"] == "ok":
            difference = np.abs(np.subtract(product["probabilities"], producer["probabilities"]))
            worst = max(worst, float(difference.max()))
        else:
            assert product["reason_code"] == producer["reason"]
    assert worst <= 1e-6


def one_vs_rest(objects: dict) -> dict:
    rows = examples("train", 2)
    reference = reference_module("linear_text_v1")
    texts = [reference.relation_text(row.item.model_dump(mode="json")) for row in rows]
    sgd = SGDClassifier(loss="log_loss", random_state=5002).fit(
        objects["vectorizer"].transform(texts), [row.annotation.final.label for row in rows]
    )
    return objects | {"classifier": sgd}


LIN_04_REFUSALS = {
    "one_vs_rest_probabilities": (one_vs_rest, "multinomial softmax"),
    "callable_analyzer": (
        lambda o: o | {"vectorizer": TfidfVectorizer(analyzer=str.split).fit(["a b"])},
        "built-in",
    ),
    "accent_stripping": (
        lambda o: o | {"vectorizer": TfidfVectorizer(strip_accents="unicode").fit(["alpha beta"])},
        "strip_accents",
    ),
}


@pytest.mark.parametrize("case", sorted(LIN_04_REFUSALS))
def test_lin_04_export_script_refuses_objects_the_loader_cannot_rebuild(
    tmp_path: Path, case: str
) -> None:
    exporter = reference_module("export_sklearn_linear")
    dev_inputs(tmp_path / "dev.inputs.jsonl")
    mechanism_dataset(tmp_path / "dataset-manifest.json")
    change, message = LIN_04_REFUSALS[case]
    with pytest.raises(exporter.ExportError, match=message):
        exporter.export_linear_return(
            tmp_path / "return",
            **change(fitted_mechanism("shared_char_wb")),
            dataset_manifest=tmp_path / "dataset-manifest.json",
            dev_inputs=tmp_path / "dev.inputs.jsonl",
            training_notes_file="notes.md",
        )
    assert not (tmp_path / "return").exists()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_lin_01_normal_feedback_names_the_linear_model_and_its_training_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    root = tmp_path / "return"
    ref = write_linear_return(root, label_tiers=["G0", "G2v"])
    code, out = register(capsys, tmp_path / "registry", root, ref)
    assert code == 0, out
    registration = FileRef.model_validate(out["registration"])
    report = feedback_report(tmp_path, monkeypatch, language, tmp_path / "registry", registration)
    (advice,) = report["model_advice"]
    assert advice["criterion"] == "R2.support"
    assert advice["status"] == "synthetic_mechanism_only"
    assert advice["affects_score"] is False
    identity = advice["registration"]
    assert identity["id"] == registration.path.split("/")[0]
    assert identity["kind"] == "linear" and identity["scope"] == "synthetic_fixture"
    assert identity["dataset"] == {
        "dataset_id": MECHANISM_DATASET,
        "dataset_manifest_sha256": "d" * 64,
        "label_tiers": ["G0", "G2v"],
    }
    assert identity["quality_validated"] is False
    assert report["provenance"]["registered_model"] == identity
    assert all(item["source"] != "model_advice" for item in report["items"])


def copied_source(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A private copy of the installed product source, imported ahead of the checkout."""
    source = Path(registry_cli.__file__).resolve().parents[3] / "career_lab"
    target = tmp_path / "src/career_lab"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return target, env


def run_cli(env: dict[str, str], *argv: object) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, "-m", "career_lab.models.v3.registry_cli", *map(str, argv)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout.strip().splitlines()[-1])


def test_rt_01_only_inference_closure_changes_invalidate_a_registration(tmp_path: Path) -> None:
    source, env = copied_source(tmp_path)
    imported = subprocess.run(
        [sys.executable, "-c", "import career_lab; print(career_lab.__file__)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(imported).resolve().is_relative_to(source.resolve())
    root, registry = tmp_path / "return", tmp_path / "registry"
    ref = write_linear_return(root)
    code, out = run_cli(
        env,
        "register",
        "--registry",
        registry,
        "--bundle-root",
        root,
        "--bundle-path",
        ref.path,
        "--bundle-hash",
        ref.sha256,
        "--scope",
        "synthetic_fixture",
    )
    assert code == 0, out
    item = tmp_path / "item.json"
    item.write_text(json.dumps(sample("synthetic-en-capacity")))

    def predict(request: str) -> tuple[int, dict]:
        return run_cli(
            env,
            "predict",
            "--registry",
            registry,
            "--registration-path",
            out["registration"]["path"],
            "--registration-hash",
            out["registration"]["sha256"],
            "--journal",
            tmp_path / "journal",
            "--request-id",
            request,
            "--input",
            item,
            "--language",
            "en",
            "--allow-synthetic",
        )

    assert predict("before")[1]["status"] == "completed"
    for unrelated in ("api/app.py", "rubrics/v4/feedback.py", "contracts/v2/evaluation.py"):
        with (source / unrelated).open("a") as stream:
            stream.write("\n# RT-01: product change outside the inference closure\n")
    code, result = predict("after-unrelated")
    assert (code, result.get("status")) == (0, "completed"), result
    for closure in ("models/v3/linear.py", "contracts/v2/data.py"):
        with (source / closure).open("a") as stream:
            stream.write("\n# RT-01: inference closure change\n")
        code, result = predict("after-" + closure)
        assert (code, result["error"]) == (2, "registered_inference_runtime_changed"), closure
        (source / closure).write_bytes(
            (source / closure).read_bytes().replace(b"\n# RT-01: inference closure change\n", b"")
        )
    assert predict("restored")[1]["status"] == "completed"
