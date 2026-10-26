"""Engineer operations inside one practice session: the second hat.

Seven session operations are installed in the ``ExtensionRegistry`` and routed by
``v2_routes`` like other module operations, behind the same session authentication:

- ``engineer.tickets.create`` (act, person only): a scenario-supplied ticket
  (``{"from": "seeded"}``) or a hand-over of existing PM tests
  (``{"from": "tests", "test_ids": [...]}``);
- ``engineer.tickets.read`` (read): the session's tickets, or one ticket's detail;
- ``engineer.reproduce`` (act): re-run the ticket's target tests on their original snapshots;
- ``engineer.trial`` (act): run a candidate on the target questions and the public probes;
- ``engineer.submissions.draft`` (act): a candidate with its explanation and self-report;
- ``engineer.submissions.sign`` (submit, person only): sign a draft and have it reviewed;
- ``engineer.reviews.read`` (read): public review reports.

Everything executes for real with the rule-based retrieval. Nothing here writes PM business
state: configuration versions, tests, work products and submissions are untouched; records
live in the engineer directory (``session_store``). The one exception is a seeded ticket on
a session whose pilot is not live yet: the system puts it live first, labelled and kept out
of the learner's PM work (``golive.py``). Reviews and trials run the scenario's engineer
regression suite (``suite.py``), never the authored probes; a scenario without one has no
engineer path. Hidden probes run only inside the existing trusted review, and only its
public projection is ever returned. Every result stays within an Agent's tool result.
"""

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, JsonValue, RootModel, model_validator

from career_lab.api.modules import Operation
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import (
    EngineerChangeClaim,
    EngineerClaimedReport,
    EngineerPublicReport,
    EngineerSubmissionRecord,
    EngineerUnresolvedItem,
)
from career_lab.scenarios.v2.module import ScenarioModule, ref_for
from career_lab.scenarios.v2.policy import effective_config
from career_lab.storage.v2_store import TransactionView, V2Store

from .candidate import (
    EDITABLE_FIELDS,
    candidate_config,
    editable_fields,
    settings_diff,
    supported_settings,
)
from .capture import capture, package_files
from .colleague import (
    DANIEL,
    DANIEL_ACTOR,
    GRACE,
    GRACE_ACTOR,
    credential,
    facts_of,
    grace_reply,
    grace_rule,
    pick,
    rules_for,
)
from .execution import matches, run_query, suite_probes
from .files import encode, file_ref, publish, retained_documentation
from .golive import go_live, revoke
from .pack import reproduce_pack
from .review import review_configuration
from .review_evaluation import stored_evaluation
from .seeded import ORIGIN_LABELS, SEEDED_TICKETS, seed_record, seeded_ticket, tests_title
from .session_store import EngineerStore, checked, read_json, record_id, records, write_json
from .submission import submit_configuration, verified_pack
from .suite import require_suite

OP_CREATE = "engineer.tickets.create"
OP_READ = "engineer.tickets.read"
OP_REPRODUCE = "engineer.reproduce"
OP_TRIAL = "engineer.trial"
OP_DRAFT = "engineer.submissions.draft"
OP_SIGN = "engineer.submissions.sign"
OP_REVIEWS = "engineer.reviews.read"

ROLE = "engineer"
REVIEW_LIMIT = 3
EXPERIMENT_LIMIT = 50
DRAFT_LIMIT = 50
IMPACT_NOTE_LIMIT = 500
# Every result of the five Agent tools stays within an Agent's tool result: at most 20,000
# characters of MCP text in the worst case (tests/integration/test_engineer_result_size.py).
# Records keep everything; views are bounded:
HANDOVER_LIMIT = 10  # tests handed over in one ticket
DRAFT_TEXT_LIMIT = 2000  # explanation + statement reasons and values + unresolved descriptions
UNRESOLVED_LIMIT = 10
PAGE_LIMIT = 40  # tickets per listed page
# Reviews per listed page: each row names two executors (signer and draft author), so a full
# page of Agent-drafted reviews stays under the MCP result limit.
REVIEW_PAGE_LIMIT = 30
QUERY_SUMMARY = 100
ANSWER_SUMMARY = 160
EXPLANATION_SUMMARY = 160
LISTED_CITATIONS = 3
QUOTE_SUMMARY = 80
# A ticket lists up to ten target tests beside its latest draft, so each is shorter still;
# reproduction shows more of each answer.
TARGET_QUERY_SUMMARY = 80
TARGET_ANSWER_SUMMARY = 100
TARGET_QUOTE_SUMMARY = 60
# The ticket detail lists up to this many latest trials and drafts (summaries), fewer when
# the widest content would not fit; the budgets still count every record.
LISTED_TRIALS = 10
LISTED_DRAFTS = 10
DETAIL_BUDGET = 19_500
RETRIEVAL_NOTE = {
    "zh": "复现、试跑与复核固定使用规则版检索与原文抽取，保留原配置记录；不重放模型生成。",
    "en": "Reproduction, trials and reviews use rule-based retrieval and extraction. "
    "Original configurations are retained; model generation is not replayed.",
}


class _Create(C.V2):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)


class SeededTicket(_Create):
    source: Literal["seeded"] = Field(alias="from")


class TestsTicket(_Create):
    source: Literal["tests"] = Field(alias="from")
    test_ids: tuple[C.Identifier, ...] = ()
    # "colleague": Daniel takes it (a product manager's practice only); "self": the person.
    assignee: Literal["self", "colleague"] = "self"
    # The work item the tests came from, so the report lands back on it.
    task_id: C.Identifier | None = None


class RoleChoice(_Create):
    """The one role this practice is played as; written once, right after it starts."""

    source: Literal["role"] = Field(alias="from")
    role: Literal["pm", "engineer"]


class TicketDecision(_Create):
    """What happens to a colleague's report: in a product manager's practice the person asks,
    returns or records that they applied it (through ``configuration.apply`` themself); in an
    engineer's practice the person hands their signed report to Grace."""

    source: Literal["decision"] = Field(alias="from")
    ticket_id: C.Identifier
    decision: Literal["ask", "return", "apply", "handover"]
    note: Annotated[str, Field(max_length=1000)] = ""
    # For "apply": the configuration version the person's own apply produced.
    config_version: Annotated[int, Field(ge=0)] | None = None


# One body for POST .../engineer/tickets, told apart by "from"; each kind is strict on its own
# (Contract forbids extra fields), so a mixed body is a 422 rather than a guess. The operation
# registry takes a V2 model, so the union sits under ``body``: the request is wrapped as it
# arrives and its shape on the wire is unchanged.
class TicketCreate(C.V2):
    body: Annotated[
        SeededTicket | TestsTicket | RoleChoice | TicketDecision,
        Field(discriminator="source"),
    ]

    @model_validator(mode="before")
    @classmethod
    def wrap(cls, data: Any) -> Any:
        if isinstance(data, dict) and "body" not in data:
            return {"body": data}
        return data


class TicketQuery(C.V2):
    ticket_id: str | None = None
    cursor: int = 0
    limit: int = 50
    since_seq: int | None = None


class ReviewQuery(C.V2):
    review_id: str | None = None
    ticket_id: str | None = None
    cursor: int = 0
    limit: int = 50
    since_seq: int | None = None


class TicketTarget(C.V2):
    ticket_id: C.Identifier


class TrialInput(C.V2):
    ticket_id: C.Identifier
    # A difference from the ticket's baseline: supported fields only.
    changes: dict[str, JsonValue] = {}


class ChangeStatement(C.V2):
    field: str
    before: JsonValue = None
    after: JsonValue = None
    # The submitted EngineerChangeClaim keeps at most 500 characters of reason.
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class UnresolvedInput(C.V2):
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    probe_ids: tuple[C.Identifier, ...] = ()


