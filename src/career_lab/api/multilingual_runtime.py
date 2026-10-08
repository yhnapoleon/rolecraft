"""Select already-prepared runtimes by immutable binding and fixed work language."""

from dataclasses import replace
from pathlib import Path
import json
from career_lab.api.modules import StoreJobHandler
from career_lab.contracts.v2 import canonical, ProtocolError


def build_catalog(
    factory,
    catalog_path,
    role_model,
    *,
    feedback_handler=None,
    store_provider=None,
    scenario_archive=None,
):
    index = json.loads(Path(catalog_path).read_text())
    entries = index["scenarios"]
    groups = []
    for entry in entries:
        registry, module = factory(
            Path(entry["root"]),
            role_model,
            feedback_handler=feedback_handler,
            store_provider=store_provider,
            scenario_archive=scenario_archive,
        )
        if (
            module.bindings.scenario.sha256 != entry["scenario_hash"]
            or module.work_language != entry["work_language"]
        ):
            raise ProtocolError("scenario_catalog_mismatch", status=503)
        groups.append((registry, module))
    if not groups:
        raise ProtocolError("scenario_catalog_empty", status=503)
    primary, module = groups[0]
    key = lambda binding: canonical(binding)
    operations = {key(m.bindings): dict(r.operations) for r, m in groups}
    resolvers = {key(m.bindings): dict(r.reference_resolvers) for r, m in groups}
    jobs = {key(m.bindings): dict(r.job_handlers) for r, m in groups}
    default = key(module.bindings)
    primary.language_scenarios = {}
    for r, m in groups:
        for name, registration in r.scenarios.items():
            choice = (name, m.work_language)
            if choice in primary.language_scenarios:
                raise ProtocolError("duplicate_scenario_language", status=503)
            primary.language_scenarios[choice] = registration
    primary.active_bindings = tuple(m.bindings for _, m in groups)
    # Every request is dispatched through the primary registry, including operations mounted on it
    # after this catalog is built (the Agent control plane, observation and tools). A language or
    # variant registry reports its own operations, and defers to the primary for anything it lacks,
    # so its workbench does not show a dispatchable operation as unavailable.
    for r, _ in groups[1:]:
        own = r.availability

        def availability(name, own=own):
            result = own(name)
            return result if result.installed else primary.availability(name)

        r.availability = availability
    for name, op in operations[default].items():
        if op.service_mode:
            continue

        def handler(view, payload, auth, name=name):
            selected = operations.get(key(view.bindings), operations[default])[name]
            return selected.handler(view, payload, auth)

        def approval(view, command, auth, name=name):
            policy = operations.get(key(view.bindings), operations[default])[name].approval_policy
            if policy is None:
                raise ProtocolError("approval_policy_required", status=403)
            return policy(view, command, auth)

        primary.operations[name] = replace(
            op, handler=handler, approval_policy=approval if op.approval_policy else None
        )
    for kind in resolvers[default]:

        def resolve(auth, ref, as_of, bindings, kind=kind, **kwargs):
            return resolvers.get(key(bindings), resolvers[default])[kind](
                auth, ref, as_of, bindings, **kwargs
            )

        primary.reference_resolvers[kind] = resolve
    for name, handler in jobs[default].items():
        if not isinstance(handler, StoreJobHandler):
            raise ProtocolError("scenario_job_adapter_required", status=503)

        def run(store, view, envelope, auth, name=name):
            choices = jobs.get(key(view.bindings))
            if choices is None:
                raise ProtocolError("scenario_read_only", status=409)
            return choices[name].callback(store, view, envelope, auth)

        primary.job_handlers[name] = StoreJobHandler(run, retry_on_error=False)
    return primary, module
