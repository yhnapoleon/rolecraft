from career_lab.contracts.base import Contract


class Deliverable(Contract):
    # Empty fields are permitted: a missing learner answer is evaluable, not an HTTP error.
    goal: str = ""
    owner: str = ""
    metrics: str = ""
    observation_window: str = ""
    exit_condition: str = ""
    rationale: str = ""
