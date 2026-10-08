from pathlib import Path
import pytest
from career_lab.datasets.controlled import generate_controlled, build_controlled_release
from career_lab.models.training import train_baselines
from career_lab.experiments.study import run_development, freeze_study, run_confirmatory


def test_dev_does_not_read_test_and_freeze_is_required(tmp_path, monkeypatch):
    manifest = build_controlled_release(tmp_path / "data", generate_controlled(1))
    models = tmp_path / "models"
    train_baselines(manifest, models)
    output = tmp_path / "study"
    original_text, original_bytes = Path.read_text, Path.read_bytes

    def guard(fn):
        def wrapped(path, *args, **kwargs):
            assert not (
                path.parent.name in ("gold", "proofs", "splits") and path.name.startswith("test")
            ), "test read during development"
            return fn(path, *args, **kwargs)

        return wrapped

    monkeypatch.setattr(Path, "read_text", guard(original_text))
    monkeypatch.setattr(Path, "read_bytes", guard(original_bytes))
    report = run_development(manifest, models, output)
    assert set(report["e1"]) == {"constant", "linear", "encoder", "ensemble", "rules", "hybrid"}
    assert report["human_validation"] == "pending"
    assert report["e1"]["rules"]["per_class"]["SUPPORTED"]["support"] == 12
    assert report["e1"]["rules"]["metrics"]["accuracy"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="freeze"):
        run_confirmatory(output)
    monkeypatch.setattr(Path, "read_text", original_text)
    monkeypatch.setattr(Path, "read_bytes", original_bytes)
    freeze_study(manifest, models, output)
    final = run_confirmatory(output)
    assert final["split"] == "test" and not final["deployment"]["eligible"]
    assert run_confirmatory(output) == final


def test_freeze_rejects_wrong_dataset_and_changed_dev_predictions(tmp_path):
    from career_lab.datasets.release import build_release

    manifest = build_controlled_release(tmp_path / "data", generate_controlled(1))
    models = tmp_path / "models"
    train_baselines(manifest, models)
    output = tmp_path / "study"
    report = run_development(manifest, models, output)
    wrong = build_release(tmp_path / "wrong")
    with pytest.raises(ValueError, match="provenance"):
        freeze_study(wrong, models, output)
    predictions = Path(report["e1"]["linear"]["manifest_path"]).parent / "predictions.jsonl"
    predictions.write_text(predictions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        freeze_study(manifest, models, output)
