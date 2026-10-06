"""Three strategies sharing the same visible observation and action validator."""
import json
from dataclasses import dataclass
from typing import Callable

from career_lab.contracts.v2 import ActionProposal, BeliefState, Observation, digest, canonical
from .legal import validate_action
from .ports import PortError
from .belief import project_observation
from .projection import model_view


@dataclass(frozen=True)
class PolicyContext:
    goal: str
    observation: Observation
    belief: BeliefState
    history: tuple[dict, ...]
    seed: int
    approved_memory_hashes: tuple[str, ...] = ()
    authorized_sources: tuple = ()


@dataclass(frozen=True)
class Choice:
    action: ActionProposal | None
    candidates: tuple[ActionProposal, ...] = ()
    reason: str = ""
    stop_reason: str | None = None


class ChecklistPolicy:
    name = "checklist"
    uses_model = False

    def __init__(self, actions):
        self.actions = tuple(ActionProposal.model_validate(a) for a in actions)

    def choose(self, context, call_model):
        completed = sum(x["outcome"] == "success" for x in context.history)
        if completed >= len(self.actions):
            return Choice(None, stop_reason="checklist_exhausted")
        action = self.actions[completed]
        validate_action(action, context.observation)
        return Choice(action, (action,), action.purpose)


class ToolLoopPolicy:
    name = "tool_loop"
    uses_model = True
    prompt_revision = "w09-tool-loop-v1"

    def __init__(self, prompt=None):
        self.prompt = prompt or (
            "You are responsible for the learner's task. Use only visible evidence. "
            "Choose one available tool. Return JSON: "
            '{"action":{"id":"...","tool":"...","arguments":{},"purpose":"brief observable reason"}} '
            'or {"stop":"blocked|proposed_complete","reason":"brief reason"}. '
            "Do not provide hidden reasoning. A suggested stop is not verified success."
        )

    def payload(self, context):
        view = model_view(context)
        return {"goal": context.goal, "observation": view["observation"], "history": view["history"]}

    def choose(self, context, call_model):
        messages = [{"role": "system", "content": self.prompt},
                    {"role": "user", "content": canonical(self.payload(context))}]
        text = call_model(messages)
        try:
            data = json.loads(text)
            if "stop" in data:
                if set(data) - {"stop", "reason"} or data["stop"] not in {"blocked", "proposed_complete"}:
                    raise ValueError("invalid stop")
                return Choice(None, reason=str(data.get("reason", ""))[:1000], stop_reason=data["stop"])
            if set(data) != {"action"}:
                raise ValueError("invalid choice")
            action = ActionProposal.model_validate(data["action"])
            validate_action(action, context.observation)
            return Choice(action, (action,), action.purpose[:1000])
        except (ValueError, TypeError, KeyError):
            raise PortError("invalid_model_choice") from None


class ActiveAcquisitionPolicy(ToolLoopPolicy):
    name = "active_acquisition"
    prompt_revision = "w09-acquisition-v1"

    def __init__(self, prompt=None):
        self.prompt = prompt or (
            "Use only the supplied observation, sourced belief and recorded results. "
            "Propose 1 to 8 legal information actions, each with the target unknown "
            "in purpose and estimated cost when available. Never read hidden facts. "
            'Return JSON {"candidates":[{"id":"...","tool":"...","arguments":{},'
            '"purpose":"unknown to resolve","expected_cost":null}],"selected_id":"...",'
            '"reason":"brief reason using observed information"}, or '
            '{"stop":"blocked|proposed_complete","reason":"brief reason"}. '
            "Do not reveal hidden reasoning. Candidate copy results are unavailable."
        )

    def payload(self, context):
        return super().payload(context) | {"belief": model_view(context)["belief"]}

    def choose(self, context, call_model):
        messages = [{"role": "system", "content": self.prompt},
                    {"role": "user", "content": canonical(self.payload(context))}]
        try:
            data = json.loads(call_model(messages))
            if "stop" in data:
                if set(data) - {"stop", "reason"} or data["stop"] not in {"blocked", "proposed_complete"}:
                    raise ValueError("invalid stop")
                return Choice(None, reason=str(data.get("reason", ""))[:1000], stop_reason=data["stop"])
            if set(data) != {"candidates", "selected_id", "reason"} or not 1 <= len(data["candidates"]) <= 8:
                raise ValueError("invalid candidates")
            candidates = tuple(ActionProposal.model_validate(x) for x in data["candidates"])
            if len({c.id for c in candidates}) != len(candidates):
                raise ValueError("duplicate candidates")
            for action in candidates:
                validate_action(action, context.observation)
            chosen = next(c for c in candidates if c.id == data["selected_id"])
            return Choice(chosen, candidates, str(data["reason"])[:1000])
        except (ValueError, TypeError, KeyError, StopIteration):
            raise PortError("invalid_model_choice") from None
