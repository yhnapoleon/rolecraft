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
from career_lab.api.vertical_reads import install_native_reads, history_reader, public_material_resolver
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
    model.provider = provider
    return model, model


def build_registry(scenario_root, role_model, *, feedback_handler=None,store_provider=None,scenario_archive=None):
    module = ScenarioModule(scenario_root)
    registry = module.install(ExtensionRegistry(),name=module.package.bundle.id+'_v2')
    from career_lab.api.scenario_history import ScenarioReadCatalog
    from career_lab.api.negotiation_runtime import install_negotiation
    catalog=ScenarioReadCatalog(module,scenario_archive)
    registry.active_bindings=(module.bindings,)
    install_negotiation(registry,module)
    registry.reference_resolvers["material"]=public_material_resolver(module,catalog.resolve)
    from dataclasses import replace
    registry.scenarios={name:replace(registration,work_language=module.work_language) for name,registration in registry.scenarios.items()}
    if feedback_handler is None:
        from career_lab.api.evaluation_runtime import create_feedback_handler
        feedback_handler=create_feedback_handler(module,model=None if isinstance(role_model,LocalRoleModel) else role_model)
    from career_lab.api.v4_config import install_settings
    install_settings(registry,module)
    roles = tuple(role.id for role in module.package.bundle.role_specs)
    install_workspace_operations(registry, roles=roles)
    install_workspace_recovery(registry, roles=roles)
    install_feedback_recovery(registry)
    install_lifecycle(registry, feedback_handler=feedback_handler)
    install_private_role_runtime(registry, ScenarioKnowledge.from_package(module.package),
                                 role_model, enable_generation=ROLE_RUNTIME_READY)
    install_native_reads(registry, module, role_mode=("local_reference" if isinstance(role_model,LocalRoleModel) else "model") if ROLE_RUNTIME_READY else "unavailable",feedback_mode="waiting_model" if isinstance(role_model,LocalRoleModel) else "model",store_provider=store_provider,scenario_resolver=catalog.resolve)
    return registry, module


def default_installed_scenario():
    """The standard entry consumes the current release, never author placeholders."""
    import hashlib
    import json
    from career_lab.contracts.v2 import ProtocolError
    repo = Path(__file__).resolve().parents[3]
    index = json.loads((repo / 'scenarios/pm_pilot/v2/installed/current.json').read_text())
    entry = index['main']['zh']
    root = (repo / entry['root']).resolve()
    if not root.is_relative_to(repo) or hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest() != entry['scenario_hash']:
        raise ProtocolError('installed_scenario_identity_mismatch', status=409)
    return root


def create_runtime_app(database_url=None, *, provider="local", scenario_root=None,
                       feedback_handler=None):
    legacy_model, role_model = configured_models(provider)
    root = Path(scenario_root or os.getenv("CAREER_LAB_SCENARIO_V2") or default_installed_scenario())
    holder={}
    options=dict(feedback_handler=feedback_handler,store_provider=lambda:holder["store"],scenario_archive=os.getenv("CAREER_LAB_SCENARIO_ARCHIVE","runs/local/scenario-archive"))
    if os.getenv('CAREER_LAB_SCENARIO_CATALOG'):
        from career_lab.api.multilingual_runtime import build_catalog
        registry,module=build_catalog(build_registry,os.environ['CAREER_LAB_SCENARIO_CATALOG'],role_model,**options)
    else:
        registry,module=build_registry(root,role_model,**options)
    app = create_app(database_url, model=legacy_model, extensions=registry)
    from career_lab.jobs.worker import NonRetryingHandler
    for name in ("turn","feedback"):
        app.state.handlers[name]=NonRetryingHandler(app.state.handlers[name])
    holder["store"] = app.state.v2_store
    app.state.v2_store.public_history_reader=history_reader(registry)
    from career_lab.delegations.factory import mount_delegations
    from career_lab.delegations.catalog import SYNC_OPERATIONS
    mount_delegations(app,synchronous=SYNC_OPERATIONS|{'actions','approvals.resolve','tests.create'})
    app.state.scenario_v2 = module
    app.state.model_provider = provider
    return app
