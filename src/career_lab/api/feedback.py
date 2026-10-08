from career_lab.rubrics.feedback import build_feedback
from career_lab.storage.sessions import digest


def feedback_id(store, session_id, submission_id):
    sub = store.get_object(session_id, submission_id, "submission")
    return digest([session_id, submission_id, "feedback", sub["model_revision"]])


def saved_feedback(store, session_id, submission_id):
    return store.get_object(session_id, feedback_id(store, session_id, submission_id), "feedback")


def generate_feedback(store, session_id, submission_id):
    try:
        return saved_feedback(store, session_id, submission_id)
    except KeyError:
        report = build_feedback(store, session_id, submission_id)
        return store.save_derived(
            session_id, feedback_id(store, session_id, submission_id), "feedback", report
        )


def read_evidence(store, session_id, submission_id, criterion_id, evidence_id):
    report = saved_feedback(store, session_id, submission_id)
    ref = report["sources"][criterion_id][evidence_id]
    seq = ref["observed_at_seq"]
    if seq > report["as_of_seq"]:
        raise ValueError("future evidence rejected")
    kind = ref["kind"]
    if kind == "document":
        view = store.project_view(session_id, "learner", seq)
        material = next(
            m
            for m in view.permitted_materials
            if m.id == ref["object_id"] and m.version == ref["version"]
        )
        content = material.content
    elif kind == "config":
        content = store.get_state(session_id, seq).configs
    elif kind == "event":
        state = store.get_state(session_id, seq)
        content = {"resources": state.resources, "applied_rules": state.applied_rules}
    else:
        content = store.get_object(
            session_id, ref["object_id"], "test" if kind == "test_result" else "artifact"
        )
    return ref | {"content": content}