class DraftInput(C.V2):
    ticket_id: C.Identifier
    changes: dict[str, JsonValue] = {}
    explanation: Annotated[str, Field(max_length=4000)] = ""
    change_statements: Annotated[tuple[ChangeStatement, ...], Field(max_length=20)] = ()
    claimed_results: dict[str, Literal["pass", "fail", "error"]] = {}
    unresolved: Annotated[tuple[UnresolvedInput, ...], Field(max_length=UNRESOLVED_LIMIT)] = ()


class SignInput(C.V2):
    ticket_id: C.Identifier
    draft_id: C.Identifier
    impact_note: str


class EngineerResult(RootModel[dict[str, JsonValue]]):
    """Each handler builds its own fixed shape; this only carries it out."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def executor_view(executor: C.Executor) -> dict[str, Any]:
    value = {"id": executor.id, "kind": executor.kind}
    if executor.delegation_id is not None:
        value["delegation_id"] = executor.delegation_id
    return value


def summary(text: str, limit: int = ANSWER_SUMMARY) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def size(value: Any) -> int:
    """Characters of compact JSON, as an MCP tool result carries it."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def citation_view(ref: C.EvidenceRefV2, quote: int = QUOTE_SUMMARY) -> dict[str, Any]:
    return {
        "object_id": ref.object_id,
        "version": ref.version,
        "span_start": ref.span_start,
        "span_end": ref.span_end,
        "quote": summary(ref.quote, quote) if ref.quote is not None else None,
    }


def citations_view(
    refs: Sequence[C.EvidenceRefV2], listed: int = LISTED_CITATIONS, quote: int = QUOTE_SUMMARY
) -> dict[str, Any]:
    """The first citations with short quotes, and how many there are."""
    return {
        "citations": [citation_view(ref, quote) for ref in refs[:listed]],
        "citation_count": len(refs),
    }


def draft_text(payload: "DraftInput") -> int:
    """The draft's free text, counted once across its fields."""
    return (
        len(payload.explanation)
        + sum(len(s.reason) + size(s.before) + size(s.after) for s in payload.change_statements)
        + sum(len(u.description) for u in payload.unresolved)
    )


def human_only(auth: C.AuthContext, code: str) -> None:
    if auth.executor.kind != "human" or auth.actor_id != "learner":
        raise C.ProtocolError(code, status=403)


def request_hash(payload: C.V2) -> str:
    return C.digest(payload.model_dump(mode="json"))


