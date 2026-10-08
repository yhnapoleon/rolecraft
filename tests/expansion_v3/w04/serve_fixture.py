"""Standalone HTTP boundary fixture; role ports deliberately remain unavailable.

It does not forge ScenarioModule's runtime manifest or install an unprotected
private audit kind. A role request must fail before invoking any model.
"""

import argparse
import time
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, ScenarioRegistration
from career_lab.contracts.v2 import AssistantConfig, SessionBindings, FileRef, digest
from career_lab.runtime.roles_v2 import create_role_service
from career_lab.runtime.context_v2 import ScenarioKnowledge
from career_lab.scenarios.v2.loader import load_package
from career_lab.storage.v2_store import V2Store
from career_lab.storage.role_memory import install_role_storage
from career_lab.jobs.worker import Worker
from pathlib import Path


def build_app(url):
    package = load_package(Path(__file__).resolve().parents[3] / "scenarios/pm_pilot/v2")
    catalog = ScenarioKnowledge.from_package(package)
    registry = ExtensionRegistry()
    fixture = FileRef(path="boundary-fixture.json", sha256=digest("boundary-only"))
    bindings = SessionBindings(scenario=catalog.binding, runtime=fixture, evaluation=fixture)
    registry.register_scenario(
        "w04-unavailable-ports",
        ScenarioRegistration(
            bindings, package.baseline("template"), package.bundle.initial_resources
        ),
    )
    service = create_role_service(V2Store(url), catalog)
    service.install(registry)
    app = create_app(url, extensions=registry)
    install_role_storage(app.state.v2_store)
    return app


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("serve", "worker"))
    p.add_argument("--database", required=True)
    p.add_argument("--port", type=int, default=18782)
    args = p.parse_args()
    app = build_app(args.database)
    if args.mode == "serve":
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    else:
        worker = Worker(app.state.jobs, app.state.handlers)
        while True:
            if not worker.run_once():
                time.sleep(0.05)
