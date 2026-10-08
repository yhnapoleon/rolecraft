"""W06 assembly on the existing FastAPI/Gateway/store, with no extra persistence."""
from pathlib import Path

from career_lab.api.app import create_app as shared_app
from career_lab.api.delegations_v2 import install_delegations
from career_lab.api.modules import ExtensionRegistry, Operation
from career_lab.api.workspace_integration import install_workspace_recovery
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_lifecycle import begin_revision, record_submission
from career_lab.workspace.extension import install_workspace_operations
from .catalog import SYNC_OPERATIONS
from .sources import WorkspaceSources, stored_history


def mount_delegations(app, *, history_reader=stored_history, synchronous=None):
    """Integrator call after common app creation and normal module installation."""
    gateway = app.state.gateway
    registry = gateway.registry
    source = WorkspaceSources(registry, history_reader=history_reader)
    # A field on TransactionView is only a seam. The actual same-window history
    # reader must be installed before tools advertise an available observation.
    if history_reader is stored_history and not callable(app.state.v2_store.public_history_reader):
        source.unavailable_code = 'observation_history_unavailable'
    bind = install_delegations(registry, source_provider=source, synchronous=synchronous)
    app.state.w06 = bind(gateway)
    # v4 integration extensions (delegation list, reviewed practice) share this post-install mount,
    # so frozen routes and the shared app factory stay unchanged.
    if not getattr(app.state, 'v4_extensions', False):
        from career_lab.api.v4_extensions import mount_v4_extensions
        mount_v4_extensions(app)
        app.state.v4_extensions = True
    return app.state.w06


def create_delegated_app(*, database_url, registry, history_reader=stored_history, synchronous=None):
    """Usable for standard server loading without editing the shared factory."""
    app = shared_app(database_url=database_url, extensions=registry)
    try:
        mount_delegations(app, history_reader=history_reader, synchronous=synchronous)
    except Exception:
        app.state.store.close()
        raise
    return app


def create_scenario_app(*, database_url, scenario_package, history_reader=stored_history):
    """Load the exact W02 package, preserving its source/contract hash checks.

    The caller must supply a coordinator-fixed package. This function neither
    regenerates it nor enables role/model jobs or makes a new queue.
    """
    scenario = ScenarioModule(Path(scenario_package))
    registry = ExtensionRegistry()
    scenario.install(registry)
    roles = tuple(role.id for role in scenario.package.bundle.role_specs)
    install_workspace_operations(registry, roles=roles)
    install_workspace_recovery(registry, roles=roles)
    install_feedback_recovery(registry)
    registry.register(Operation('submissions.create', 'submit', C.SubmitInput, record_submission, action_name='submit'))
    registry.register(Operation('revision_cycles', 'act', C.BeginRevisionInput, begin_revision, action_name='begin_revision'))
    # Only the exact synchronous W02 implementation above is enabled. No role,
    # review or feedback generation is registered without its real runtime.
    app = create_delegated_app(database_url=database_url, registry=registry, history_reader=history_reader,
        synchronous=SYNC_OPERATIONS | {'actions', 'approvals.resolve', 'tests.create'})
    app.state.scenario_v2 = scenario
    return app
