"""Read-only command proof using the store's existing request fingerprint verifier."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from career_lab.contracts.v2.core import Command, Executor, ProtocolError
from career_lab.contracts.v2.discovery import REQUEST_MODELS, public_models
from career_lab.delegations.credentials import Credentials
from career_lab.storage.v2_store import V2Store


@dataclass(frozen=True)
class RequestIdentity:
    database: Path
    credentials: Credentials
    executor: Executor

    def transaction_for(self, command: Command, operation: str) -> str:
        store = V2Store(
            "sqlite:///file:" + quote(str(self.database.resolve()), safe="/") + "?mode=ro&uri=true"
        )
        try:
            auth = store.authenticate(self.credentials.session_id, self.credentials.token)
            if auth.executor != self.executor:
                raise ProtocolError("request_result_identity_mismatch", status=409)
            # Despite its name, replay only reads a matching, authorized stored result.
            # It verifies the complete command/actor/credential fingerprint and never
            # dispatches a handler, mutation, approval or model call.
            # Gateway dispatch normalizes payloads through these same public models
            # before persisting the command fingerprint (including default fields).
            payload = public_models()[REQUEST_MODELS[operation]].model_validate(command.payload)
            canonical_command = Command.model_validate(
                command.model_dump(mode="json") | {"payload": payload.model_dump(mode="json")}
            )
            result = store.replay(auth, canonical_command, capability="read")
            if result is None:
                raise ProtocolError("request_not_found", status=404)
            return result.transaction_id
        finally:
            store.db.engine.dispose()
