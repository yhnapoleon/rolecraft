import threading
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from career_lab.jobs.repository import LeaseLost
from career_lab.contracts.v2.core import ProtocolError


@dataclass(frozen=True)
class WorkerClaim:
    job_id: str
    lease_token: str
    worker_id: str
    attempt: int

    @classmethod
    def from_job(cls, job):
        return cls(job["id"], job["lease_token"], job["worker_id"], job["attempt"])


@dataclass(frozen=True)
class ClaimedHandler:
    callback: Callable
    retry_on_error: bool = True

    def __call__(self, payload, claim):
        return self.callback(payload, claim)


@dataclass(frozen=True)
class NonRetryingHandler:
    callback: Callable
    retry_on_error: bool = False

    def __call__(self, payload):
        return self.callback(payload)


class Worker:
    def __init__(self, jobs, handlers):
        self.jobs, self.handlers, self.id = jobs, handlers, uuid4().hex

    def run_once(self):
        job = self.jobs.claim_job(self.id)
        if job is None:
            return False
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(15):
                try:
                    self.jobs.heartbeat(job["id"], job["lease_token"])
                except LeaseLost:
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        handler = None
        try:
            handler = self.handlers[job["kind"]]
            if job["attempt"] > 1 and not getattr(handler, "retry_on_error", True):
                self.jobs.fail(job, "model_retry_requires_user_action", retry=False)
                return True
            if isinstance(handler, ClaimedHandler):
                result = handler(job["payload"], WorkerClaim.from_job(job))
            else:
                result = handler(job["payload"])
            self.jobs.complete(job["id"], job["lease_token"], result)
        except LeaseLost:
            pass
        except Exception as exc:
            try:
                if isinstance(handler, ClaimedHandler):
                    code = exc.code if isinstance(exc, ProtocolError) else "job_execution_failed"
                    if code in {
                        "context_stale",
                        "object_version_conflict",
                        "job_session_inactive",
                        "job_cycle_closed",
                        "job_cycle_changed",
                    }:
                        self.jobs.needs_context(job, code)
                    else:
                        deterministic = isinstance(exc, ProtocolError) and (
                            exc.status < 500
                            or code
                            in {
                                "module_unavailable",
                                "module_object_invalid",
                                "module_response_invalid",
                                "object_kind_unavailable",
                            }
                        )
                        self.jobs.fail(
                            job, code, retry=handler.retry_on_error and not deterministic
                        )
                else:
                    self.jobs.fail(
                        job, type(exc).__name__, retry=getattr(handler, "retry_on_error", True)
                    )
            except LeaseLost:
                pass
        finally:
            stop.set()
            thread.join(timeout=2)
        return True
