import hashlib
import json
from uuid import uuid4

from sqlalchemy import insert, select, update

from career_lab.contracts.actions import Action, Event, TransitionResult, WorldState
from career_lab.contracts.scenario import ScenarioSpec
from career_lab.scenarios.reducer import apply_action, initial_state
from career_lab.scenarios.visibility import project_view
from career_lab.storage.database import Database, sessions, snapshots, events, actions, objects


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class IdempotencyConflict(ValueError):
    pass


class SessionStore:
    def __init__(self, url: str):
        self.db = Database(url)

    def close(self):
        self.db.engine.dispose()

    def create_session(self, spec: ScenarioSpec, session_id: str | None = None, token: str = "") -> WorldState:
        state = initial_state(session_id or uuid4().hex, spec)
        with self.db.transaction() as conn:
            conn.execute(insert(sessions).values(id=state.session_id, spec=spec.model_dump_json(), state=state.model_dump_json(), token_hash=digest(token)))
            conn.execute(insert(snapshots).values(session_id=state.session_id, seq=0, state=state.model_dump_json()))
        return state

    def _session(self, conn, session_id, lock=False):
        query = select(sessions).where(sessions.c.id == session_id)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        if row is None:
            raise KeyError("session not found")
        return row

    def authenticate(self, session_id, token):
        import hmac
        with self.db.engine.connect() as conn:
            return hmac.compare_digest(self._session(conn, session_id)["token_hash"], digest(token))

    def get_spec(self, session_id) -> ScenarioSpec:
        with self.db.engine.connect() as conn:
            return ScenarioSpec.model_validate_json(self._session(conn, session_id)["spec"])

    def get_state(self, session_id, as_of_seq=None) -> WorldState:
        with self.db.engine.connect() as conn:
            if as_of_seq is None:
                raw = self._session(conn, session_id)["state"]
            else:
                raw = conn.execute(select(snapshots.c.state).where(snapshots.c.session_id == session_id, snapshots.c.seq == as_of_seq)).scalar_one_or_none()
                if raw is None:
                    raise KeyError("snapshot not found")
            return WorldState.model_validate_json(raw)

    def events(self, session_id) -> tuple[Event, ...]:
        with self.db.engine.connect() as conn:
            return tuple(Event.model_validate_json(raw) for raw in conn.execute(select(events.c.content).where(events.c.session_id == session_id).order_by(events.c.seq)).scalars())

    def project_view(self, session_id, actor_id, as_of_seq=None):
        return project_view(self.get_state(session_id, as_of_seq), actor_id, self.get_spec(session_id), self.events(session_id))

    def commit_action(self, session_id: str, action: Action, *, object_record: dict | None = None) -> TransitionResult:
        request_hash = digest({"action": action.model_dump(mode="json"), "object": object_record})
        with self.db.transaction() as conn:
            row = self._session(conn, session_id, lock=True)
            previous = conn.execute(select(actions).where(actions.c.session_id == session_id, actions.c.key == action.idempotency_key)).mappings().first()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise IdempotencyConflict("idempotency key reused with different request")
                return TransitionResult.model_validate_json(previous["result"]).model_copy(update={"replayed": True})
            if action.tool in {"test_assistant", "save_artifact", "submit_plan", "record_turn"}:
                if not object_record or object_record["id"] != action.arguments.get("object_id"):
                    raise ValueError("service operation needs atomically stored content")
            result = apply_action(WorldState.model_validate_json(row["state"]), action, ScenarioSpec.model_validate_json(row["spec"]))
            conn.execute(update(sessions).where(sessions.c.id == session_id).values(state=result.state.model_dump_json()))
            for snapshot in result.snapshots:
                conn.execute(insert(snapshots).values(session_id=session_id, seq=snapshot.version, state=snapshot.model_dump_json()))
            for event in result.events:
                conn.execute(insert(events).values(session_id=session_id, seq=event.seq, content=event.model_dump_json()))
            if object_record:
                conn.execute(insert(objects).values(id=object_record["id"], session_id=session_id, kind=object_record["kind"], content=canonical(object_record["content"])))
            conn.execute(insert(actions).values(session_id=session_id, key=action.idempotency_key, request_hash=request_hash, result=result.model_dump_json()))
            return result

    def get_object(self, session_id, object_id, kind=None):
        with self.db.engine.connect() as conn:
            query = select(objects).where(objects.c.id == object_id, objects.c.session_id == session_id)
            if kind:
                query = query.where(objects.c.kind == kind)
            row = conn.execute(query).mappings().first()
            if row is None:
                raise KeyError("object not found")
            return json.loads(row["content"])

    def list_objects(self, session_id, kind):
        with self.db.engine.connect() as conn:
            rows = conn.execute(select(objects).where(objects.c.session_id == session_id, objects.c.kind == kind)).mappings()
            return [{"id": row["id"], **json.loads(row["content"])} for row in rows]

    def save_derived(self, session_id, object_id, kind, content):
        """Persist immutable derived output without creating a learner business event."""
        with self.db.transaction() as conn:
            self._session(conn, session_id, lock=True)
            previous = conn.execute(select(objects).where(objects.c.id == object_id)).mappings().first()
            if previous:
                if previous["session_id"] != session_id or previous["kind"] != kind or previous["content"] != canonical(content):
                    raise IdempotencyConflict("derived output conflict")
                return json.loads(previous["content"])
            conn.execute(insert(objects).values(id=object_id, session_id=session_id, kind=kind, content=canonical(content)))
        return content
