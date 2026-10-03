import numpy as np

from career_lab.datasets.release import build_release
from career_lab.models.training import train_baselines, load_candidate, load_partition


def test_training_probability_order_and_train_only_preprocessing(tmp_path, monkeypatch):
    manifest = build_release(tmp_path / "data")
    from pathlib import Path
    original_text, original_bytes = Path.read_text, Path.read_bytes
    def guard_text(path, *args, **kwargs):
        assert not (path.parent.name == "gold" and path.name == "test.jsonl"), "trainer read test gold"
        return original_text(path, *args, **kwargs)
    def guard_bytes(path, *args, **kwargs):
        assert not (path.parent.name == "gold" and path.name == "test.jsonl"), "trainer read test gold"
        return original_bytes(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guard_text)
    monkeypatch.setattr(Path, "read_bytes", guard_bytes)
    result = train_baselines(manifest, tmp_path / "models")
    inputs, labels = load_partition(manifest, "dev")
    for name in ("linear", "encoder", "ensemble"):
        model = load_candidate(result[name])
        probabilities = model.predict_proba(inputs)
        assert probabilities.shape == (30, 3)
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)
        assert model.labels == ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
    linear = load_candidate(result["linear"])
    assert "索引" not in linear.vectorizer.vocabulary_
    assert result["selection_split"] == "dev"
