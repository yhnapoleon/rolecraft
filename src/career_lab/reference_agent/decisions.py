"""Parse a model proposal without dispatching or persisting business effects."""

from dataclasses import dataclass
from typing import Literal

from career_lab.contracts.v2.core import V2, ProtocolError, VersionPoint
from career_lab.contracts.v2.data import ActionProposal
from career_lab.contracts.v2.world import Observation
from career_lab.reference_agent.belief import ReferenceBelief, apply_deliberation
from career_lab.reference_agent.ports import OPERATIONS, canonical_tool, validate_candidate
from career_lab.runtime.model_adapter import ModelReply


class SelectedAction(V2):
    proposal: ActionProposal
    as_of: VersionPoint


@dataclass(frozen=True)
class DecisionSelection:
    belief: ReferenceBelief
    candidates: tuple[ActionProposal, ...]
    selected: ActionProposal | None


def select_decision(
    belief: ReferenceBelief,
    observation: Observation,
    reply: ModelReply,
    strategy: Literal["ordinary", "active"],
) -> DecisionSelection:
    if strategy == "active" and reply.text.strip():
        try:
            belief = apply_deliberation(belief, reply.text, observation)
        except ValueError:
            raise ProtocolError("reference_model_invalid") from None
    if not reply.tool_calls:
        return DecisionSelection(belief, (), None)
    if len(reply.tool_calls) != 1:
        raise ProtocolError("reference_one_action_required")
    call = reply.tool_calls[0]
    name = canonical_tool(call.name, observation)
    tool = next((tool for tool in observation.tools if tool.name == name), None)
    if name is None or tool is None or not tool.available or name not in OPERATIONS:
        raise ProtocolError("reference_operation_unavailable", status=403)
    proposed = ActionProposal(id=call.id, tool=name, purpose=belief.goal, arguments=call.arguments)
    candidates = belief.plan if strategy == "active" and belief.plan else (proposed,)
    matching = [
        candidate
        for candidate in candidates
        if candidate.tool == proposed.tool and candidate.arguments == proposed.arguments
    ]
    if len(matching) != 1:
        raise ProtocolError("reference_candidate_unlisted")
    try:
        for candidate in candidates:
            validate_candidate(candidate)
    except ValueError:
        raise ProtocolError("reference_candidate_invalid") from None
    return DecisionSelection(belief, candidates, matching[0])
