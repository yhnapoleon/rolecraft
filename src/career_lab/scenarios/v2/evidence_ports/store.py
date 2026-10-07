"""Actual persisted W02 history through existing authorized public read adapters.

No private SQL/table access, shadow database, in-memory action capture, synthetic
clock or external call. The W05 evaluation bundle pins this adapter separately
from the scenario engine's runtime dependency set.
"""
from career_lab.contracts import v2 as C
from career_lab.api.evaluation_runtime import ScenarioEvidencePort
from career_lab.api.vertical_reads import public_event_history
from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter,ScenarioEvidenceWindow,before
from career_lab.scenarios.v2.module import point


def create_store_fact_adapter(store,module,registry):
    points_reader=ScenarioEvidencePort(store,module).points
    def exact_window(auth,at):
        store.authorize(auth,'read')
        points=points_reader(auth,at)
        def read(view):
            module.check_bindings(view.bindings)
            if point(view.state)!=at:raise C.ProtocolError('snapshot_point_mismatch')
            projected=public_event_history(store,registry,auth,at,view=view)
            events=[]
            for event in projected:
                born=min((p for p in points if p.business_seq>=event.seq and before(p,at)),key=lambda p:p.storage_revision,default=None)
                if born is None:raise C.ProtocolError('event_time_unknown')
                events.append((event,born))
            # This assertion concerns W02's immutable committed test outcomes and
            # relevant business events, not all learner activity or failed HTTP
            # attempts. Finite object grants never prove absence outside scope.
            producers=[]
            for operation in ('tests.create','actions'):
                installed=registry.operations.get(operation)
                producer=getattr(installed.handler,'__self__',None) if installed else None
                producers.append(getattr(producer,'bindings',None)==module.bindings)
            complete=auth.allowed_objects is None and all(producers)
            return ScenarioEvidenceWindow(module.snapshot(view),view.bindings,tuple(view.objects),tuple(events),tuple(points),complete,complete)
        return store.query_at(auth,at,read)
    return ScenarioFactAdapter(module,authorize=lambda auth:store.authorize(auth,'read'),window_reader=exact_window,
        record_reader=lambda auth,ref,at:store.read(auth,ref,storage_revision=at.storage_revision if at else None),
        reference_resolver=lambda auth,ref,at:store.resolve_reference(auth,ref,storage_revision=at.storage_revision))
