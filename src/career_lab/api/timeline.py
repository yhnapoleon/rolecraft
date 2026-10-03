def timeline(store, session_id):
    events = store.project_view(session_id, "learner").recent_events
    turns = store.list_objects(session_id, "turn")
    return {"events": [e.model_dump(mode="json") for e in events],
            "turns": [t["result"] for t in sorted(turns, key=lambda x: (x["result"]["as_of_seq"], x["id"]))],
            "mode": "saved_replay_no_model_calls"}
