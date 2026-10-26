from career_lab.aipm.evaluation.summary import summarize


def test_quality_denominator_excludes_unsupported_failed_and_unjudged():
    rows = [
        {"id": "a", "status": "completed", "route": "retrieval_generation"},
        {"id": "b", "status": "completed", "route": "retrieval_generation"},
        {"id": "c", "status": "completed", "route": "retrieval_generation"},
        {"id": "d", "status": "execution_failed", "route": "retrieval_generation"},
        {"id": "e", "status": "unsupported", "route": "agent_confirmation"},
    ]
    result = summarize(rows, {"a": "satisfied", "b": "not_satisfied", "c": "unknown"})
    assert result["all"] == {
        "total": 5,
        "runnable": 4,
        "completed": 3,
        "assessed": 2,
        "satisfied": 1,
        "unknown": 1,
        "unsupported": 1,
        "execution_failed": 1,
        "completion_rate": 0.75,
        "assessment_rate": 2 / 3,
        "satisfaction_rate": 0.5,
        "judge": "learner_assessment",
    }
    assert result["agent_confirmation"]["satisfaction_rate"] is None
