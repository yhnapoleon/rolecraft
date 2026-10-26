"""Public counts: running a case is separate from judging its answer."""

ROUTES = ("deterministic", "retrieval_generation", "agent_confirmation", "human")


def summarize(rows, assessments):
    def count(items):
        completed = [r for r in items if r["status"] == "completed"]
        judged = [
            r for r in completed if assessments.get(r["id"]) in {"satisfied", "not_satisfied"}
        ]
        satisfied = sum(assessments.get(r["id"]) == "satisfied" for r in judged)
        unsupported = sum(r["status"] == "unsupported" for r in items)
        runnable = len(items) - unsupported
        return {
            "total": len(items),
            "runnable": runnable,
            "completed": len(completed),
            "assessed": len(judged),
            "satisfied": satisfied,
            "unknown": len(completed) - len(judged),
            "unsupported": unsupported,
            "execution_failed": sum(r["status"] == "execution_failed" for r in items),
            "completion_rate": len(completed) / runnable if runnable else None,
            "assessment_rate": len(judged) / len(completed) if completed else None,
            "satisfaction_rate": satisfied / len(judged) if judged else None,
            "judge": "learner_assessment",
        }

    return {
        "all": count(rows),
        **{route: count([r for r in rows if r["route"] == route]) for route in ROUTES},
    }
