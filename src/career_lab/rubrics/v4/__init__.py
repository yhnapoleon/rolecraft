"""Versioned advisory evaluation; v3 implementation is never replaced."""
from .rules import run_rules

RULES_REVISION='rules-v4'
__all__=['RULES_REVISION','run_rules']
