"""L2 operation declarations; L4 owns whitelisting, routes and both registries."""

from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from career_lab.aipm.types import AipmDesign, AipmProfile, ProcessFeedbackRecord
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts.v2 import V2, AuthContext, ObjectRef, ProtocolError, canonical
from career_lab.storage.reference_graph import full_references, references
from career_lab.storage.v2_store import Mutation, ObjectWrite, TransactionView

from .rules import DesignFacts, evaluate_design, feedback_is_stale, load_rules


class DesignSaveInput(V2):
    design: AipmDesign
    expected_revision: int = Field(ge=0)


class DesignReadInput(V2):
    design_id: str
    version: int | None = Field(default=None, ge=1)


DESIGN_OBJECT_MODELS = {
    "aipm_design": AipmDesign,
    "aipm_process_feedback": ProcessFeedbackRecord,
}
FactsProvider = Callable[[TransactionView, AuthContext], DesignFacts]


def _profile(view, auth):
    matches = [r for r in view.objects if r.ref.kind == "aipm_profile"]
    if not matches:
        raise ProtocolError("aipm_not_enrolled", status=409)
    profile = AipmProfile.model_validate(matches[0].content)
    if (
        profile.session_id != auth.session_id
        or profile.scenario_hash != view.bindings.scenario.sha256
    ):
        raise ProtocolError("aipm_binding_mismatch", status=409)
    return profile


def _visible(view, auth, content):
    for ref in full_references(content):
        if ref.session_id != auth.session_id:
            raise ProtocolError("object_not_found", status=404)
        if not callable(view.reference_allowed) or not view.reference_allowed(ref):
            raise ProtocolError("object_not_found", status=404)


def _unique(values):
    ids = [value.id for value in values]
    if len(ids) != len(set(ids)):
        raise ProtocolError("aipm_duplicate_id")


def design_operations(*, rules_path: Path, facts_provider: FactsProvider) -> tuple[Operation, ...]:
    """Installer must resolve rules_path from the enrolled package, never the request.

    facts_provider returns authorized same-window public evidence and server capability
    facts. Unavailable facts deliberately produce unknown, not a fabricated rule verdict.
    """
    rules = load_rules(rules_path)

    def save(view, command, auth):
        if (
            auth.executor.kind != "human"
            or auth.actor_id != "learner"
            or "act" not in auth.capabilities
        ):
            raise ProtocolError("aipm_human_required", status=403)
        profile = _profile(view, auth)
        body = DesignSaveInput.model_validate(command.payload)
        design = body.design
        if design.session_id != auth.session_id:
            raise ProtocolError("object_not_found", status=404)
        if design.revision != body.expected_revision + 1:
            raise ProtocolError("aipm_design_revision_conflict", status=409)
        if design.prd_ref is not None and design.prd_ref.kind != "product":
            raise ProtocolError("aipm_prd_product_required")
        existing = [
            r for r in view.objects if r.ref.kind == "aipm_design" and r.ref.object_id == design.id
        ]
        previous = max(existing, key=lambda r: r.ref.version) if existing else None
        if (previous.ref.version if previous else 0) != body.expected_revision:
            raise ProtocolError("aipm_design_revision_conflict", status=409)
        for values in (design.rows, design.needs, design.stakeholders):
            _unique(values)
        prior_rows = {r["id"]: r for r in previous.content["rows"]} if previous else {}
        for row in design.rows:
            prior = prior_rows.get(row.id)
            actual = row.model_dump(mode="json", exclude={"revision", "execution_support"})
            old = (
                {k: v for k, v in prior.items() if k not in {"revision", "execution_support"}}
                if prior
                else None
            )
            required = prior["revision"] + int(actual != old) if prior else 1
            if row.revision != required:
                raise ProtocolError("aipm_row_revision_conflict", status=409)
        content = design.model_dump(mode="json")
        _visible(view, auth, content)
        facts = facts_provider(view, auth)
        _visible(
            view,
            auth,
            {
                "facts": [
                    ref.model_dump(mode="json")
                    for refs in facts.public_sources.values()
                    for ref in refs
                ]
            },
        )
        ref = ObjectRef(
            session_id=auth.session_id,
            kind="aipm_design",
            object_id=design.id,
            version=design.revision,
        )
        rows, findings = evaluate_design(content, ref, facts, rules, profile.work_language)
        content["rows"] = rows
        deps = references(content)
        writes = [
            ObjectWrite(
                ref=ref, expected_head=body.expected_revision, content=content, dependencies=deps
            )
        ]
        feedback_refs = []
        for finding in findings:
            feedback = ProcessFeedbackRecord(
                **finding, session_id=auth.session_id, content_revision=profile.content_revision
            )
            feedback_ref = ObjectRef(
                session_id=auth.session_id,
                kind="aipm_process_feedback",
                object_id=feedback.id,
                version=1,
            )
            feedback_content = feedback.model_dump(mode="json")
            writes.append(
                ObjectWrite(
                    ref=feedback_ref,
                    expected_head=0,
                    content=feedback_content,
                    dependencies=references(feedback_content),
                )
            )
            feedback_refs.append(feedback_ref.model_dump(mode="json"))
        return Mutation(
            writes=tuple(writes),
            result={
                "ref": ref.model_dump(mode="json"),
                "design": content,
                "feedback_refs": feedback_refs,
            },
        )

    def read(view, page, auth):
        _profile(view, auth)
        matches = [
            r
            for r in view.objects
            if r.ref.kind == "aipm_design" and r.ref.object_id == page.design_id
        ]
        if not matches:
            raise ProtocolError("object_not_found", status=404)
        head = max(matches, key=lambda r: r.ref.version)
        selected = (
            head
            if page.version is None
            else next((r for r in matches if r.ref.version == page.version), None)
        )
        if selected is None:
            raise ProtocolError("object_not_found", status=404)
        _visible(view, auth, selected.content)
        heads = {}
        for record in view.objects:
            key = (record.ref.kind, record.ref.object_id)
            heads[key] = max(heads.get(key, 0), record.ref.version)
        current_facts = facts_provider(view, auth)
        for refs in current_facts.public_sources.values():
            for source in refs:
                heads[(source.kind, source.object_id)] = source.version
        if current_facts.config_ref is not None:
            source = current_facts.config_ref
            heads[(source.kind, source.object_id)] = source.version
        feedback = []
        for record in view.objects:
            if record.ref.kind != "aipm_process_feedback":
                continue
            item = record.content
            if canonical(item["input_ref"]) != canonical(selected.ref):
                continue
            _visible(view, auth, item)
            stale = feedback_is_stale(selected.ref, head.ref, record.dependencies, heads)
            feedback.append(dict(item, stale=stale))
        return V2Response(
            result={
                "ref": selected.ref.model_dump(mode="json"),
                "design": selected.content,
                "feedback": feedback,
            }
        )

    return (
        Operation("aipm.design.save", "act", DesignSaveInput, save),
        Operation(
            "aipm.design.read",
            "read",
            DesignReadInput,
            read,
            mutates=False,
            response_model=V2Response,
        ),
    )
