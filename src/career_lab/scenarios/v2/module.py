"""W02 adapter to the frozen W01 public store; all handlers are pure plans.

Register these operations through the integrator's ExtensionRegistry. No app.py,
storage implementation or global CLI mutation is performed here.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from career_lab.api.modules import ExtensionRegistry, Operation, ScenarioRegistration, V2Response
from career_lab.contracts.v2 import (
    ActionInput, ApprovalInput, AssistantConfig, BusinessRequest, BusinessDecision,
    EvidenceRefV2, ExternalReference, FileRef, ObjectRef, ProtocolError, PublicEvent,
    ResourcePage, ScenarioStateV2, SessionBindings, TestRequestV2, TestResultV2,
    VersionPoint, RuntimeBundle, EvaluationBundle, canonical, digest, read_file,
)
from career_lab.storage.v2_store import Mutation, ObjectWrite, EventDraft, references
from career_lab.assistant.v2 import Assistant
from .loader import load_package
from .engine import ScenarioEngine, ScenarioSnapshot
from .policy import evaluate_request


def point(state):
    return VersionPoint(**state.model_dump(include={"business_seq","workspace_revision","storage_revision"}))


def ref_for(kind,obj):
    return ObjectRef(session_id=obj.session_id,kind=kind,object_id=obj.id,version=obj.version,
        config_version=obj.config_version if kind=="config" else None)


def latest(view,kind):
    results={}
    for record in view.objects:
        if record.ref.kind==kind and (record.ref.object_id not in results or record.ref.version>results[record.ref.object_id].ref.version):
            results[record.ref.object_id]=record
    return tuple(results.values())


class ScenarioModule:
    def __init__(self,root):
        self.package=load_package(Path(root))
        self.engine=ScenarioEngine(self.package)
        self.assistant=Assistant(self.package)
        self.files={f.path:f for f in self.package.bundle.files}
        self.bindings=SessionBindings(scenario=FileRef(path="manifest.json",sha256=self.package.content_hash),
            runtime=self.files["runtime/bundle.json"],evaluation=self.files["runtime/evaluation.json"])
        runtime=RuntimeBundle.model_validate_json(read_file(self.package.root,self.bindings.runtime))
        EvaluationBundle.model_validate_json(read_file(self.package.root,self.bindings.evaluation))
        source=json.loads(read_file(self.package.root,runtime.source.overlay))
        repo=Path(__file__).resolve().parents[4]
        actual={name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in source["owned_code"]}
        if actual!=source["owned_code"] or digest(actual)!=runtime.source.source_digest:
            raise ProtocolError("runtime_source_mismatch",status=409)
        foundation=repo/"docs/contracts/expansion-v3/manifest.json"
        if hashlib.sha256(foundation.read_bytes()).hexdigest()!=source["foundation_contract_sha256"]:
            raise ProtocolError("runtime_contract_mismatch",status=409)

    def registration(self):
        baseline=self.package.bundle.baseline_config
        private=ScenarioStateV2(id="scenario-state",session_id=baseline.session_id,version=1,
            current_config=ref_for("config",baseline),
            source_versions=self.package.rules["initial_material_versions"],
            indexed_versions=self.package.rules["initial_material_versions"],
            material_activation={f"{mid}:{version}":0 for mid,version in self.package.rules["initial_material_versions"].items()})
        return ScenarioRegistration(self.bindings,baseline,dict(self.package.bundle.initial_resources),private)

    def check_bindings(self,bindings):
        if bindings!=self.bindings:raise ProtocolError("scenario_binding_mismatch",status=409)
        read_file(self.package.root,self.bindings.scenario)

    def snapshot(self,view):
        self.check_bindings(view.bindings)
        private=view.private_scenario_state
        if private is None or private.session_id!=view.state.session_id:
            raise ProtocolError("scenario_state_missing",status=503)
        config=AssistantConfig.model_validate(view.get(private.current_config).content)
        requests=tuple(BusinessRequest.model_validate(x.content) for x in latest(view,"business_request"))
        decisions=tuple(BusinessDecision.model_validate(x.content) for x in latest(view,"business_decision"))
        return ScenarioSnapshot(view.state,config,dict(private.source_versions),dict(private.indexed_versions),
            dict(private.material_activation),requests,decisions,{x.id:x.basis.config for x in requests})

    def write(self,obj,kind,head,visible_to=("learner",)):
        content=obj.model_dump(mode="json")
        return ObjectWrite(ref=ref_for(kind,obj),expected_head=head,content=content,
            visible_to=visible_to,dependencies=references(content))

    def reference(self,auth,ref,as_of,bindings,*,scenario_state=None):
        """Pure resolver. Future-version references require authoritative context.

        The registered contextual resolver receives the authoritative snapshot from
        the public store. Direct callers without it can only resolve initial versions.
        """
        self.check_bindings(bindings)
        if "read" not in auth.capabilities or ref.session_id!=auth.session_id or ref.kind!="material":
            raise ProtocolError("material_unavailable",status=404)
        if auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects:
            raise ProtocolError("material_unavailable",status=404)
        initial=self.package.rules["initial_material_versions"]
        if scenario_state is None:
            if initial.get(ref.object_id)!=ref.version:
                raise ProtocolError("reference_context_required",status=503)
            activation=0
        else:
            if scenario_state.session_id!=auth.session_id:raise ProtocolError("material_unavailable",status=404)
            activation=scenario_state.material_activation.get(f"{ref.object_id}:{ref.version}")
            if activation is None or activation>as_of.business_seq:
                raise ProtocolError("material_unavailable",status=404)
        fragments=self.package.project(ref.object_id,ref.version,auth.actor_id,as_of.business_seq,auth.session_id)
        if not fragments:raise ProtocolError("material_unavailable",status=404)
        if isinstance(ref,EvidenceRefV2):
            if ref.observed_at_seq>as_of.business_seq or ref.observed_at_seq<activation or ref.valid_from_seq!=activation:
                raise ProtocolError("reference_time_mismatch",status=409)
            if ref.quote is not None or ref.span_start is not None:
                permitted=next((f for f in fragments if f.ref.span_start is not None and
                    ref.span_start is not None and ref.span_end is not None and
                    f.ref.span_start<=ref.span_start<ref.span_end<=f.ref.span_end and
                    f.text[ref.span_start-f.ref.span_start:ref.span_end-f.ref.span_start]==ref.quote),None)
                if permitted is None:raise ProtocolError("reference_span_forbidden",status=403)
        path=self.package.rules["material_files"][ref.object_id][str(ref.version)]
        file=self.files[path];read_file(self.package.root,file)
        bare=ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode="json").items() if k in ObjectRef.model_fields})
        return ExternalReference(ref=bare,source=file,content_hash=file.sha256)

    def reference_resolver(self,auth,ref,as_of,bindings,*,scenario_state):
        return self.reference(auth,ref,as_of,bindings,scenario_state=scenario_state)

    def check_evidence(self,view,auth,ref):
        if ref.session_id!=auth.session_id or ref.observed_at_seq>view.state.business_seq:
            raise ProtocolError("evidence_unavailable",status=404)
        if ref.kind=="material":
            self.reference(auth,ref,point(view.state),view.bindings,scenario_state=view.private_scenario_state)
        else:
            bare=ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode="json").items() if k in ObjectRef.model_fields})
            record=view.get(bare)
            if ref.quote is not None:
                text=record.content.get("content",record.content.get("answer"))
                if not isinstance(text,str) or ref.span_start is None or ref.span_end is None or text[ref.span_start:ref.span_end]!=ref.quote:
                    raise ProtocolError("reference_span_forbidden",status=403)
        return True

    def action(self,view,command,auth):
        self.check_bindings(view.bindings)
        args=ActionInput.model_validate(command.payload)
        if args.tool=="read_material":
            # Reading materials does not require a grant to the unrelated config.
            if args.material is None:raise ProtocolError("material_unavailable",status=404)
            state=view.private_scenario_state
            if state is None or state.material_activation.get(f"{args.material.object_id}:{args.material.version}",view.state.business_seq+1)>view.state.business_seq:
                raise ProtocolError("material_unavailable",status=404)
            self.reference(auth,args.material,point(view.state),view.bindings,scenario_state=state)
            fragments=self.package.project(args.material.object_id,args.material.version,auth.actor_id,view.state.business_seq,auth.session_id)
            fragments=tuple(f.model_copy(update={"ref":f.ref.model_copy(update={
                "observed_at_seq":view.state.business_seq,
                "valid_from_seq":state.material_activation[f"{f.ref.object_id}:{f.ref.version}"]})}) for f in fragments)
            return Mutation(events=(EventDraft(type="material_read",visible_to=(auth.actor_id,),
                data={"material_id":args.material.object_id,"version":args.material.version}),),
                result={"material":{"id":args.material.object_id,"version":args.material.version},
                        "fragments":[f.model_dump(mode="json") for f in fragments],"read_at":point(view.state).model_dump(mode="json")})
        before=self.snapshot(view)
        for ref in args.evidence_refs:self.check_evidence(view,auth,ref)
        planned=self.engine.plan(before,command,auth)
        after=planned.snapshot;writes=[]
        if after.config!=before.config:writes.append(self.write(after.config,"config",before.config.version))
        old_requests={r.id:r for r in before.requests}
        for req in after.requests:
            previous=old_requests.get(req.id)
            if previous!=req:writes.append(self.write(req,"business_request",previous.version if previous else 0))
        if (before.source_versions,before.indexed_versions,before.material_activation,before.config)!=(after.source_versions,after.indexed_versions,after.material_activation,after.config):
            current=view.private_scenario_state
            private=ScenarioStateV2(id=current.id,session_id=auth.session_id,version=current.version+1,
                current_config=ref_for("config",after.config),source_versions=after.source_versions,
                indexed_versions=after.indexed_versions,material_activation=after.material_activation)
            writes.append(self.write(private,"scenario_state",current.version,visible_to=("system",)))
        events=tuple(EventDraft(type=e["event_type"],visible_to=tuple(e["visible_to"]),data=e["payload"]) for e in planned.events)
        changes={key:getattr(after.world,key) for key in ("status","config_version","applied_milestones")
                 if getattr(after.world,key)!=getattr(before.world,key)}
        result={}
        if args.tool=="apply_config":result={"config":planned.result.model_dump(mode="json")}
        elif args.tool=="request_business":result={"request":ref_for("business_request",planned.result).model_dump(mode="json"),
            "request_data":planned.result.model_dump(mode="json")}
        return Mutation(writes=tuple(writes),events=events,state_changes=changes,result=result)

    def approval_policy(self,view,command,auth):
        if auth.allowed_objects is not None:raise ProtocolError("object_forbidden",status=403)
        args=ApprovalInput.model_validate(command.payload)
        if args.request.session_id!=auth.session_id or args.request.kind!="business_request":
            raise ProtocolError("request_unavailable",status=404)
        snapshot=self.snapshot(view)
        request=next((r for r in snapshot.requests if r.id==args.request.object_id),None)
        if request is None:raise ProtocolError("request_unavailable",status=404)
        if request.version!=args.expected_request_revision or args.request.version!=request.version:
            raise ProtocolError("request_revision_conflict",status=409)
        def checked(ref):
            try:return self.check_evidence(view,auth,ref)
            except ProtocolError:return False
        decision=evaluate_request(self.package,request,snapshot,checked)
        return decision.model_copy(update={"as_of":point(view.state)})

    def approve(self,view,command,auth):
        decision=self.approval_policy(view,command,auth)
        request=BusinessRequest.model_validate(view.get(decision.request).content)
        updated=request.model_copy(update={"version":request.version+1,"status":decision.status})
        writes=[self.write(updated,"business_request",request.version),self.write(decision,"business_decision",0)]
        events=[EventDraft(type="business_decided",visible_to=("learner","supervisor","tech_lead","business_lead"),
            refs=(ref_for("business_decision",decision),),data={"decision_id":decision.id,"request_id":request.id,
                "status":decision.status,"reason_code":decision.reason_code,"granted":decision.granted})]
        changes={}
        if decision.status=="approved" and "capacity" in decision.granted:
            snapshot=self.snapshot(view)
            snapshot=replace(snapshot,world=snapshot.world.model_copy(update={
                "business_seq":view.state.business_seq+1,"resources":{**view.state.resources,**decision.granted}}))
            following,notices=self.engine.business_followups(snapshot,"capacity_approved")
            if notices:
                current=view.private_scenario_state
                private=current.model_copy(update={"version":current.version+1,"source_versions":following.source_versions,
                    "indexed_versions":following.indexed_versions,"material_activation":following.material_activation})
                writes.append(self.write(private,"scenario_state",current.version,visible_to=("system",)))
                changes["applied_milestones"]=following.world.applied_milestones
                events.extend(EventDraft(type=n["event_type"],visible_to=tuple(n["visible_to"]),data=n["payload"]) for n in notices)
        return Mutation(writes=tuple(writes),events=tuple(events),state_changes=changes,
            decision=decision,result={"decision":decision.model_dump(mode="json")})

    def test(self,view,command,auth):
        request=TestRequestV2.model_validate(command.payload)
        run=self.assistant.run(self.snapshot(view),request,auth,command.request_id,operation_name=command.operation)
        for ref in run.result.citations:self.check_evidence(view,auth,ref)
        return Mutation(writes=(self.write(run.result,"test",0),),
            events=(EventDraft(type="test_assistant",visible_to=(auth.actor_id,),refs=(ref_for("test",run.result),)),),
            result={"test":run.result.model_dump(mode="json")})

    def list_tests(self,view,payload,auth):
        self.check_bindings(view.bindings)
        records=latest(view,"test")
        # Stored results are immutable; scope to their exact configuration/citations.
        result=[]
        for record in records:
            item=TestResultV2.model_validate(record.content)
            if auth.allowed_objects is not None and any(ref.object_id not in auth.allowed_objects for ref in (item.config_ref,*item.citations)):
                continue
            result.append(item.model_dump(mode="json"))
        return V2Response(result={"tests":sorted(result,key=lambda x:(x["as_of"]["business_seq"],x["id"]))})

    def materials(self,view,payload,auth):
        self.check_bindings(view.bindings)
        state=view.private_scenario_state
        if state is None:raise ProtocolError("scenario_state_missing",status=503)
        seq=view.state.business_seq if payload.as_of_seq is None else payload.as_of_seq
        if seq>view.state.business_seq or seq<0:raise ProtocolError("material_time_unavailable",status=404)
        versions={}
        for key,activated in state.material_activation.items():
            mid,version=key.rsplit(":",1)
            if activated<=seq and int(version)>versions.get(mid,0):versions[mid]=int(version)
        visible=self.package.visible_materials(versions,auth.actor_id,seq,auth.session_id)
        rows=[asdict(m) for m,_ in visible if auth.allowed_objects is None or m.id in auth.allowed_objects]
        return V2Response(result={"materials":rows[payload.cursor:payload.cursor+payload.limit],
            "requested_as_of_seq":seq,"retrieved_at":point(view.state).model_dump(mode="json"),
            "next_cursor":payload.cursor+payload.limit if payload.cursor+payload.limit<len(rows) else None,
            "catalog_is_not_acquired_knowledge":True})

    def project_event(self,event,auth):
        if auth.session_id!=event.session_id or "read" not in auth.capabilities or auth.actor_id not in event.visible_to:
            return None
        payload=dict(event.data)
        payload.pop("trigger",None)  # The learner receives the business notice, not the script trigger.
        allowed=None if auth.allowed_objects is None else set(auth.allowed_objects)
        if "before_versions" in payload or "after_versions" in payload:
            for key in ("before_versions","after_versions"):
                if key in payload:
                    ids={m.id for m,_ in self.package.visible_materials(payload[key],auth.actor_id,event.seq,auth.session_id)}
                    if allowed is not None:ids &= allowed
                    payload[key]={k:v for k,v in payload[key].items() if k in ids}
            if allowed is not None and payload.get("before_versions")==payload.get("after_versions"):return None
            if allowed is not None:payload={k:payload[k] for k in ("before_versions","after_versions")}
        elif event.type in {"material_read","config_applied"}:
            key="material_id" if event.type=="material_read" else "config_id"
            if allowed is not None and payload.get(key) not in allowed:return None
        elif allowed is not None and event.type!="test_assistant":
            return None
        return PublicEvent.model_validate(event.model_dump(mode="json",exclude={"visible_to","data"})|{"data":payload})

    def operations(self):
        return (
            Operation("actions","act",ActionInput,self.action,action_field="tool",event_projector=self.project_event),
            Operation("approvals.resolve","act",ApprovalInput,self.approve,approval_policy=self.approval_policy,
                      action_name="resolve_approval",event_projector=self.project_event),
            Operation("tests.create","act",TestRequestV2,self.test,event_projector=self.project_event),
            Operation("tests.list","read",ResourcePage,self.list_tests,mutates=False,response_model=V2Response),
            Operation("materials.list","read",ResourcePage,self.materials,mutates=False,response_model=V2Response),
        )

    def install(self,registry:ExtensionRegistry,name="pm_pilot_v2"):
        registry.register_scenario(name,self.registration())
        registry.register_reference_resolver("material",self.reference_resolver,contextual=True)
        for operation in self.operations():registry.register(operation)
        return registry
