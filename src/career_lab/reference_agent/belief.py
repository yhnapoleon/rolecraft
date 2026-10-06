"""Conservative belief updates from the exact visible reply/material fragments."""
from career_lab.contracts.v2 import BeliefFact, BeliefState, Observation, digest
from .ports import PortError

VISIBLE_CHANNELS = {"material", "reply", "disclosure", "event", "attachment", "export", "fact"}
PRIVATE_CHANNELS = {"prompt", "role_prompt", "prompt_only", "private", "role_private", "model_only", "gold", "solution"}
MEMORY_CHANNELS = {"memory", "learner_memory"}

def project_observation(observation, approved_memory_hashes=()):
    """Quarantine unknown provenance; a channel name alone never authorizes memory."""
    approved = set(approved_memory_hashes)
    kept, quarantined = [], []
    for fragment in observation.visible_sources:
        if fragment.channel in PRIVATE_CHANNELS:
            raise PortError("unfiltered_observation")
        if fragment.channel in VISIBLE_CHANNELS or (fragment.channel in MEMORY_CHANNELS and digest(fragment) in approved):
            ref = fragment.ref
            if ref.quote is not None and ref.quote not in fragment.text:
                ref = ref.model_copy(update={"quote": None, "span_start": None, "span_end": None})
            kept.append(fragment.model_copy(update={"ref": ref}))
        else:
            quarantined.append({"source_hash": digest(fragment), "reason": "source_origin_unresolved"})
    return observation.model_copy(update={"visible_sources": tuple(kept)}), quarantined



def check_observation(observation, session_id, actor):
    observation = Observation.model_validate(observation)
    if observation.session_id != session_id or observation.actor != actor:
        raise PortError("observation_identity_mismatch")
    if len({t.name for t in observation.tools}) != len(observation.tools):
        raise PortError("duplicate_tool")
    for fragment in observation.visible_sources:
        ref = fragment.ref
        if ref.session_id != session_id or ref.observed_at_seq > observation.as_of.business_seq:
            raise PortError("observation_source_mismatch")
        # Role prompt and model-only memory are not learner disclosures.
        if fragment.channel in PRIVATE_CHANNELS:
            raise PortError("unfiltered_observation")
    for ref in (*observation.read_versions, *observation.events, *observation.products, *observation.tests):
        if ref.session_id != session_id:
            raise PortError("observation_reference_mismatch")
    return observation


def update_belief(previous: BeliefState | None, observation: Observation, approved_memory_hashes=()) -> BeliefState:
    """Fact IDs group claims, never retrieve authority values.

    Each statement is a verbatim observed fragment. Conflicts are conservative
    candidates (different observed wording), not semantic proof of contradiction.
    """
    observation, _ = project_observation(observation, approved_memory_hashes)
    if previous and previous.session_id != observation.session_id:
        raise PortError("belief_session_mismatch")
    if previous and any(getattr(observation.as_of, k) < getattr(previous.as_of, k)
                        for k in ("business_seq", "workspace_revision", "storage_revision")):
        raise PortError("stale_observation")
    oh = digest(observation)
    if previous and oh in previous.observation_hashes:
        return previous
    facts = list(previous.facts if previous else ())
    for fragment in observation.visible_sources:
        # These channels mean actual learner-visible evidence, not prompt membership.
        if fragment.channel not in VISIBLE_CHANNELS | MEMORY_CHANNELS:
            continue
        for fid in fragment.fact_ids:
            matches = [f for f in facts if f.id == fid]
            duplicate = next((f for f in matches if f.statement == fragment.text), None)
            if duplicate:
                refs = tuple({digest(r): r for r in (*duplicate.observed_refs, fragment.ref)}.values())
                facts[facts.index(duplicate)] = duplicate.model_copy(update={"observed_refs": refs})
                continue
            if matches:
                facts = [f.model_copy(update={"status": "conflict"}) if f.id == fid else f for f in facts]
            facts.append(BeliefFact(id=fid, status="conflict" if matches else "known",
                                    statement=fragment.text, observed_refs=(fragment.ref,)))
    return BeliefState(session_id=observation.session_id, as_of=observation.as_of,
                       facts=tuple(facts), observation_hashes=(*previous.observation_hashes, oh) if previous else (oh,))
