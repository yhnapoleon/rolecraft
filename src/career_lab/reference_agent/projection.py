"""One source-grounded view for every model-facing text surface.

Raw steps remain restricted audit records. Only exact already-authorized text
and references enter policy history or belief; summaries require a future
explicit provenance codec rather than being trusted merely as step text.
"""
from career_lab.contracts.v2 import EvidenceRefV2, digest
from .belief import project_observation


def _identity(ref):
    return (ref.session_id, ref.kind, ref.object_id, ref.version, ref.config_version)


def safe_reference(raw, sources):
    ref = EvidenceRefV2.model_validate(raw)
    matches = [source for source in sources if _identity(source.ref) == _identity(ref)]
    if not matches:
        return None
    if ref.quote is not None and not any(ref.quote in source.text for source in matches):
        ref = ref.model_copy(update={"quote": None, "span_start": None, "span_end": None})
    return ref.model_dump(mode="json")


def model_view(context):
    current, _ = project_observation(context.observation, context.approved_memory_hashes)
    # authorized_sources is constructed only from the runner's projected observation
    # ledger, never from raw step text or arbitrary model output.
    sources = tuple({digest(source): source for source in
                     (*context.authorized_sources, *current.visible_sources)}.values())
    allowed_text = {source.text for source in sources}
    history = []
    metadata = ("id", "command_request_id", "action", "as_of", "outcome",
                "error_code", "dispatch_attempts", "observation_hash")
    for raw in context.history:
        row = {key: raw[key] for key in metadata if key in raw}
        row["observations"] = [text for text in raw.get("observations", ()) if text in allowed_text]
        row["evidence_refs"] = [safe for ref in raw.get("evidence_refs", ())
                                if (safe := safe_reference(ref, sources)) is not None]
        refs = [EvidenceRefV2.model_validate(ref) for ref in row["evidence_refs"]]
        row["disclosed_sources"] = [source.model_dump(mode="json") for source in sources
            if any(_identity(ref) == _identity(source.ref) for ref in refs)
            and source.ref.observed_at_seq <= raw.get("as_of", {}).get("business_seq", -1)]
        history.append(row)
    facts = []
    for fact in context.belief.facts:
        witnesses = [source for source in sources if source.text == fact.statement and fact.id in source.fact_ids]
        if not witnesses:
            continue
        refs = [safe for ref in fact.observed_refs
                if (safe := safe_reference(ref, witnesses)) is not None]
        if not refs:
            continue
        facts.append({**fact.model_dump(mode="json"), "observed_refs": refs})
    belief = {**context.belief.model_dump(mode="json"), "facts": facts}
    return {"observation": current.model_dump(mode="json"), "history": history, "belief": belief}
