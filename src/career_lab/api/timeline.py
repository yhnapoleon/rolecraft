def timeline(store, session_id):
    events = store.project_view(session_id, "learner").recent_events
    turns = store.list_objects(session_id, "turn")
    denials = store.list_objects(session_id, "approval_denied")
    return {
        "events": [
            {**e.model_dump(mode="json"), "created_at": store.event_created_at(session_id, e.seq)}
            for e in events
        ],
        "turns": [
            {
                **t["result"],
                "question": t["result"].get("question"),
                "created_at": store.object_created_at(session_id, t["id"]),
            }
            for t in sorted(turns, key=lambda x: (x["result"]["as_of_seq"], x["id"]))
        ],
        "approval_denials": sorted(
            [
                {**record, "created_at": store.object_created_at(session_id, record["id"])}
                for record in denials
            ],
            key=lambda record: (record["created_at"] or "", record["id"]),
        ),
        "mode": "saved_replay_no_model_calls",
    }
