"""The shared production assembly used by both the HTTP server and worker.

Scenario construction validates the frozen runtime before anything is served.
No runtime repair, provider call or secret persistence takes place at startup.
"""
import os
from pathlib import Path

from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry
from career_lab.api.workspace_integration import install_workspace_recovery
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.api.lifecycle_integration import install_lifecycle
from career_lab.api.vertical_reads import install_native_reads
from career_lab.api.private_roles import install_private_role_runtime
from career_lab.runtime.context_v2 import ScenarioKnowledge
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.runtime.model_adapter import LocalModel, OpenAICompatibleModel
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.workspace.extension import install_workspace_operations


# The normal-input repair must be a coordinator-fixed W04 backend input.
ROLE_RUNTIME_READY = True

def configured_models(provider="local"):
    if provider == "local":
        return LocalModel(), LocalRoleModel()
    defaults = {
        "deepseek": ("ds.txt", "https://api.deepseek.com", "deepseek-chat"),
        "openai": ("openai.txt", "https://api.openai.com/v1", "gpt-4.1-mini"),
    }
    key_file, url, name = defaults[provider]
    model = OpenAICompatibleModel.from_key_file(
        Path(os.getenv("CAREER_LAB_KEY_FILE", key_file)),
        base_url=os.getenv("CAREER_LAB_BASE_URL", url),
        model=os.getenv("CAREER_LAB_MODEL", name), retries=0,
    )
    return model, model


def build_registry(scenario_root, role_model, *, feedback_handler=None,store_provider=None):
    module = ScenarioModule(scenario_root)
    registry = module.install(ExtensionRegistry())
    if feedback_handler is None:
        from career_lab.api.evaluation_runtime import create_feedback_handler
        feedback_handler=create_feedback_handler(module,model=None if isinstance(role_model,LocalRoleModel) else role_model)
    roles = tuple(role.id for role in module.package.bundle.role_specs)
    install_workspace_operations(registry, roles=roles)
    install_workspace_recovery(registry, roles=roles)
    install_feedback_recovery(registry)
    install_lifecycle(registry, feedback_handler=feedback_handler)
    install_private_role_runtime(registry, ScenarioKnowledge.from_package(module.package),
                                 role_model, enable_generation=ROLE_RUNTIME_READY)
    install_native_reads(registry, module, role_mode=("local_reference" if isinstance(role_model,LocalRoleModel) else "model") if ROLE_RUNTIME_READY else "unavailable",store_provider=store_provider)
    return registry, module


def create_runtime_app(database_url=None, *, provider="local", scenario_root=None,
                       feedback_handler=None):
    legacy_model, role_model = configured_models(provider)
    root = Path(scenario_root or os.getenv("CAREER_LAB_SCENARIO_V2", "scenarios/pm_pilot/v2"))
    holder={}
    registry, module = build_registry(root, role_model, feedback_handler=feedback_handler,store_provider=lambda:holder["store"])
    app = create_app(database_url, model=legacy_model, extensions=registry)
    from career_lab.jobs.worker import NonRetryingHandler
    for name in ("turn","feedback"):
        app.state.handlers[name]=NonRetryingHandler(app.state.handlers[name])
    holder["store"] = app.state.v2_store
    app.state.scenario_v2 = module
    app.state.model_provider = provider
    return app
