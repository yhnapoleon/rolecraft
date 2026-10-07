"""Historical prototype adapter protocol, retained for reading old fixture evidence.

Do not implement this transaction/state interface for production. The formal
Gateway/V2Store/lifecycle and worker own those concerns. EvidenceReader and
RuleSnapshot in ports.py remain the usable pure evaluator boundary.
"""
from typing import Protocol
from sqlalchemy.engine import Connection
from career_lab.contracts.v2.core import AuthContext, ObjectRef, VersionPoint, FileRef
from career_lab.contracts.v2.world import WorldStateV2, SessionBindings
from career_lab.contracts.v2.workspace import RevisionCycle
from .ports import EvidenceReader, RuleSnapshot, CriterionPolicy


class ReviewAuthority(Protocol):
    def validate(self,conn:Connection,auth:AuthContext,capability:str,operation:str)->None: ...
    def protocol(self,conn:Connection,auth:AuthContext)->str: ...
    def state(self,conn:Connection,auth:AuthContext,*,lock:bool)->WorldStateV2: ...
    def bindings(self,conn:Connection,auth:AuthContext)->SessionBindings: ...
    def cycle(self,conn:Connection,auth:AuthContext,cycle_id:str)->RevisionCycle:
        """Resolve the existing initial/current open cycle; do not invent one."""
    def can_access(self,conn:Connection,auth:AuthContext,ref:ObjectRef)->bool: ...
    def reader(self,conn:Connection)->EvidenceReader: ...
    def collect(self,conn:Connection,auth:AuthContext,subjects:tuple[ObjectRef,...],
                as_of:VersionPoint,decision:str|None)->tuple[RuleSnapshot,tuple]: ...
    def policies(self,conn:Connection,evaluation:FileRef)->tuple[CriterionPolicy,...]: ...
    def commit_transition(self,conn:Connection,auth:AuthContext,before:WorldStateV2,
                          after:WorldStateV2,operation:str)->None:
        """CAS and persist the v2 workflow transition in the same transaction.

        review/feedback metadata never advances business_seq or milestones;
        submit/begin_revision change only workflow status/cycle and sequences.
        W01 owns shared events, snapshots, action boundaries and installation.
        """
