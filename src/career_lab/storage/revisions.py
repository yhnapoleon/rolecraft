"""Retired W05 private persistence entry point.

The historical prototype is retained only in explicit test fixtures. Production
reviews must use the common V2Store, lifecycle plans, and claimed worker. This
worktree is still pinned to the draft contract and cannot install that adapter.
"""

from career_lab.contracts.v2.core import ProtocolError


def register_tables(*args, **kwargs):
    raise ProtocolError(
        "module_unavailable", "W05 requires the fixed public V2Store input", status=503
    )


class RevisionRepository:
    def __init__(self, *args, **kwargs):
        raise ProtocolError("module_unavailable", "Private W05 persistence is retired", status=503)
