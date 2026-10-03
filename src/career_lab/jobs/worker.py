import threading
from uuid import uuid4

from career_lab.jobs.repository import LeaseLost


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
        try:
            result = self.handlers[job["kind"]](job["payload"])
            self.jobs.complete(job["id"], job["lease_token"], result)
        except LeaseLost:
            pass
        except Exception as exc:
            try:
                self.jobs.fail(job, type(exc).__name__)
            except LeaseLost:
                pass
        finally:
            stop.set()
            thread.join(timeout=2)
        return True
