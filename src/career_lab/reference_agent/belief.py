"""Source-preserving local belief record; the frozen public BeliefState is unchanged."""

from pydantic import Field

from career_lab.contracts.v2.core import V2, ActualConsumption, Budget, ProtocolError, digest
from career_lab.contracts.v2.data import ActionProposal
from career_lab.contracts.v2.research import BeliefFact, BeliefState
from career_lab.contracts.v2.world import Observation


class SourcedThought(V2):
    statement: str = Field(min_length=1)
    observation_hashes: tuple[str, ...] = Field(min_length=1)


class ReferenceBelief(V2):
    goal: str
    observed: BeliefState
    unknowns: tuple[SourcedThought, ...] = ()
    hypotheses: tuple[SourcedThought, ...] = ()
    plan: tuple[ActionProposal, ...] = ()
    revision: int = Field(ge=1)
    budget: Budget
    consumption: ActualConsumption = Field(default_factory=ActualConsumption)


def observe(
    previous: ReferenceBelief | None, observation: Observation, *, goal: str, budget: Budget
) -> ReferenceBelief:
    if previous and previous.observed.session_id != observation.session_id:
        raise ProtocolError("belief_session_mismatch")
    if previous and any(
        getattr(observation.as_of, key) < getattr(previous.observed.as_of, key)
        for key in ("business_seq", "workspace_revision", "storage_revision")
    ):
        raise ProtocolError("belief_observation_stale")
    identity = digest(observation)
    if previous and identity in previous.observed.observation_hashes:
        return previous
    facts = list(previous.observed.facts if previous else ())
    for fragment in observation.visible_sources:
        if (
            fragment.fact_ids
            or fragment.audience != "learner"
            or fragment.ref.session_id != observation.session_id
            or fragment.ref.observed_at_seq > observation.as_of.business_seq
            or fragment.channel
            in {"prompt", "role_prompt", "private", "model_only", "gold", "solution"}
        ):
            raise ProtocolError("belief_observation_untrusted")
        ref = fragment.ref
        group = digest([ref.kind, ref.object_id])
        matches = [fact for fact in facts if fact.id == group]
        if any(fact.statement == fragment.text and ref in fact.observed_refs for fact in matches):
            continue
        # Changed source versions need comparison even when their text spans move.
        # This is an unresolved source change, never a semantic contradiction verdict.
        conflict = any(
            fact.statement != fragment.text
            and any(source.version != ref.version for source in fact.observed_refs)
            for fact in matches
        )
        if conflict:
            facts = [
                fact.model_copy(update={"status": "conflict"}) if fact.id == group else fact
                for fact in facts
            ]
        facts.append(
            BeliefFact(
                id=group,
                status="conflict" if conflict else "known",
                statement=fragment.text,
                observed_refs=(ref,),
            )
        )
    observed = BeliefState(
        session_id=observation.session_id,
        as_of=observation.as_of,
        facts=tuple(facts),
        observation_hashes=(*(previous.observed.observation_hashes if previous else ()), identity),
    )
    if previous:
        return previous.model_copy(update={"observed": observed, "revision": previous.revision + 1})
    return ReferenceBelief(goal=goal, observed=observed, revision=1, budget=budget)


class Deliberation(V2):
    unknowns: tuple[SourcedThought, ...] = ()
    hypotheses: tuple[SourcedThought, ...] = ()
    plan: tuple[ActionProposal, ...] = ()


def apply_deliberation(
    belief: ReferenceBelief, text: str, observation: Observation
) -> ReferenceBelief:
    notes = Deliberation.model_validate_json(text)
    observed = set(belief.observed.observation_hashes)
    if any(
        not set(thought.observation_hashes).issubset(observed)
        for thought in (*notes.unknowns, *notes.hypotheses)
    ):
        raise ProtocolError("belief_source_unobserved")
    available = {tool.name for tool in observation.tools if tool.available}
    if any(action.tool not in available for action in notes.plan):
        raise ProtocolError("belief_plan_tool_unavailable")
    # Hashes bind the thought's actual observation context, not proof of its truth.
    # Model notes never enter the verbatim observed-facts collection.
    return belief.model_copy(
        update={
            "unknowns": notes.unknowns,
            "hypotheses": notes.hypotheses,
            "plan": notes.plan,
            "revision": belief.revision + 1,
        }
    )
