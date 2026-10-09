from career_lab.errors import CodedValueError, InternalFailure
from career_lab.rubrics.feedback import build_feedback
from career_lab.storage.sessions import SessionStore, digest


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


def read_evidence(
    store: SessionStore,
    session_id: str,
    submission_id: str,
    criterion_id: str,
    evidence_id: str,
) -> dict[str, object]:
    report = saved_feedback(store, session_id, submission_id)
    try:
        sources = report["sources"]
    except KeyError as error:
        raise InternalFailure("invalid persisted feedback") from error
    if not isinstance(sources, dict):
        raise TypeError("invalid persisted feedback sources")
    if criterion_id not in sources:
        raise KeyError(criterion_id)
    criterion = sources[criterion_id]
    if not isinstance(criterion, dict):
        raise TypeError("invalid persisted criterion sources")
    if evidence_id not in criterion:
        raise KeyError(evidence_id)
    ref = criterion[evidence_id]
    try:
        seq, as_of_seq = ref["observed_at_seq"], report["as_of_seq"]
    except KeyError as error:
        raise InternalFailure("invalid persisted evidence coordinates") from error
    if seq > as_of_seq:
        raise CodedValueError("future evidence rejected")
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
