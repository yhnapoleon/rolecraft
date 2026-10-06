"""Role turns run through the registered W01 worker and atomic mutation layer."""
from time import monotonic
from uuid import uuid4

from career_lab.api.modules import Operation
from career_lab.contracts.v2 import (
    Command, DisclosureRecord, ModelAttemptUsage, ObjectRef, ProtocolError,
    ResourcePage, TurnInput, V2, ObjectRead, digest,
)
from career_lab.contracts.v2.projection import project_disclosures
from career_lab.runtime.context_v2 import ContextPort, bare, clean_ref, in_scope
from career_lab.runtime.model_adapter import ModelReply
from career_lab.storage.role_memory import RoleTurn, RoleReply, RoleDisplay, SpokenEvidence, object_write, read_role_memory, read_replies
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import JobRequest, Mutation, EventDraft


class RoleModelUnavailable(RuntimeError):
    """Deliberately contains no provider response, private context or credentials."""


class LocalRoleModel:
    revision = "w04-local-extractive-v1"

    def complete(self, messages, tools):
        import json
        context = json.loads(messages[0]["content"].split("\nCONTEXT\n", 1)[1])
        sources = context["sources"]
        history = [s for s in sources if s["channel"] == "memory"]
        current = [s for s in sources if s["channel"] != "memory"]
        parts = ["本地资料模式。", "我的职责：" + "；".join(context["responsibilities"]) + "。"]
        if history:
            parts.append("我保留上轮讨论记录；以下按本轮收到的版本核对。")
        for source in current[:6]:
            parts.append(f"[{source['id']}] {source['text']}")
        parts.append("这些是讨论依据。申请需单独处理，资源以保存的决定为准；未执行的访谈可先整理为待办。")
        return ModelReply(text="\n".join(parts))


def actual_disclosures(snapshot, auth, reply_ref, text, *, included_sources=None):
    """Only an exact actually spoken source sentence supports a verified record.

    Non-exact model paraphrases remain unrecorded until a separate audited semantic
    extractor verifies them. Prompt membership is never learner knowledge.
    """
    records = []
    for source in snapshot.generation_sources(auth) if included_sources is None else included_sources:
        if not source.text or source.text not in text or not source.fact_ids:
            continue
        for fact_id in source.fact_ids:
            # Public DTOs must never carry a private fact key.
            public_id = "disclosure-" + digest([reply_ref.model_dump(mode="json"), fact_id, source.text])[:20]
            records.append(DisclosureRecord(fact_id=public_id, source=clean_ref(source.ref),
                reply_ref=reply_ref, quote=source.text, verification="verified",
                displayed_at_seq=snapshot.context.as_of.business_seq))
    # Generation is not evidence that a learner displayed the reply.
    return tuple(record.model_copy(update={"displayed_at_seq": None}) for record in records)


def displayed_disclosures(reply, reply_ref, *, displayed_at_seq):
    records = tuple(DisclosureRecord(fact_id=x.label, source=x.source, reply_ref=reply_ref,
                    quote=x.quote, verification=x.verification, displayed_at_seq=displayed_at_seq)
                    for x in reply.spoken_evidence)
    return project_disclosures(reply.text, records, session_id=reply.session_id, as_of_seq=displayed_at_seq)


def record_reply_display(view, command, auth):
    """Explicit client acknowledgement plan; needs the shared turns.display slot.

    Polling a job, generating a reply and restoring a request do not call this.
    Acknowledgement records display, never the learner's comprehension.
    """
    body = ObjectRead.model_validate(command.payload)
    if body.ref.kind != "role_reply" or body.as_of is not None:
        raise ProtocolError("reply_display_invalid")
    reply = RoleReply.model_validate(view.get(body.ref).content)
    if reply.status != "completed":
        raise ProtocolError("reply_unavailable", status=409)
    display = RoleDisplay(id="display-" + digest([auth.session_id, command.request_id])[:24],
                         session_id=auth.session_id, reply=body.ref, as_of=point(view.state), executor=auth.executor)
    write = object_write("role_display", display)
    public = displayed_disclosures(reply, body.ref, displayed_at_seq=view.state.business_seq)
    return Mutation(writes=(write,), result={"display": write.ref.model_dump(mode="json"),
                    "disclosures": [x.model_dump(mode="json") for x in public]})


