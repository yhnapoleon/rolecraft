from pathlib import Path

from career_lab.contracts.evaluation import JudgeDecision
from career_lab.datasets.release import build_release
from career_lab.evals.runner import RunnerConfig, run_eval


class Candidate:
    revision = "constant-v1"

    def __init__(self):
        self.calls = 0

    def judge(self, item):
        self.calls += 1
        return JudgeDecision(
            label="SUPPORTED",
            evidence_ids=["e1"],
            reason_code="constant",
            explanation="test",
            model_revision=self.revision,
        )


def test_resume_and_replicate(tmp_path):
    manifest = build_release(tmp_path / "data")
    config = RunnerConfig(
        suite="smoke",
        dataset_manifest=str(manifest),
        candidate="constant-v1",
        prompt_version="v1",
        input_mode="oracle",
        decode={},
        seeds=[0],
        concurrency=1,
        output_dir=str(tmp_path / "runs"),
    )
    model = Candidate()
    first = run_eval(config, model)
    assert model.calls == 30
    run_eval(config, model)
    assert model.calls == 30
    run_eval(config.model_copy(update={"replicate_id": "new"}), model)
    assert model.calls == 60
    assert Path(first.manifest_path).exists()
