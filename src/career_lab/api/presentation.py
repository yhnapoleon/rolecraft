"""Response-only metadata and learner visibility; persisted evidence stays unchanged."""


def learner_state(store, session_id, state=None):
    state = state if state is not None else store.get_state(session_id)
    result = state.model_dump(mode="json")
    visible = {
        (m.id, m.version) for m in store.get_spec(session_id).materials if "learner" in m.visible_to
    }
    for field in ("material_versions", "indexed_versions"):
        result[field] = {
            key: version for key, version in result[field].items() if (key, version) in visible
        }
    return result


def object_response(store, session_id, record):
    result = {**record, "created_at": store.object_created_at(session_id, record["id"])}
    if "as_of_seq" not in result:
        result["as_of_seq"] = next(
            (
                event.before_version
                for event in store.events(session_id)
                if event.payload.get("object_id") == record["id"]
            ),
            None,
        )
    return result


def object_list(store, session_id, kind):
    records = [
        object_response(store, session_id, record)
        for record in store.list_objects(session_id, kind)
    ]
    return sorted(
        records,
        key=lambda record: (
            record["as_of_seq"] if record["as_of_seq"] is not None else -1,
            record["created_at"] or "",
            record["id"],
        ),
    )