class EngineerService:
    def __init__(
        self,
        root: Path,
        modules: Sequence[ScenarioModule],
        apply_handler: Callable[[], Any] | None = None,
    ):
        self.files = EngineerStore(root)
        self.modules = {C.canonical(m.bindings): m for m in modules}
        # The installed configuration.apply handler, read when a seeded ticket needs the
        # pilot live (see golive.py); the registry installs it before these operations.
        self.apply_handler = apply_handler

    # Session, module and ticket lookup ---------------------------------------------------

    def module(self, bindings: C.SessionBindings) -> ScenarioModule:
        module = self.modules.get(C.canonical(bindings))
        if module is None:
            raise C.ProtocolError("scenario_read_only", status=409)
        return module

    def bound_module(self, store: V2Store, auth: C.AuthContext, operation: str) -> ScenarioModule:
        return self.module(store.query(auth, lambda view: view.bindings, operation=operation))

    def ticket(self, session_id: str, ticket_id: str) -> tuple[Path, dict[str, Any]]:
        folder = self.files.ticket(session_id, ticket_id)
        path = folder / "ticket.json"
        if not path.is_file():
            raise C.ProtocolError("engineer_ticket_not_found", status=404)
        ticket = read_json(path)
        if ticket.get("session_id") != session_id or ticket.get("id") != ticket_id:
            raise C.ProtocolError("engineer_ticket_not_found", status=404)
        return folder, ticket

    def seeds(self, folder: Path, ticket: dict[str, Any]) -> tuple[C.TestResultV2, ...]:
        expected = ticket.get("seed_test_sha256")
        if expected is None:
            return ()
        raw = (folder / "seed-test.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise C.ProtocolError("engineer_ticket_changed", status=409)
        return (C.TestResultV2.model_validate_json(raw),)

    def pack(self, folder: Path, ticket: dict[str, Any]):
        root = folder / "pack"
        raw = (root / "index.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != ticket["pack_index_sha256"]:
            raise C.ProtocolError("engineer_ticket_changed", status=409)
        index, pack, _ = retained_documentation(root)
        tests = tuple(C.TestResultV2.model_validate_json(C.read_file(root, r)) for r in index.tests)
        baseline = C.AssistantConfig.model_validate_json(C.read_file(root, index.config))
        probes = json.loads(C.read_file(root, index.public_probes))
        return index, pack, tests, baseline, probes

    # Ticket creation ---------------------------------------------------------------------

    def create_ticket(
        self, store: V2Store, payload: TicketCreate, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        human_only(auth, "engineer_ticket_requires_human")
        body = payload.body
        if isinstance(body, RoleChoice):
            return self.set_role(store, body, auth)
        if isinstance(body, TicketDecision):
            return self.decide(store, body, auth, request_id)
        colleague = isinstance(body, TestsTicket) and body.assignee == "colleague"
        if colleague and self.learner_role(auth.session_id) != "pm":
            # Daniel takes tickets only in a product manager's practice; an engineer's practice
            # (or one with no role yet, an older one) keeps its own desk.
            raise C.ProtocolError("assignee_not_allowed", status=409)
        result = self.open_ticket(store, body, auth)
        if colleague:
            result["ticket"] = self.run_daniel(store, auth, result["ticket"]["id"], request_id)
        return result

    def open_ticket(
        self, store: V2Store, payload: "SeededTicket | TestsTicket", auth: C.AuthContext
    ) -> dict[str, Any]:
        module = self.bound_module(store, auth, OP_CREATE)
        # Without an engineer suite the review would run authored probes with their own
        # preconditions under one configuration: false regressions. No engineer path then.
        require_suite(module.package)
        sid = auth.session_id
        colleague = isinstance(payload, TestsTicket) and payload.assignee == "colleague"
        if payload.source == "seeded":
            _, query = seeded_ticket(module)
            ticket_id = record_id("ticket", [sid, "seeded", module.package.bundle.id, query])
        else:
            ids = sorted(set(payload.test_ids))
            if not ids:
                raise C.ProtocolError("engineer_test_selection_required")
            if len(ids) > HANDOVER_LIMIT:
                raise C.ProtocolError(
                    "engineer_test_selection_too_large",
                    f"at most {HANDOVER_LIMIT} tests per ticket",
                )
            # Daniel's ticket is its own: the same tests handed to him are not the person's.
            ticket_id = record_id(
                "ticket", [sid, "tests", ids, *(["colleague"] if colleague else [])]
            )
        folder = self.files.ticket(sid, ticket_id)
        with self.files.lock(sid, "tickets"):
            if (folder / "ticket.json").is_file():
                return {"ticket": self.detail(module, sid, ticket_id), "created": False}
            if folder.exists():
                # A creation that stopped before its record: our own unfinished staging.
                shutil.rmtree(folder)
            self.check_baseline(store, module, auth)
            seed = setup = None
            if payload.source == "seeded":
                setup = self.world_setup(store, module, auth)
                files, seed = self.capture_seeded(store, module, auth, query, ticket_id)
            else:
                files = capture(store, module, auth, ids, operation=OP_CREATE)
            publish(folder / "pack", files)
            seed_sha = None
            if seed is not None:
                raw = encode(seed)
                (folder / "seed-test.json").write_bytes(raw)
                seed_sha = hashlib.sha256(raw).hexdigest()
            pack = json.loads(files["pack.json"])
            write_json(
                folder / "ticket.json",
                {
                    "schema_version": 1,
                    "kind": "engineer_ticket",
                    "id": ticket_id,
                    "session_id": sid,
                    "source": payload.source,
                    "scenario": module.package.bundle.id,
                    "work_language": module.work_language,
                    "created_at": now(),
                    "created_by": executor_view(auth.executor),
                    "role": ROLE,
                    "pack_id": pack["id"],
                    "pack_index_sha256": hashlib.sha256(files["index.json"]).hexdigest(),
                    "target_test_ids": [ref["object_id"] for ref in pack["failures"]],
                    "seed_test_sha256": seed_sha,
                    "world_setup": setup,
                    "assignee": "colleague" if colleague else "self",
                    **(
                        {
                            "origin": {
                                "task_id": payload.task_id,
                                "test_ids": ids,
                            },
                            "handover": {"state": "queued", "decisions": []},
                        }
                        if colleague
                        else {}
                    ),
                },
            )
        return {"ticket": self.detail(module, sid, ticket_id), "created": True}

    # The practice's one role -------------------------------------------------------------
    # Kept in the engineer directory beside the tickets: the session record has no role field
    # and the public contract stays unchanged. Debt: it belongs with the session's bindings
    # (v2_sessions) once the contract moves; see the 223 receipt.

    def role_path(self, sid: str) -> Path:
        return self.files.session(sid) / "learner-role.json"

    def learner_role(self, sid: str) -> str | None:
        path = self.role_path(sid)
        return read_json(path).get("role") if path.is_file() else None

    def set_role(self, store: V2Store, payload: RoleChoice, auth: C.AuthContext) -> dict[str, Any]:
        self.bound_module(store, auth, OP_CREATE)
        sid = auth.session_id
        with self.files.lock(sid, "role"):
            current = self.learner_role(sid)
            if current is not None and current != payload.role:
                raise C.ProtocolError("learner_role_fixed", status=409)
            if current is None:
                path = self.role_path(sid)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json(
                    path,
                    {
                        "schema_version": 1,
                        "role": payload.role,
                        "set_at": now(),
                        "set_by": executor_view(auth.executor),
                    },
                )
        return {"learner_role": payload.role, "created": current is None}

    # Daniel: the rule orchestration ------------------------------------------------------

    def handover_state(self, sid: str, ticket_id: str, **changes: Any) -> dict[str, Any]:
        folder, ticket = self.ticket(sid, ticket_id)
        ticket["handover"] = {**ticket.get("handover", {}), **changes}
        write_json(folder / "ticket.json", ticket)
        return ticket["handover"]

    def run_daniel(
        self, store: V2Store, owner: C.AuthContext, ticket_id: str, request_id: str
    ) -> dict[str, Any]:
        """Reproduce, try candidates from the rule table, draft and sign as Daniel, through the
        ordinary engineer tools and the same trusted review. A run that cannot finish says so
        (failed with a reason); it is never dressed up as a report."""
        module = self.bound_module(store, owner, OP_CREATE)
        sid = owner.session_id
        folder, ticket = self.ticket(sid, ticket_id)
        state = ticket.get("handover", {}).get("state")
        if state in (
            "reproducing",
            "trying",
            "signing",
            "reported",
            "applied",
            "applied_with_changes",
        ):
            return self.detail(module, sid, ticket_id)
        language = ticket["work_language"]
        auth = credential(
            store,
            owner,
            DANIEL,
            ("read", "act", "submit"),
            (OP_READ, OP_REPRODUCE, OP_TRIAL, OP_DRAFT, OP_SIGN),
        )
        run = f"{request_id}-daniel-{len(ticket.get('handover', {}).get('runs', []))}"
        try:
            self.handover_state(sid, ticket_id, state="reproducing", started_at=now())
            self.reproduce(store, TicketTarget(ticket_id=ticket_id), auth, run + "-reproduce")
            index, pack_files = verified_pack(
                store,
                module,
                auth,
                folder / "pack",
                seeded=self.seeds(folder, ticket),
                operation=OP_TRIAL,
            )
            targets = [C.TestResultV2.model_validate_json(pack_files[r.path]) for r in index.tests]
            baseline = C.AssistantConfig.model_validate_json(pack_files[index.config.path])
            rules = rules_for(facts_of(targets))
            if not rules:
                return self.daniel_failed(module, sid, ticket_id, "no_rule")
            self.handover_state(sid, ticket_id, state="trying")
            tried, skipped = [], []
            for rule in rules:
                try:
                    candidate_config(module.package, baseline, dict(rule.changes), sid)
                except C.ProtocolError as error:
                    skipped.append({"rule": rule.id, "code": error.code})
                    continue
                out = self.trial(
                    store,
                    TrialInput(ticket_id=ticket_id, changes=dict(rule.changes)),
                    auth,
                    f"{run}-trial-{rule.id}",
                )["trial"]
                tried.append((rule, out))
            if not tried:
                return self.daniel_failed(module, sid, ticket_id, "no_valid_candidate", skipped)
            rule, chosen = pick(tried)
            public = [row for row in chosen["rows"] if row["kind"] == "public_probe"]
            failing = [row["id"] for row in public if row["result"] != "pass"]
            changes = chosen["changes"]
            self.handover_state(sid, ticket_id, state="signing")
            draft = self.draft(
                store,
                DraftInput(
                    ticket_id=ticket_id,
                    changes=dict(rule.changes),
                    explanation=rule.why[language],
                    change_statements=tuple(
                        ChangeStatement(
                            field=name,
                            before=value["before"],
                            after=value["after"],
                            reason=rule.why[language][:500],
                        )
                        for name, value in changes.items()
                    ),
                    claimed_results={
                        row["id"]: (
                            "pass"
                            if row["result"] == "pass"
                            else "error"
                            if row["result"] == "error"
                            else "fail"
                        )
                        for row in public
                    },
                    unresolved=tuple(
                        UnresolvedInput(
                            description=(
                                "这条公开检查在这个改动下仍未通过。"
                                if language == "zh"
                                else "This public check still fails with this change."
                            ),
                            probe_ids=(probe,),
                        )
                        for probe in failing[:UNRESOLVED_LIMIT]
                    ),
                ),
                auth,
                run + "-draft",
            )["draft"]
            signed = self._sign(
                store,
                SignInput(
                    ticket_id=ticket_id,
                    draft_id=draft["id"],
                    impact_note=rule.why[language][:IMPACT_NOTE_LIMIT],
                ),
                auth,
                run + "-sign",
                actor=DANIEL_ACTOR,
            )
            self.handover_state(
                sid,
                ticket_id,
                state="reported",
                actor=DANIEL_ACTOR,
                rule={"id": rule.id, "why": rule.why[language], "changes": changes},
                tried=[
                    {
                        "rule": r.id,
                        "trial_id": t["id"],
                        "changes": t["changes"],
                        "counts": t["counts"],
                    }
                    for r, t in tried
                ],
                skipped=skipped,
                review_id=signed["signoff"]["review_id"],
                review_status=signed["review"]["status"],
                reported_at=now(),
            )
        except C.ProtocolError as error:
            return self.daniel_failed(module, sid, ticket_id, error.code)
        finally:
            revoke(store, auth)
        return self.detail(module, sid, ticket_id)

    def daniel_failed(
        self,
        module: ScenarioModule,
        sid: str,
        ticket_id: str,
        reason: str,
        skipped: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.handover_state(
            sid,
            ticket_id,
            state="failed",
            failed_reason=reason,
            actor=DANIEL_ACTOR,
            skipped=skipped or [],
            failed_at=now(),
        )
        return self.detail(module, sid, ticket_id)

    # Decisions on a colleague's report ---------------------------------------------------

    def decide(
        self, store: V2Store, payload: TicketDecision, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        module = self.bound_module(store, auth, OP_CREATE)
        sid = auth.session_id
        role = self.learner_role(sid)
        folder, ticket = self.ticket(sid, payload.ticket_id)
        if payload.decision == "handover":
            if role != "engineer" or ticket.get("assignee") == "colleague":
                raise C.ProtocolError("decision_not_allowed", status=409)
            return self.grace_handover(store, module, auth, ticket, request_id)
        if role != "pm" or ticket.get("assignee") != "colleague":
            raise C.ProtocolError("decision_not_allowed", status=409)
        handover = ticket.get("handover", {})
        if handover.get("state") not in ("reported", "applied", "applied_with_changes", "returned"):
            raise C.ProtocolError("handover_not_reported", status=409)
        config = store.query(auth, lambda view: module.snapshot(view).config, operation=OP_CREATE)
        current = config.config_version
        entry: dict[str, Any] = {
            "decision": payload.decision,
            "note": payload.note,
            "at": now(),
            "by": executor_view(auth.executor),
            "config_version": current,
        }
        if payload.decision == "apply":
            # The person applied it themself through configuration.apply; this records that the
            # current configuration is the one their apply produced, and that it carries the
            # report's change. Every setting the report changed must have the report's value
            # (otherwise 409: the record would claim a change that is not there); settings the
            # report left alone but the person also changed are listed, as "applied_with_changes".
            if payload.config_version is None or payload.config_version != current:
                raise C.ProtocolError("config_version_mismatch", status=409)
            entry.update(self.compare_with_report(folder, config))
        state = {"apply": "applied", "return": "returned"}.get(payload.decision, handover["state"])
        if entry.get("result") == "applied_with_changes":
            state = "applied_with_changes"
        with self.files.lock(sid, payload.ticket_id):
            self.handover_state(
                sid,
                payload.ticket_id,
                state=state,
                decisions=[*handover.get("decisions", []), entry],
            )
        return {"ticket": self.detail(module, sid, payload.ticket_id), "decision": entry}

    def compare_with_report(self, folder: Path, config: C.AssistantConfig) -> dict[str, Any]:
        signoffs = self.signoffs(folder)
        if not signoffs:
            raise C.ProtocolError("handover_not_reported", status=409)
        draft = read_json(folder / "drafts" / (signoffs[-1]["draft_id"] + ".json"))
        reported = supported_settings(C.AssistantConfig.model_validate(draft["candidate"]))
        now_settings = supported_settings(config)
        changed = set(draft["changes"])
        missing = sorted(name for name in changed if now_settings[name] != reported[name])
        if missing:
            raise C.ProtocolError(
                "config_not_from_report",
                "the current configuration does not carry the report's change: "
                + ", ".join(missing),
                status=409,
            )
        extra = {
            name: {"report": reported[name], "current": now_settings[name]}
            for name in sorted(set(EDITABLE_FIELDS) - changed)
            if now_settings[name] != reported[name]
        }
        return {
            "result": "applied_with_changes" if extra else "applied",
            "review_id": signoffs[-1]["review_id"],
            "other_changes": extra,
        }

    def grace_handover(
        self,
        store: V2Store,
        module: ScenarioModule,
        owner: C.AuthContext,
        ticket: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        """Grace takes the person's latest signed report for the product side and decides by
        rule (colleague.grace_rule). Applying goes through configuration.apply as Grace, with
        the same version check as anyone's apply; the events say Grace applied it."""
        sid = owner.session_id
        folder = self.files.ticket(sid, ticket["id"])
        signoffs = self.signoffs(folder)
        if not signoffs:
            raise C.ProtocolError("handover_needs_signoff", status=409)
        last = signoffs[-1]
        language = ticket["work_language"]
        evaluation = stored_evaluation(self.files.private_reviews(sid), last["review_id"])
        decision = grace_rule(evaluation.model_dump(mode="json"), last["review_status"])
        decision.update(review_id=last["review_id"], actor=GRACE_ACTOR, at=now())
        if decision["result"] == "applied":
            draft = read_json(folder / "drafts" / (last["draft_id"] + ".json"))
            index, pack_files = verified_pack(
                store,
                module,
                owner,
                folder / "pack",
                seeded=self.seeds(folder, ticket),
                operation=OP_CREATE,
            )
            built_on = C.AssistantConfig.model_validate_json(pack_files[index.config.path])
            applied = self.grace_apply(store, module, owner, built_on, draft, language)
            if applied is None:
                decision.update(result="returned", reasons=["config_moved"])
            else:
                decision.update(applied)
        decision["reply"] = grace_reply(language, decision)
        handover = ticket.get("handover", {})
        with self.files.lock(sid, ticket["id"]):
            self.handover_state(
                sid,
                ticket["id"],
                state=decision["result"],
                receiver=GRACE_ACTOR,
                decisions=[*handover.get("decisions", []), decision],
            )
        return {"ticket": self.detail(module, sid, ticket["id"]), "decision": decision}

    def grace_apply(
        self,
        store: V2Store,
        module: ScenarioModule,
        owner: C.AuthContext,
        built_on: C.AssistantConfig,
        draft: dict[str, Any],
        language: str,
    ) -> dict[str, Any] | None:
        """None when the configuration moved since the report was built (version check)."""

        def current(view: TransactionView):
            return view.state, module.snapshot(view).config

        state, config = store.query(owner, current, operation=OP_CREATE)
        if config.config_version != built_on.config_version:
            return None
        settings = C.AssistantConfig.model_validate(draft["candidate"]).model_dump(mode="json")
        before, after = config.config_version, config.config_version + 1
        note = {
            "origin": "colleague_apply",
            "note": (
                f"已由 Grace 应用，配置从 v{before} 变为 v{after}"
                if language == "zh"
                else f"Applied by Grace: configuration v{before} → v{after}"
            ),
            "actor": GRACE_ACTOR,
        }
        command = C.Command(
            schema_version=2,
            request_id=f"grace-apply-{draft['id']}",
            operation="configuration.apply",
            payload={
                "base": ref_for("config", config).model_dump(mode="json"),
                "settings": {name: settings[name] for name in EDITABLE_FIELDS},
            },
            expected_version=state.business_seq,
            expected_workspace_revision=state.workspace_revision,
        )
        handler = self.apply_handler()

        def labelled(view: TransactionView, cmd: C.Command, auth: C.AuthContext):
            mutation = handler(view, cmd, auth)
            events = tuple(
                event.model_copy(update={"data": {**event.data, **note}})
                for event in mutation.events
            )
            return replace(mutation, events=events)

        context = credential(
            store, owner, GRACE, ("read", "act"), ("configuration.apply", "apply_config")
        )
        try:
            store.execute(context, command, labelled, capability="act")
        finally:
            revoke(store, context)
        return {"from_version": before, "to_version": after}

    @staticmethod
    def check_baseline(store: V2Store, module: ScenarioModule, auth: C.AuthContext) -> None:
        """The current settings must be a valid engineer candidate themselves: otherwise every
        trial is refused, and the ticket view would not stay within its bound."""
        config = store.query(auth, lambda view: module.snapshot(view).config, operation=OP_CREATE)
        try:
            candidate_config(module.package, config, {}, auth.session_id)
        except C.ProtocolError:
            raise C.ProtocolError("engineer_baseline_unsupported", status=409) from None

    def world_setup(
        self, store: V2Store, module: ScenarioModule, auth: C.AuthContext
    ) -> dict[str, Any] | None:
        """The pilot goes live by the system when the world has not reached the ticket yet."""
        if self.apply_handler is None:
            raise C.ProtocolError("module_unavailable", status=503)
        return go_live(store, module, self.apply_handler(), auth, OP_CREATE)

    def capture_seeded(
        self,
        store: V2Store,
        module: ScenarioModule,
        auth: C.AuthContext,
        query: str,
        ticket_id: str,
    ) -> tuple[dict[str, bytes], C.TestResultV2]:
        def read(view: TransactionView) -> tuple[dict[str, bytes], C.TestResultV2]:
            seed = seed_record(view, module, auth, query, "engineer-seed-" + ticket_id, OP_CREATE)
            snapshot = module.snapshot(view)
            config_ref = ref_for("config", snapshot.config)
            for ref in (config_ref, seed.config_ref, *seed.citations):
                if not view.reference_allowed(ref):
                    raise C.ProtocolError("engineer_source_unavailable", status=404)
            return package_files(view, module, auth, snapshot, [seed], config_ref, None), seed

        return store.query(auth, read, operation=OP_CREATE)

    # Reads -------------------------------------------------------------------------------

    def read_tickets(
        self, view: TransactionView, payload: TicketQuery, auth: C.AuthContext
    ) -> dict[str, Any]:
        module = self.module(view.bindings)
        sid = auth.session_id
        role = self.learner_role(sid)
        if payload.ticket_id is not None:
            return {
                "ticket": self.detail(
                    module, sid, payload.ticket_id, view, include_rows=auth.executor.kind == "human"
                ),
                "learner_role": role,
            }
        folder = self.files.tickets(sid)
        rows = []
        if folder.is_dir():
            for path in sorted(folder.glob("ticket-*/ticket.json")):
                ticket = read_json(path)
                if ticket.get("session_id") == sid:
                    rows.append(self.ticket_summary(ticket))
        rows.sort(key=lambda row: (row["created_at"], row["id"]))
        return {
            "tickets": rows[
                payload.cursor : payload.cursor + max(1, min(payload.limit, PAGE_LIMIT))
            ],
            "learner_role": role,
        }

    def ticket_summary(self, ticket: dict[str, Any]) -> dict[str, Any]:
        language = ticket["work_language"]
        return {
            "id": ticket["id"],
            "source": ticket["source"],
            "title": self.title(ticket),
            "work_language": language,
            "created_at": ticket["created_at"],
            "created_by": ticket["created_by"],
            "role": ticket["role"],
            "assignee": ticket.get("assignee", "self"),
            **(
                {"handover": ticket["handover"], "origin": ticket.get("origin")}
                if "handover" in ticket
                else {}
            ),
        }

    def title(self, ticket: dict[str, Any]) -> str:
        language = ticket["work_language"]
        if ticket["source"] == "seeded":
            return SEEDED_TICKETS[ticket["scenario"]]["title"][language]
        return tests_title(language, len(ticket["target_test_ids"]))

    def detail(
        self,
        module: ScenarioModule,
        sid: str,
        ticket_id: str,
        view: TransactionView | None = None,
        *,
        include_rows: bool = True,
    ) -> dict[str, Any]:
        folder, ticket = self.ticket(sid, ticket_id)
        index, pack, tests, baseline, probes = self.pack(folder, ticket)
        seeds = {t.id for t in self.seeds(folder, ticket)}
        if view is not None:
            # The same scope as the normal test list: an Agent limited to some objects
            # cannot read a ticket built on records outside its grant.
            for ref in (pack.config, *(r for t in tests for r in (t.config_ref, *t.citations))):
                if not view.reference_allowed(ref):
                    raise C.ProtocolError("engineer_source_unavailable", status=404)
        language = ticket["work_language"]
        signoffs = self.signoffs(folder)
        trials, drafts = self.ordered(folder / "trials"), self.ordered(folder / "drafts")
        baseline_settings = supported_settings(baseline)
        view = {
            **self.ticket_summary(ticket),
            # The system's go-live for this ticket, if it had to run one; never learner work.
            "world_setup": ticket.get("world_setup"),
            "target_tests": [
                self.target_view(
                    t,
                    "ticket_seed" if t.id in seeds else "learner_test",
                    language,
                    baseline_settings,
                )
                for t in tests
            ],
            "public_probes": [{"id": p["id"], "query": p["query"]} for p in probes],
            "baseline_config": baseline_settings,
            "editable_fields": editable_fields(module.package),
            "review_budget": self.budget(signoffs),
            "experiment_budget": {"used": len(trials), "limit": EXPERIMENT_LIMIT},
            "draft_budget": {"used": len(drafts), "limit": DRAFT_LIMIT},
            "retrieval": {"mode": "rule_based", "note": RETRIEVAL_NOTE[language]},
            "trials": [
                self.trial_summary(row, include_rows=include_rows)
                for row in trials[-LISTED_TRIALS:]
            ],
            "drafts": [self.draft_summary(row) for row in drafts[-LISTED_DRAFTS:]],
            # The person signs what they can read: the latest draft in full.
            "latest_draft": self.draft_view(drafts[-1]) if drafts else None,
            "reviews": [self.review_summary(row) for row in signoffs],
        }
        return self.fit(view)

    @staticmethod
    def fit(view: dict[str, Any]) -> dict[str, Any]:
        """Drop the oldest listed trial or draft summary until the detail fits its budget."""
        trials, drafts = view["trials"], view["drafts"]
        # Preserve the run identities/settings before dropping any summary. Newest public
        # rows take priority; a bounded response explicitly marks omitted older details.
        for trial in trials:
            if size(view) <= DETAIL_BUDGET:
                break
            if "rows" in trial:
                trial.pop("rows")
                trial["rows_omitted"] = True
        while size(view) > DETAIL_BUDGET and (trials or drafts):
            oldest = (
                trials
                if trials and (not drafts or trials[0]["created_at"] <= drafts[0]["created_at"])
                else drafts
            )
            oldest.pop(0)
        return view

    def target_view(
        self,
        test: C.TestResultV2,
        origin: str,
        language: str,
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """One target test, bounded: short question and answer, its first citation, the
        versions it used, the sources whose index lags, and how its settings differ from the
        ticket baseline. Reproduction shows more of each answer."""
        execution = test.execution
        lagging = {
            key
            for key, version in execution.source_versions.items()
            if execution.indexed_versions.get(key) != version
        }
        requested = supported_settings(test.config.requested)
        return {
            "test_id": test.id,
            "origin": origin,
            "origin_label": ORIGIN_LABELS[origin][language],
            "executor": executor_view(execution.executor),
            "query": summary(test.query, TARGET_QUERY_SUMMARY),
            "status": test.status,
            "error_code": test.error_code,
            "answer_summary": summary(test.answer, TARGET_ANSWER_SUMMARY),
            **citations_view(test.citations, 1, TARGET_QUOTE_SUMMARY),
            "source_versions": {
                k: v for k, v in sorted(execution.source_versions.items()) if k in lagging
            },
            "indexed_versions": {
                k: v for k, v in sorted(execution.indexed_versions.items()) if k in lagging
            },
            "used_versions": dict(execution.used_versions),
            "config_version": test.config_ref.config_version,
            "config": {
                "same_as_baseline": requested == baseline,
                "changed_fields": [k for k in EDITABLE_FIELDS if requested[k] != baseline[k]],
                "differences": dict(test.config.differences),
            },
        }

    @staticmethod
    def ordered(folder: Path) -> list[dict[str, Any]]:
        return sorted(records(folder), key=lambda row: (row["created_at"], row["id"]))

    def signoffs(self, folder: Path) -> list[dict[str, Any]]:
        rows = self.ordered(folder / "signoffs")
        return [self.with_author(folder, row) for row in rows if row["state"] == "complete"]

    @staticmethod
    def with_author(folder: Path, row: dict[str, Any]) -> dict[str, Any]:
        """A sign-off written before the draft's author was kept reads it from the draft."""
        if "draft_executor" not in row:
            draft = read_json(folder / "drafts" / (row["draft_id"] + ".json"))
            row["draft_executor"] = draft["executor"]
        return row

    @staticmethod
    def budget(signoffs: list[dict[str, Any]]) -> dict[str, int]:
        return {"used": len({row["review_id"] for row in signoffs}), "limit": REVIEW_LIMIT}

    @staticmethod
    def trial_summary(row: dict[str, Any], *, include_rows: bool = True) -> dict[str, Any]:
        """A listed experiment: each changed setting with its ticket-baseline value and the
        value tried, with the same public rows returned to its executor."""
        return {
            **{
                key: row[key]
                for key in ("id", "kind", "executor", "role", "created_at", "config_hash")
            },
            "changed_fields": list(row["changes"]),
            "changes": row["changes"],
            **(
                {"rows": row["rows"], "effective_differences": row.get("effective_differences", {})}
                if include_rows
                else {}
            ),
            **{key: row[key] for key in ("counts", "status")},
        }

    @staticmethod
    def draft_view(row: dict[str, Any]) -> dict[str, Any]:
        """A whole draft as written; the full candidate configuration stays in the record."""
        return {
            key: value for key, value in row.items() if key not in {"request_hash", "candidate"}
        }

    @staticmethod
    def draft_summary(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **{key: row[key] for key in ("id", "executor", "role", "created_at", "config_hash")},
            "changed_fields": list(row["changes"]),
            "explanation_summary": summary(row["explanation"], EXPLANATION_SUMMARY),
            "claimed": bool(row["claimed_results"]),
            "unresolved_count": len(row["unresolved"]),
        }

    @staticmethod
    def review_summary(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "review_id": row["review_id"],
            "status": row["review_status"],
            "signed_at": row["signed_at"],
            "signed_by": row["signed_by"],
            # An AI colleague who signed under its own executor (Daniel); absent for the person,
            # whose review keeps its shape.
            **({"actor": row["actor"]} if row.get("actor") else {}),
            "draft_id": row["draft_id"],
            # Who wrote the draft the person signed: the person or their Agent.
            "draft_executor": row["draft_executor"],
        }

    # Experiments -------------------------------------------------------------------------

    def experiment(
        self,
        folder: Path,
        kind: str,
        payload: C.V2,
        auth: C.AuthContext,
        request_id: str,
    ) -> tuple[Path, dict[str, Any] | None]:
        """A request ID names one experiment of one executor; a retry returns it again."""
        identity = record_id("trial", [folder.name, kind, executor_view(auth.executor), request_id])
        path = folder / "trials" / (identity + ".json")
        if path.is_file():
            existing = read_json(path)
            if existing["request_hash"] != request_hash(payload):
                raise C.ProtocolError("engineer_request_id_reused", status=409)
            return path, existing
        if len(records(folder / "trials")) >= EXPERIMENT_LIMIT:
            raise C.ProtocolError("engineer_trial_limit_reached", status=409)
        return path, None

    def reproduce(
        self, store: V2Store, payload: TicketTarget, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        module = self.bound_module(store, auth, OP_REPRODUCE)
        sid = auth.session_id
        folder, ticket = self.ticket(sid, payload.ticket_id)
        with self.files.lock(sid, payload.ticket_id):
            path, existing = self.experiment(folder, "reproduce", payload, auth, request_id)
            if existing is not None:
                return {"reproduction": self.public_experiment(existing)}
            output = folder / "reproductions" / path.stem
            done = reproduce_pack(
                store,
                module,
                auth,
                folder / "pack",
                output,
                seeded=self.seeds(folder, ticket),
                operation=OP_REPRODUCE,
            )
            report = read_json(output / "report.json")
            rows = [
                {
                    "test_id": row["source_test"]["object_id"],
                    "query": summary(row["recorded"]["query"], QUERY_SUMMARY),
                    "matches_record": row["matches_record"],
                    "recorded": self.behavior(row["recorded"]),
                    "reproduced": self.behavior(row["reproduced"]),
                }
                for row in report["results"]
            ]
            matched = sum(row["matches_record"] for row in rows)
            record = {
                "id": path.stem,
                "kind": "reproduce",
                "ticket_id": payload.ticket_id,
                "request_hash": request_hash(payload),
                "executor": executor_view(auth.executor),
                "role": ROLE,
                "created_at": now(),
                "config_hash": None,
                "changes": {},
                "status": done["status"],
                "counts": {"matched": matched, "changed": len(rows) - matched, "total": len(rows)},
                "mode": report["mode"],
                "rows": rows,
            }
            write_json(path, record)
        return {"reproduction": self.public_experiment(record)}

    @staticmethod
    def behavior(value: dict[str, Any]) -> dict[str, Any]:
        refs = value["citations"]
        return {
            "status": value["status"],
            "error_code": value["error_code"],
            "answer_summary": summary(value["answer"]),
            "citations": [
                {
                    "object_id": ref.get("object_id"),
                    "version": ref.get("version"),
                    "quote": summary(ref["quote"], QUOTE_SUMMARY) if ref.get("quote") else None,
                }
                for ref in refs[:LISTED_CITATIONS]
            ],
            "citation_count": len(refs),
        }

    @staticmethod
    def public_experiment(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "request_hash"}

    def trial(
        self, store: V2Store, payload: TrialInput, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        module = self.bound_module(store, auth, OP_TRIAL)
        sid = auth.session_id
        folder, ticket = self.ticket(sid, payload.ticket_id)
        with self.files.lock(sid, payload.ticket_id):
            path, existing = self.experiment(folder, "trial", payload, auth, request_id)
            if existing is not None:
                return {"trial": self.public_experiment(existing)}
            index, pack_files = verified_pack(
                store,
                module,
                auth,
                folder / "pack",
                seeded=self.seeds(folder, ticket),
                operation=OP_TRIAL,
            )
            baseline = C.AssistantConfig.model_validate_json(pack_files[index.config.path])
            candidate = candidate_config(module.package, baseline, dict(payload.changes), sid)
            snapshot = store.query_at(auth, index.source.as_of, module.snapshot, operation=OP_TRIAL)
            resolved = effective_config(module.package, candidate, snapshot.world.resources)
            targets = [
                C.TestResultV2.model_validate_json(pack_files[ref.path]) for ref in index.tests
            ]
            rows = self.trial_rows(module, replace(snapshot, config=candidate), auth, targets, path)
            counts = {
                outcome: sum(row["result"] == outcome for row in rows)
                for outcome in ("pass", "fail", "error", "unchecked")
            }
            record = {
                "id": path.stem,
                "kind": "trial",
                "ticket_id": payload.ticket_id,
                "request_hash": request_hash(payload),
                "executor": executor_view(auth.executor),
                "role": ROLE,
                "created_at": now(),
                "config_hash": C.digest(resolved.effective),
                "changes": settings_diff(baseline, candidate),
                "effective_differences": dict(resolved.differences),
                "status": "completed",
                "counts": {
                    "passed": counts["pass"],
                    "failed": counts["fail"],
                    "errors": counts["error"],
                    "unchecked": counts["unchecked"],
                    "total": len(rows),
                },
                "rows": rows,
            }
            write_json(path, record)
        return {"trial": self.public_experiment(record)}

    def trial_rows(
        self,
        module: ScenarioModule,
        state: Any,
        auth: C.AuthContext,
        targets: list[C.TestResultV2],
        path: Path,
    ) -> list[dict[str, Any]]:
        """Public probes with their public expected status, then any other target question.

        A target asking a hidden probe's question runs as that target, without an expected
        status, so the trial never reveals that a hidden probe exists.
        """
        suite = suite_probes(require_suite(module.package))
        public = [probe for probe in suite if probe.public]
        target_queries = [t.query for t in targets]
        rows = []
        for probe in public:
            actual = run_query(
                module, state, auth, probe.query, path.stem + "-" + probe.id, OP_TRIAL
            )
            result = "error"
            if actual is not None:
                result = "pass" if matches(actual, probe.expected) else "fail"
            rows.append(
                self.trial_row(
                    probe.id,
                    "public_probe",
                    probe.query in target_queries,
                    probe.query,
                    probe.expected.status,
                    actual,
                    result,
                )
            )
        covered = {probe.query for probe in public}
        number = 0
        for query in dict.fromkeys(target_queries):
            if query in covered:
                continue
            number += 1
            row_id = f"target-{number}"
            actual = run_query(module, state, auth, query, path.stem + "-" + row_id, OP_TRIAL)
            rows.append(
                self.trial_row(
                    row_id,
                    "target",
                    True,
                    query,
                    None,
                    actual,
                    "unchecked" if actual is not None else "error",
                )
            )
        return rows

    @staticmethod
    def trial_row(
        row_id: str,
        kind: str,
        is_target: bool,
        query: str,
        expected_status: str | None,
        actual: C.TestResultV2 | None,
        result: str,
    ) -> dict[str, Any]:
        return {
            "id": row_id,
            "kind": kind,
            "is_target": is_target,
            "query": summary(query, QUERY_SUMMARY),
            "expected_status": expected_status,
            "actual_status": actual.status if actual is not None else None,
            "error_code": actual.error_code
            if actual is not None
            else "engineer_probe_execution_failed",
            "answer_summary": summary(actual.answer) if actual is not None else "",
            **citations_view(actual.citations if actual is not None else ()),
            "result": result,
        }

    # Drafts and sign-off -----------------------------------------------------------------

    def draft(
        self, store: V2Store, payload: DraftInput, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        module = self.bound_module(store, auth, OP_DRAFT)
        sid = auth.session_id
        folder, ticket = self.ticket(sid, payload.ticket_id)
        identity = record_id("draft", [payload.ticket_id, executor_view(auth.executor), request_id])
        path = folder / "drafts" / (identity + ".json")
        with self.files.lock(sid, payload.ticket_id):
            if path.is_file():
                existing = read_json(path)
                if existing["request_hash"] != request_hash(payload):
                    raise C.ProtocolError("engineer_request_id_reused", status=409)
                return {"draft": self.draft_view(existing)}
            if len(records(folder / "drafts")) >= DRAFT_LIMIT:
                raise C.ProtocolError("engineer_draft_limit_reached", status=409)
            index, pack_files = verified_pack(
                store,
                module,
                auth,
                folder / "pack",
                seeded=self.seeds(folder, ticket),
                operation=OP_DRAFT,
            )
            baseline = C.AssistantConfig.model_validate_json(pack_files[index.config.path])
            candidate = candidate_config(module.package, baseline, dict(payload.changes), sid)
            changes = settings_diff(baseline, candidate)
            # Statements are the learner's (or their Agent's) account of the change and are kept
            # as stated: one per editable setting. Whether they match the actual difference is
            # judged after review (E3), so a wrong value is not refused here.
            fields = [statement.field for statement in payload.change_statements]
            if len(set(fields)) != len(fields) or set(fields) - set(EDITABLE_FIELDS):
                raise C.ProtocolError("engineer_change_statement_invalid")
            if draft_text(payload) > DRAFT_TEXT_LIMIT:
                raise C.ProtocolError(
                    "engineer_draft_text_too_long",
                    f"draft text over {DRAFT_TEXT_LIMIT} characters: explanation, statement "
                    "reasons and values, unresolved descriptions",
                )
            public = {row["id"] for row in json.loads(pack_files[index.public_probes.path])}
            claimed = dict(payload.claimed_results)
            if set(claimed) - public or any(set(u.probe_ids) - public for u in payload.unresolved):
                raise C.ProtocolError("engineer_claim_probe_unknown")
            if claimed and set(claimed) != public:
                raise C.ProtocolError("engineer_claim_incomplete")
            snapshot = store.query_at(auth, index.source.as_of, module.snapshot, operation=OP_DRAFT)
            resolved = effective_config(module.package, candidate, snapshot.world.resources)
            record = {
                "id": identity,
                "ticket_id": payload.ticket_id,
                "request_hash": request_hash(payload),
                "executor": executor_view(auth.executor),
                "role": ROLE,
                "created_at": now(),
                "changes": changes,
                "candidate": candidate.model_dump(mode="json"),
                "config_hash": C.digest(resolved.effective),
                "explanation": payload.explanation,
                "change_statements": [
                    {"field": s.field, "before": s.before, "after": s.after, "reason": s.reason}
                    for s in payload.change_statements
                ],
                "claimed_results": dict(sorted(claimed.items())),
                "unresolved": [
                    {"description": u.description, "probe_ids": list(u.probe_ids)}
                    for u in payload.unresolved
                ],
            }
            write_json(path, record)
        return {"draft": self.draft_view(record)}

    def sign(
        self, store: V2Store, payload: SignInput, auth: C.AuthContext, request_id: str
    ) -> dict[str, Any]:
        human_only(auth, "engineer_signoff_requires_human")
        # In a product manager's practice the person does not sign engineering work: Daniel
        # does. The role never switches inside one practice.
        if self.learner_role(auth.session_id) == "pm":
            raise C.ProtocolError("learner_role_cannot_sign", status=409)
        return self._sign(store, payload, auth, request_id)

    def _sign(
        self,
        store: V2Store,
        payload: SignInput,
        auth: C.AuthContext,
        request_id: str,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The sign-off and its trusted review, for the person or, with ``actor``, for an AI
        colleague signing under its own executor (never the person's)."""
        note = payload.impact_note.strip()
        if not note:
            raise C.ProtocolError("engineer_impact_note_required")
        if len(note) > IMPACT_NOTE_LIMIT:
            raise C.ProtocolError("engineer_impact_note_too_long")
        module = self.bound_module(store, auth, OP_SIGN)
        sid = auth.session_id
        folder, ticket = self.ticket(sid, payload.ticket_id)
        draft_id = checked(payload.draft_id, "draft", "engineer_draft_not_found")
        draft_path = folder / "drafts" / (draft_id + ".json")
        if not draft_path.is_file():
            raise C.ProtocolError("engineer_draft_not_found", status=404)
        draft = read_json(draft_path)
        signer = executor_view(auth.executor)
        # The review ID digests its whole input, so the same signed content is one review.
        content_key = C.digest(
            {
                "pack": ticket["pack_id"],
                "candidate": draft["candidate"],
                "explanation": draft["explanation"],
                "change_statements": draft["change_statements"],
                "claimed_results": draft["claimed_results"],
                "unresolved": draft["unresolved"],
                "signer": signer,
            }
        )
        signoff_id = "signoff-" + content_key
        path = folder / "signoffs" / (signoff_id + ".json")
        seeds = self.seeds(folder, ticket)
        with self.files.lock(sid, payload.ticket_id):
            record = read_json(path) if path.is_file() else None
            if record is not None and record["state"] == "complete":
                record = self.with_author(folder, record)
                return self.signed(sid, folder, record, already_signed=True)
            if self.budget(self.signoffs(folder))["used"] >= REVIEW_LIMIT:
                raise C.ProtocolError("engineer_review_budget_exhausted", status=409)
            if record is None:
                record = {
                    "id": signoff_id,
                    "state": "pending",
                    "ticket_id": payload.ticket_id,
                    "draft_id": draft_id,
                    "signed_by": signer,
                    "role": ROLE,
                    "created_at": now(),
                    **({"actor": actor} if actor else {}),
                }
            record["impact_note"] = note
            record.setdefault("draft_executor", draft["executor"])
            write_json(path, record)
            staged = folder / "submission-inputs" / signoff_id
            publish(staged, self.submission_files(folder, record, draft, module, auth))
            submitted = submit_configuration(
                store,
                module,
                auth,
                folder / "pack",
                staged / "submission.json",
                self.files.submissions(sid),
                seeded=seeds,
                operation=OP_SIGN,
            )
            reviewed = review_configuration(
                store,
                module,
                auth,
                folder / "pack",
                self.files.submissions(sid) / submitted["directory"],
                self.files.public_reviews(sid),
                self.files.private_reviews(sid),
                seeded=seeds,
                operation=OP_SIGN,
            )
            record.update(
                state="complete",
                submission_id=submitted["submission_id"],
                review_id=reviewed["review_id"],
                review_status=reviewed["status"],
                signed_at=now(),
            )
            write_json(path, record)
            return self.signed(sid, folder, record, already_signed=False)

    def submission_files(
        self,
        folder: Path,
        record: dict[str, Any],
        draft: dict[str, Any],
        module: ScenarioModule,
        auth: C.AuthContext,
    ) -> dict[str, bytes]:
        """The frozen file protocol, written by the server for the signing person."""
        root = folder / "pack"
        index, _, _ = retained_documentation(root)
        pack_raw = C.read_file(root, index.pack)
        candidate_raw = encode(C.AssistantConfig.model_validate(draft["candidate"]))
        pack_ref = file_ref("pack.json", pack_raw)
        config_ref = file_ref("candidate.json", candidate_raw)
        files = {"pack.json": pack_raw, "candidate.json": candidate_raw}
        claim_ref = None
        if draft["claimed_results"]:
            files["claim.json"] = encode(
                EngineerClaimedReport(
                    contract_version="engineer-review-v1",
                    id="claim-" + record["id"].removeprefix("signoff-"),
                    pack=pack_ref,
                    config=config_ref,
                    created_at=record["created_at"],
                    results=tuple(
                        {"probe_id": key, "result": value}
                        for key, value in draft["claimed_results"].items()
                    ),
                )
            )
            claim_ref = file_ref("claim.json", files["claim.json"])
        files["submission.json"] = encode(
            EngineerSubmissionRecord(
                contract_version="engineer-review-v1",
                id=record["id"],
                pack=pack_ref,
                config=config_ref,
                base_config_hash=index.config.sha256,
                regression_report=claim_ref,
                unresolved=tuple(
                    EngineerUnresolvedItem(
                        id=f"u{number}",
                        description=item["description"],
                        visibility="public",
                        probe_ids=tuple(item["probe_ids"]),
                    )
                    for number, item in enumerate(draft["unresolved"], 1)
                ),
                explanation=draft["explanation"],
                executor=auth.executor,
                created_at=record["created_at"],
                work_language=module.work_language,
                # Stated as drafted; their agreement with the actual difference is E3's to judge.
                changes=tuple(
                    EngineerChangeClaim(
                        field=item["field"],
                        before=item["before"],
                        after=item["after"],
                        reason=item["reason"],
                    )
                    for item in draft["change_statements"]
                ),
            )
        )
        return files

    def signed(
        self, sid: str, folder: Path, record: dict[str, Any], *, already_signed: bool
    ) -> dict[str, Any]:
        return {
            "signoff": {
                "id": record["id"],
                "ticket_id": record["ticket_id"],
                "draft_id": record["draft_id"],
                "signed_by": record["signed_by"],
                **({"actor": record["actor"]} if record.get("actor") else {}),
                "role": record["role"],
                "impact_note": record["impact_note"],
                "signed_at": record["signed_at"],
                "review_id": record["review_id"],
                "already_signed": already_signed,
            },
            "review": self.review_view(sid, record),
            "review_budget": self.budget(self.signoffs(folder)),
        }

    def review_view(self, sid: str, record: dict[str, Any]) -> dict[str, Any]:
        review_id = checked(record["review_id"], "review", "engineer_review_not_found")
        raw = (self.files.public_reviews(sid) / review_id / "report.json").read_bytes()
        report = EngineerPublicReport.model_validate_json(raw)
        language = report.work_language
        return {
            **self.review_summary(record),
            "ticket_id": record["ticket_id"],
            "impact_note": record["impact_note"],
            "retrieval": {"mode": "rule_based", "note": RETRIEVAL_NOTE[language]},
            "report": report.model_dump(mode="json"),
            # Rule conclusions E1-E4 (E5 waits for a model), computed from the private store;
            # only public probe IDs and hidden counts appear in them.
            "evaluation": stored_evaluation(self.files.private_reviews(sid), review_id).model_dump(
                mode="json"
            ),
        }

    def read_reviews(
        self, view: TransactionView, payload: ReviewQuery, auth: C.AuthContext
    ) -> dict[str, Any]:
        self.module(view.bindings)
        sid = auth.session_id
        folder = self.files.tickets(sid)
        if payload.ticket_id is not None:
            folders = [self.ticket(sid, payload.ticket_id)[0]]
        else:
            folders = sorted(folder.glob("ticket-*")) if folder.is_dir() else []
        rows = [row for path in folders for row in self.signoffs(path)]
        rows.sort(key=lambda row: (row["signed_at"], row["review_id"]))
        if payload.review_id is not None:
            review_id = checked(payload.review_id, "review", "engineer_review_not_found")
            match = next((row for row in rows if row["review_id"] == review_id), None)
            if match is None:
                raise C.ProtocolError("engineer_review_not_found", status=404)
            return {"review": self.review_view(sid, match)}
        unique = list({row["review_id"]: row for row in rows}.values())
        width = max(1, min(payload.limit, REVIEW_PAGE_LIMIT))
        page = unique[payload.cursor : payload.cursor + width]
        return {
            "reviews": [{**self.review_summary(row), "ticket_id": row["ticket_id"]} for row in page]
        }


def install_engineer_operations(
    registry: Any, modules: Sequence[ScenarioModule], root: Path | str | None = None
) -> EngineerService:
    """Install after the scenario catalog; handlers select the module by session binding."""
    service = EngineerService(
        Path(root or os.getenv("CAREER_LAB_ENGINEER_ROOT") or "runs/local/engineer"),
        modules,
        lambda: registry.operations["configuration.apply"].handler,
    )

    def act(name: str, capability: str, model: type[C.V2], handler: Any) -> Operation:
        return Operation(
            name, capability, model, handler, service_mode=True, response_model=EngineerResult
        )

    for operation in (
        act(OP_CREATE, "act", TicketCreate, service.create_ticket),
        Operation(
            OP_READ,
            "read",
            TicketQuery,
            service.read_tickets,
            mutates=False,
            response_model=EngineerResult,
        ),
        act(OP_REPRODUCE, "act", TicketTarget, service.reproduce),
        act(OP_TRIAL, "act", TrialInput, service.trial),
        act(OP_DRAFT, "act", DraftInput, service.draft),
        act(OP_SIGN, "submit", SignInput, service.sign),
        Operation(
            OP_REVIEWS,
            "read",
            ReviewQuery,
            service.read_reviews,
            mutates=False,
            response_model=EngineerResult,
        ),
    ):
        registry.register(operation)
    return service
