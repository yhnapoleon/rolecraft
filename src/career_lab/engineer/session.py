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

from pydantic import ConfigDict, Field, JsonValue, RootModel

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
from .execution import matches, run_query, suite_probes
from .files import encode, file_ref, publish, retained_documentation
from .golive import go_live
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
PAGE_LIMIT = 40  # tickets or reviews per listed page
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
    "zh": "试跑与复核固定使用规则版检索，与是否配置识别器无关。",
    "en": "Trials and reviews always use the rule-based retrieval, whether or not "
    "recognizers are configured.",
}


class TicketCreate(C.V2):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)
    source: Literal["seeded", "tests"] = Field(alias="from")
    test_ids: tuple[C.Identifier, ...] = ()


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
        module = self.bound_module(store, auth, OP_CREATE)
        # Without an engineer suite the review would run authored probes with their own
        # preconditions under one configuration: false regressions. No engineer path then.
        require_suite(module.package)
        sid = auth.session_id
        if payload.source == "seeded":
            if payload.test_ids:
                raise C.ProtocolError("engineer_ticket_source_invalid")
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
            ticket_id = record_id("ticket", [sid, "tests", ids])
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
                },
            )
        return {"ticket": self.detail(module, sid, ticket_id), "created": True}

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
        if payload.ticket_id is not None:
            return {"ticket": self.detail(module, sid, payload.ticket_id, view)}
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
            ]
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
            "trials": [self.trial_summary(row) for row in trials[-LISTED_TRIALS:]],
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
        return [row for row in self.ordered(folder / "signoffs") if row["state"] == "complete"]

    @staticmethod
    def budget(signoffs: list[dict[str, Any]]) -> dict[str, int]:
        return {"used": len({row["review_id"] for row in signoffs}), "limit": REVIEW_LIMIT}

    @staticmethod
    def trial_summary(row: dict[str, Any]) -> dict[str, Any]:
        """A listed experiment: which settings it changed; the full change is in its result."""
        return {
            **{
                key: row[key]
                for key in ("id", "kind", "executor", "role", "created_at", "config_hash")
            },
            "changed_fields": list(row["changes"]),
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
            "draft_id": row["draft_id"],
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
                }
            record["impact_note"] = note
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
        page = unique[payload.cursor : payload.cursor + max(1, min(payload.limit, PAGE_LIMIT))]
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
