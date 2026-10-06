"""Versioned rules. v4 business semantics are installed by W05, never aliased to v3."""
from career_lab.contracts.v2 import ProtocolError
from career_lab.rubrics.checks import run_rule_checks

class RulesRegistry:
    def __init__(self):self.engines={'rules-v3':run_rule_checks}
    def register(self,revision,engine):
        if revision in self.engines:raise ValueError('rules revision already registered')
        if revision!='rules-v4':raise ValueError('new implementation must explicitly target rules-v4')
        self.engines[revision]=engine
    def get(self,revision):
        if revision not in self.engines:
            raise ProtocolError('rules_engine_unavailable','historical rules engine unavailable; existing feedback remains readable',503)
        return self.engines[revision]

RULES=RulesRegistry()