class RoleService:
    def __init__(self, context_port: ContextPort, model=None, *, max_context_chars=24000):
        self.port, self.model = context_port, model or LocalRoleModel()
        self.max_context_chars = max_context_chars

    def enqueue(self, view, command, auth):
        """Pure callback inside V2Store.execute; no nested transaction or model."""
        turn = TurnInput.model_validate(command.payload)
        self.port.catalog.role(turn.role_id)
        if view.bindings.scenario != self.port.catalog.binding:
            raise ProtocolError("scenario_binding_mismatch", status=409)
        for ref in (*turn.shares, *((turn.task,) if turn.task else ())):
            view.get(ref)
        for ref in turn.shares:
            from career_lab.contracts.v2 import ProductShare
            share = ProductShare.model_validate(view.get(ref).content)
            if (ref.kind != "share" or share.recipient_role != turn.role_id or share.revoked_at is not None):
                raise ProtocolError("share_not_current", status=409)
            latest = max((x for x in view.objects if x.ref.kind == "share"
                          and x.ref.object_id == ref.object_id), key=lambda x: x.ref.version)
            if latest.ref != ref:
                raise ProtocolError("share_not_current", status=409)
            view.get(share.product)
        request = RoleTurn(id="turn-" + digest([auth.session_id, command.request_id])[:24],
                           session_id=auth.session_id, input=turn, as_of=point(view.state), executor=auth.executor)
        write = object_write("role_turn", request)
        job_command = Command(schema_version=2, request_id="role-effect-" + digest(command)[:24],
                              expected_version=command.expected_version,
                              expected_workspace_revision=command.expected_workspace_revision,
                              operation="turns.create", payload={"subject": write.ref.model_dump(mode="json")})
        return Mutation(writes=(write,), jobs=(JobRequest(name="v2.role_turn", command=job_command,
                         sources=(write.ref, *turn.shares), context_hash=digest(request)),),
                        result={"turn": write.ref.model_dump(mode="json"), "status": "queued"})

    def generate(self, view, envelope, auth):
        ref = ObjectRef.model_validate(envelope.command.payload["subject"])
        if ref.kind != "role_turn":
            raise ProtocolError("role_subject_invalid")
        request = RoleTurn.model_validate(view.get(ref).content)
        if request.executor != auth.executor:
            raise ProtocolError("role_executor_mismatch", status=403)
        snapshot = self.port.capture(auth, request.input, as_of=envelope.context.as_of)
        messages, omitted = snapshot.messages(auth, max_chars=self.max_context_chars)
        started = monotonic()
        try:
            response = self.model.complete(messages, [])
            response = ModelReply.model_validate(response.model_dump(mode="json"))
            if response.tool_calls or not response.text.strip():
                raise ValueError("role response must be a nonempty discussion")
        except Exception:
            raise RoleModelUnavailable("role generation unavailable; retry through the saved job") from None
        text = snapshot.scrub(response.text)
        # Source fact identifiers and raw quote/span are never model/public metadata.
        for fact in self.port.catalog.facts:
            text = text.replace(fact.id, "[来源编号]")
        if text != response.text:
            # Never save a seemingly successful reply that attempted restricted output.
            raise RoleModelUnavailable("role output failed disclosure checks")
        oid = "reply-" + digest([auth.session_id, envelope.origin_request_id])[:24]
        reply_ref = ObjectRef(session_id=auth.session_id, kind="role_reply", object_id=oid, version=1)
        selected, _ = snapshot.select_sources(auth, self.max_context_chars)
        sources = tuple({digest(bare(x.ref)): bare(x.ref) for x in selected}.values())
        usage = response.usage
        # Adapter.revision is configuration, not a verified provider response identity.
        attempt = ModelAttemptUsage(request_id=envelope.origin_request_id, attempt_id=uuid4().hex,
                    expected_model_revision=self.model.revision, provider=None, model_revision=None,
                    status="success", input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"), elapsed_seconds=monotonic() - started,
                    usage_known=usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None)
        disclosures = actual_disclosures(snapshot, auth, reply_ref, text, included_sources=selected)
        reply = RoleReply(id=oid, session_id=auth.session_id, role_id=request.input.role_id,
                          request=ref, question=snapshot.scrub(request.input.text), text=text,
                          status="completed", context_hash=snapshot.context.context_hash,
                          history_revision=snapshot.history_revision, as_of=snapshot.context.as_of,
                          model_revision=self.model.revision, source_versions=sources,
                          spoken_evidence=tuple(SpokenEvidence(label=x.fact_id, source=x.source,
                                               quote=x.quote, verification=x.verification) for x in disclosures),
                          omitted_sources=omitted, attempts=(attempt,), executor=auth.executor)
        write = object_write("role_reply", reply, visible_to=("learner", request.input.role_id))
        return Mutation(writes=(write,), result={"reply": reply_ref.model_dump(mode="json"),
                         "role_id": reply.role_id, "text": text, "status": "completed",
                         "disclosures": [], "display_ack_required": True})

    def install(self, registry):
        registry.register(Operation("turns.create", "act", TurnInput, self.enqueue))
        registry.register_job("v2.role_turn", self.generate)


def create_role_service(store, catalog, model=None, *, event_reader=None):
    from career_lab.storage.role_memory import install_role_storage
    install_role_storage(store)
    return RoleService(ContextPort(store, catalog, read_role_memory, event_reader), model)
