"""Engineer session operations through the normal session HTTP routes (TestClient)."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario
from career_lab.contracts.v2.engineer import EngineerRegressionReport

TARGET_QUERY = {
    "zh": "住宿报销上限是多少？",
    "en": "What is the hotel reimbursement limit per night?",
}
PUBLIC_PROBES = {"F01", "F04", "F05", "F12"}
ENGINEER_AGENT_ACTIONS = [
    "engineer.tickets.read",
    "engineer.reproduce",
    "engineer.trial",
    "engineer.submissions.draft",
    "engineer.reviews.read",
]


@dataclass
class Eng:
    app: FastAPI
    client: TestClient
    sid: str
    token: str
    language: str
    root: Path
    responses: list[str] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.token}

    def state(self) -> dict[str, Any]:
        return self.client.get("/sessions/" + self.sid, headers=self.headers).json()["state"]

    def call(
        self,
        path: str,
        operation: str,
        payload: dict[str, Any],
        request_id: str,
        *,
        token: str | None = None,
        method: str = "POST",
    ) -> httpx.Response:
        state = self.state()
        response = self.client.request(
            method,
            "/sessions/" + self.sid + path,
            headers={"Authorization": "Bearer " + (token or self.token)},
            json={
                "schema_version": 2,
                "request_id": request_id,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )
        self.responses.append(response.text)
        return response

    def read(self, path: str, *, token: str | None = None) -> httpx.Response:
        response = self.client.get(
            "/sessions/" + self.sid + path,
            headers={"Authorization": "Bearer " + (token or self.token)},
        )
        self.responses.append(response.text)
        return response

    def ok(self, response: httpx.Response) -> dict[str, Any]:
        assert response.status_code == 200, response.text
        return response.json()["result"]

    def advance_world(self) -> None:
        """The first plan publishes the newer policy notice; the daily index keeps v1."""
        from career_lab.scenarios.v2.module import ref_for

        module = self.app.state.scenario_v2
        result = self.call(
            "/configuration",
            "configuration.apply",
            {
                "base": ref_for("config", module.package.baseline(self.sid)).model_dump(
                    mode="json"
                ),
                "settings": {"work_items": ["scope_filter", "human_fallback"], "fallback": "human"},
            },
            "advance-world",
        )
        assert result.status_code == 200, result.text

    def seeded(self) -> dict[str, Any]:
        created = self.ok(
            self.call("/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "seed")
        )
        return created["ticket"]

    def grant(self, label: str, capabilities: list[str], actions: list[str] | None) -> str:
        payload: dict[str, Any] = {
            "agent_label": label,
            "capabilities": capabilities,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        if actions is not None:
            payload["allowed_actions"] = actions
        result = self.ok(self.call("/delegations", "delegations.create", payload, "grant-" + label))
        return result["result"]["token"]


def make_session(app: FastAPI, client: TestClient, language: str, root: Path) -> Eng:
    response = client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
    )
    assert response.status_code == 200, response.text
    created = response.json()
    return Eng(app, client, created["session_id"], created["token"], language, root)


def build_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str) -> FastAPI:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("CAREER_LAB_ENGINEER_ROOT", str(tmp_path / "engineer"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    scenario = default_installed_scenario()
    if language == "en":
        scenario = scenario / "locales" / "en"
    return create_runtime_app("sqlite:///" + str(tmp_path / "source.db"), scenario_root=scenario)


@pytest.fixture(params=["zh", "en"])
def eng(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[Eng]:
    app = build_app(tmp_path, monkeypatch, request.param)
    try:
        with TestClient(app) as client:
            yield make_session(app, client, request.param, tmp_path / "engineer")
    finally:
        app.state.store.close()


def hidden_queries(eng: Eng) -> list[str]:
    """Hidden questions of the authored probes and of the engineer suite the review runs."""
    from career_lab.contracts.v2 import read_file
    from career_lab.engineer.suite import engineer_suite

    module = eng.app.state.scenario_v2
    rows = json.loads(read_file(module.package.root, module.files["probes.json"]))
    rows += json.loads(engineer_suite(module.package) or b"[]")
    return list(dict.fromkeys(row["query"] for row in rows if not row["public"]))


def test_seeded_ticket_detail(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    assert ticket["source"] == "seeded"
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert detail["id"] == ticket["id"] and detail["work_language"] == eng.language
    (target,) = detail["target_tests"]
    assert target["query"] == TARGET_QUERY[eng.language]
    assert target["origin"] == "ticket_seed"
    assert target["executor"] == {"id": "engineer-ticket-seed", "kind": "system"}
    assert target["origin_label"] == (
        "委托附带的复现记录"
        if eng.language == "zh"
        else "Reproduction record attached to the ticket"
    )
    assert target["status"] == "answered" and "500" in target["answer_summary"]
    assert target["used_versions"]["policy"] == 1 and target["source_versions"]["policy"] == 2
    assert {p["id"] for p in detail["public_probes"]} == PUBLIC_PROBES
    assert all(set(p) == {"id", "query"} for p in detail["public_probes"])
    assert detail["baseline_config"]["freshness_guard"] == "none"
    fields = {f["field"]: f for f in detail["editable_fields"]}
    assert fields["freshness_guard"]["choices"] == ["none", "warn", "fallback"]
    assert "policy_travel" in fields["domains"]["choices"]
    assert "realtime_sync" in fields["work_items"]["choices"]
    assert "session_id" not in fields and "generator" not in fields
    assert detail["review_budget"] == {"used": 0, "limit": 3}
    assert detail["trials"] == [] and detail["drafts"] == [] and detail["reviews"] == []
    raw = json.dumps(detail, ensure_ascii=False)
    assert all(query not in raw for query in hidden_queries(eng))
    assert "expected" not in raw


def test_seeded_ticket_is_idempotent_and_listed(eng: Eng) -> None:
    eng.advance_world()
    first = eng.seeded()
    again = eng.ok(
        eng.call("/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "seed-2")
    )["ticket"]
    assert again["id"] == first["id"]
    listed = eng.ok(eng.read("/engineer/tickets"))["tickets"]
    assert [t["id"] for t in listed] == [first["id"]]


def test_seeded_record_is_not_learner_work(eng: Eng) -> None:
    eng.advance_world()
    before_state = eng.state()
    before_tests = eng.ok(eng.read("/tests"))
    before_timeline = eng.read("/timeline").json()
    eng.seeded()
    assert eng.state() == before_state
    assert eng.ok(eng.read("/tests")) == before_tests
    assert eng.read("/timeline").json() == before_timeline


def ticket_path(ticket: dict[str, Any], leaf: str) -> str:
    return "/engineer/tickets/" + ticket["id"] + "/" + leaf


def trial(eng: Eng, ticket: dict[str, Any], changes: dict[str, Any], key: str, **kw: Any):
    return eng.call(
        ticket_path(ticket, "trials"),
        "engineer.trial",
        {"ticket_id": ticket["id"], "changes": changes},
        key,
        **kw,
    )


def test_reproduce_reruns_the_seed_record(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    done = eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "repro-1",
        )
    )["reproduction"]
    assert done["status"] == "reproduced" and done["counts"]["matched"] == 1
    (row,) = done["rows"]
    assert row["query"] == TARGET_QUERY[eng.language] and row["matches_record"]
    assert done["executor"]["kind"] == "human" and done["role"] == "engineer"
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert [t["kind"] for t in detail["trials"]] == ["reproduce"]


def test_trial_runs_target_and_public_probes(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    baseline = eng.ok(trial(eng, ticket, {}, "trial-base"))["trial"]
    rows = {row["id"]: row for row in baseline["rows"]}
    assert set(rows) == PUBLIC_PROBES
    assert rows["F01"]["is_target"] and rows["F01"]["result"] == "fail"
    assert rows["F01"]["expected_status"] == "answered_with_warning"
    fixed = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial-warn"))["trial"]
    assert {row["result"] for row in fixed["rows"]} == {"pass"}
    assert fixed["counts"] == {"passed": 4, "failed": 0, "errors": 0, "unchecked": 0, "total": 4}
    assert fixed["changes"] == {"freshness_guard": {"before": "none", "after": "warn"}}
    assert fixed["config_hash"] != baseline["config_hash"]
    assert fixed["executor"]["kind"] == "human" and fixed["role"] == "engineer"
    again = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial-warn"))["trial"]
    assert again["id"] == fixed["id"]
    reused = trial(eng, ticket, {"freshness_guard": "fallback"}, "trial-warn")
    assert reused.status_code == 409 and reused.json()["code"] == "engineer_request_id_reused"
    raw = json.dumps([baseline, fixed], ensure_ascii=False)
    assert all(query not in raw for query in hidden_queries(eng))


def test_trial_for_handed_over_tests(eng: Eng) -> None:
    query = "火星天气如何？" if eng.language == "zh" else "What is the weather on Mars?"
    other = "住宿报销金额？" if eng.language == "zh" else "What is the maximum hotel reimbursement?"
    tests = []
    for number, text in enumerate((query, other)):
        made = eng.ok(
            eng.call(
                "/tests",
                "tests.create",
                {"query": text, "config_version": 0},
                f"pm-test-{number}",
            )
        )
        tests.append(made["test"]["id"])
    ticket = eng.ok(
        eng.call(
            "/engineer/tickets",
            "engineer.tickets.create",
            {"from": "tests", "test_ids": tests},
            "t",
        )
    )["ticket"]
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert {t["origin"] for t in detail["target_tests"]} == {"learner_test"}
    rows = eng.ok(trial(eng, ticket, {}, "trial-pm"))["trial"]["rows"]
    by_query = {row["query"]: row for row in rows}
    assert by_query[query]["is_target"] and by_query[query]["kind"] == "public_probe"
    # A PM question that equals a hidden probe runs as a plain target, with no expectation.
    assert by_query[other]["kind"] == "target" and by_query[other]["expected_status"] is None
    assert by_query[other]["result"] == "unchecked" and by_query[other]["id"] == "target-1"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"command": "touch /tmp/forbidden"}, "engineer_setting_not_editable"),
        ({"url": "https://example.invalid"}, "engineer_setting_not_editable"),
        ({"session_id": "someone-else"}, "engineer_setting_not_editable"),
        ({"generator": "llm"}, "engineer_setting_not_editable"),
        ({"domains": ["https://example.invalid"]}, "unknown_domain"),
        ({"domains": ["/tmp/file"]}, "unknown_domain"),
        ({"work_items": ["shell"]}, "unknown_work_item"),
        ({"prohibited_topics": ["https://example.invalid/x"]}, "engineer_setting_value_invalid"),
        ({"prohibited_topics": ["/etc/passwd"]}, "engineer_setting_value_invalid"),
        ({"scope_filter": "false"}, "engineer_setting_value_invalid"),
        ({"freshness_guard": "sometimes"}, "engineer_setting_value_invalid"),
        ({"retrieval_limit": 21}, "retrieval_limit_exceeded"),
    ],
)
def test_trial_rejects_invalid_settings(eng: Eng, changes: dict[str, Any], code: str) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    rejected = trial(eng, ticket, changes, "bad")
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == code
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert detail["trials"] == []


def draft(eng: Eng, ticket: dict[str, Any], key: str, *, token: str | None = None, **extra: Any):
    payload = {
        "ticket_id": ticket["id"],
        "changes": {"freshness_guard": "warn"},
        "explanation": "Warn when the indexed policy is older than the source.",
        "change_statements": [
            {
                "field": "freshness_guard",
                "before": "none",
                "after": "warn",
                "reason": "The index lags the newer notice.",
            }
        ],
        "claimed_results": {probe: "pass" for probe in sorted(PUBLIC_PROBES)},
        "unresolved": [{"description": "Index refresh is still daily.", "probe_ids": ["F01"]}],
    }
    payload.update(extra)
    return eng.call(
        ticket_path(ticket, "drafts"), "engineer.submissions.draft", payload, key, token=token
    )


def sign(
    eng: Eng, ticket: dict[str, Any], draft_id: str, key: str, *, token: str | None = None
) -> httpx.Response:
    return eng.call(
        ticket_path(ticket, "signoffs"),
        "engineer.submissions.sign",
        {
            "ticket_id": ticket["id"],
            "draft_id": draft_id,
            "impact_note": "Other stale policy answers may now carry a warning.",
        },
        key,
        token=token,
    )


def private_report(eng: Eng, review_id: str) -> EngineerRegressionReport:
    folder = eng.root / "private-reviews" / eng.sid / "reports" / review_id
    return EngineerRegressionReport.model_validate_json((folder / "report.json").read_bytes())


def test_seeded_round_trip_signed_by_the_person(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "r",
        )
    )
    tried = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial"))["trial"]
    assert tried["counts"]["passed"] == 4
    drafted = eng.ok(draft(eng, ticket, "draft-1"))["draft"]
    assert drafted["executor"]["kind"] == "human" and drafted["role"] == "engineer"
    assert drafted["changes"] == {"freshness_guard": {"before": "none", "after": "warn"}}
    assert drafted["config_hash"] == tried["config_hash"]
    signed = eng.ok(sign(eng, ticket, drafted["id"], "sign-1"))
    assert signed["signoff"]["impact_note"].startswith("Other stale policy")
    assert signed["signoff"]["signed_by"]["kind"] == "human"
    assert signed["review_budget"] == {"used": 1, "limit": 3}
    review = signed["review"]
    report = review["report"]
    assert review["status"] == report["status"] == "verified"
    assert report["claim_check"] == "matched"
    assert review["retrieval"]["mode"] == "rule_based"
    assert {row["probe_id"] for row in report["public_results"]} == PUBLIC_PROBES
    assert any(
        f["kind"] == "target_fix" and f["status"] == "pass" and f["probe_ids"] == ["F01"]
        for f in report["findings"]
    )
    full = private_report(eng, review["review_id"])
    rows = {row.probe_id: row for row in full.results}
    # The root-cause fix passes every probe of the engineer suite, hidden ones included.
    assert {row.result for row in full.results} == {"pass"}
    assert rows["F14"].visibility == rows["F15"].visibility == "hidden"
    hidden_regressions = [
        f.probe_ids
        for f in full.findings
        if f.kind == "new_regression" and f.status == "fail" and f.visibility == "hidden"
    ]
    assert hidden_regressions == []
    baseline = json.loads(
        (
            eng.root
            / "private-reviews"
            / eng.sid
            / "reports"
            / review["review_id"]
            / "baseline-results.json"
        ).read_bytes()
    )
    baseline_hidden_fails = sum(
        row["visibility"] == "hidden" and row["result"] == "fail" for row in baseline
    )
    # The baseline's two hidden failures (the target's own kind) are fixed; none is left.
    assert baseline_hidden_fails == 2 and report["hidden"]["failed"] == 0
    assert report["hidden_comparison"]["fixed"] == 2
    assert report["hidden_comparison"]["new_failures"] == 0
    assert full.reviewer.kind == "human"
    read = eng.ok(eng.read("/engineer/reviews/" + review["review_id"]))["review"]
    assert read["report"] == report and read["impact_note"] == signed["signoff"]["impact_note"]
    listed = eng.ok(eng.read("/engineer/reviews"))["reviews"]
    assert [row["review_id"] for row in listed] == [review["review_id"]]
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert [r["review_id"] for r in detail["reviews"]] == [review["review_id"]]
    assert detail["review_budget"] == {"used": 1, "limit": 3}
    assert [row["id"] for row in detail["drafts"]] == [drafted["id"]]
    assert detail["latest_draft"]["change_statements"][0]["field"] == "freshness_guard"


def test_review_budget_counts_distinct_inputs(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    reviews = []
    for number in range(3):
        made = eng.ok(draft(eng, ticket, f"d{number}", explanation=f"Attempt {number}"))["draft"]
        reviews.append(eng.ok(sign(eng, ticket, made["id"], f"s{number}"))["review"]["review_id"])
    assert len(set(reviews)) == 3
    again = eng.ok(draft(eng, ticket, "d-repeat", explanation="Attempt 0"))["draft"]
    repeated = eng.ok(sign(eng, ticket, again["id"], "s-repeat"))
    assert repeated["review"]["review_id"] == reviews[0]
    assert repeated["signoff"]["already_signed"] is True
    assert repeated["review_budget"] == {"used": 3, "limit": 3}
    fourth = eng.ok(draft(eng, ticket, "d4", explanation="Attempt 4"))["draft"]
    refused = sign(eng, ticket, fourth["id"], "s4")
    assert refused.status_code == 409
    assert refused.json()["code"] == "engineer_review_budget_exhausted"


@pytest.mark.parametrize(
    "extra,code",
    [
        ({"claimed_results": {"F01": "pass"}}, "engineer_claim_incomplete"),
        ({"claimed_results": {"F09": "pass"}}, "engineer_claim_probe_unknown"),
        (
            {"unresolved": [{"description": "x", "probe_ids": ["F09"]}]},
            "engineer_claim_probe_unknown",
        ),
        (
            # A wrong value is kept and judged by E3; two statements for one field are refused.
            {
                "change_statements": [
                    {"field": "freshness_guard", "before": "none", "after": "warn", "reason": "r"},
                    {
                        "field": "freshness_guard",
                        "before": "none",
                        "after": "fallback",
                        "reason": "r",
                    },
                ]
            },
            "engineer_change_statement_invalid",
        ),
        ({"changes": {"command": "rm -rf /"}}, "engineer_setting_not_editable"),
    ],
)
def test_draft_rejects_inconsistent_content(eng: Eng, extra: dict[str, Any], code: str) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    rejected = draft(eng, ticket, "bad-draft", **extra)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == code


def test_signoff_requires_an_impact_note(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    for note, code in (
        ("   ", "engineer_impact_note_required"),
        ("x" * 501, "engineer_impact_note_too_long"),
    ):
        rejected = eng.call(
            ticket_path(ticket, "signoffs"),
            "engineer.submissions.sign",
            {"ticket_id": ticket["id"], "draft_id": made["id"], "impact_note": note},
            "sign-" + code,
        )
        assert rejected.status_code == 422 and rejected.json()["code"] == code
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert detail["review_budget"]["used"] == 0


def test_agent_works_the_ticket_but_cannot_sign(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    agent = eng.grant("engineer-agent", ["read", "act", "submit"], ENGINEER_AGENT_ACTIONS)
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"], token=agent))["ticket"]
    assert detail["id"] == ticket["id"]
    done = eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "agent-repro",
            token=agent,
        )
    )["reproduction"]
    assert done["status"] == "reproduced" and done["executor"]["kind"] == "external_agent"
    tried = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "agent-trial", token=agent))
    assert tried["trial"]["executor"]["delegation_id"]
    made = eng.ok(draft(eng, ticket, "agent-draft", token=agent))["draft"]
    assert made["executor"]["kind"] == "external_agent" and made["role"] == "engineer"
    # The grant confines the Agent to engineer operations; PM reads are refused.
    refused = eng.read("/tests", token=agent)
    assert refused.status_code == 403 and refused.json()["code"] == "action_forbidden"
    for key, response in (
        ("sign", sign(eng, ticket, made["id"], "agent-sign", token=agent)),
        (
            "create",
            eng.call(
                "/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "a", token=agent
            ),
        ),
    ):
        assert response.status_code == 403, key
        assert response.json()["code"] == "action_forbidden", key
    # Even an unrestricted Agent with submit cannot sign or hand over tests: person only.
    broad = eng.grant("broad-agent", ["read", "act", "submit"], None)
    signed = sign(eng, ticket, made["id"], "broad-sign", token=broad)
    assert signed.status_code == 403
    assert signed.json()["code"] == "engineer_signoff_requires_human"
    handed = eng.call(
        "/engineer/tickets",
        "engineer.tickets.create",
        {"from": "tests", "test_ids": [detail["target_tests"][0]["test_id"]]},
        "broad-create",
        token=broad,
    )
    assert handed.status_code == 403
    assert handed.json()["code"] == "engineer_ticket_requires_human"
    person = eng.ok(sign(eng, ticket, made["id"], "person-sign"))
    assert person["signoff"]["signed_by"]["kind"] == "human"
    reviews = eng.ok(eng.read("/engineer/reviews", token=agent))["reviews"]
    assert [row["review_id"] for row in reviews] == [person["review"]["review_id"]]


def test_engineer_work_leaves_pm_state_unchanged(eng: Eng) -> None:
    eng.advance_world()
    pm_query = TARGET_QUERY[eng.language]
    eng.ok(eng.call("/tests", "tests.create", {"query": pm_query, "config_version": 1}, "pm"))

    def pm_view() -> list[Any]:
        return [
            eng.state(),
            eng.ok(eng.read("/tests")),
            eng.ok(eng.read("/work-products")),
            eng.ok(eng.read("/submissions")),
            eng.read("/timeline").json(),
        ]

    before = pm_view()
    ticket = eng.seeded()
    eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "r",
        )
    )
    eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "t"))
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    eng.ok(sign(eng, ticket, made["id"], "s"))
    assert pm_view() == before


def test_other_sessions_cannot_reach_a_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(tmp_path, monkeypatch, "zh")
    try:
        with TestClient(app) as client:
            owner = make_session(app, client, "zh", tmp_path / "engineer")
            other = make_session(app, client, "zh", tmp_path / "engineer")
            owner.advance_world()
            ticket = owner.seeded()
            # Another session's token on this session's route is not a credential here.
            stranger = owner.read("/engineer/tickets/" + ticket["id"], token=other.token)
            assert stranger.status_code == 401
            # The other session's own route never sees this session's ticket.
            missing = other.read("/engineer/tickets/" + ticket["id"])
            assert missing.status_code == 404
            assert missing.json()["code"] == "engineer_ticket_not_found"
            assert other.ok(other.read("/engineer/tickets"))["tickets"] == []
            refused = trial(other, ticket, {}, "cross")
            assert refused.status_code == 404
            for bad in ("..%2F..%2Fsecret", "ticket-" + "0" * 64):
                assert other.read("/engineer/tickets/" + bad).status_code == 404
    finally:
        app.state.store.close()


def test_responses_carry_no_private_paths_tokens_or_hidden_probes(eng: Eng) -> None:
    eng.advance_world()
    agent = eng.grant("privacy-agent", ["read", "act"], ENGINEER_AGENT_ACTIONS)
    # Only the person's own grant response carries the new token; scan what follows it.
    eng.responses.clear()
    ticket = eng.seeded()
    eng.read("/engineer/tickets/" + ticket["id"], token=agent)
    eng.call(
        ticket_path(ticket, "reproductions"), "engineer.reproduce", {"ticket_id": ticket["id"]}, "r"
    )
    trial(eng, ticket, {"freshness_guard": "warn"}, "t", token=agent)
    made = eng.ok(draft(eng, ticket, "d", token=agent))["draft"]
    signed = eng.ok(sign(eng, ticket, made["id"], "s"))
    eng.read("/engineer/reviews/" + signed["review"]["review_id"], token=agent)
    eng.read("/engineer/reviews")
    eng.read("/engineer/tickets/" + ticket["id"])
    text = "\n".join(eng.responses)
    assert str(eng.root) not in text and "private-reviews" not in text
    assert str(eng.root.parent) not in text
    assert eng.token not in text and agent not in text
    for query in hidden_queries(eng):
        assert query not in text
    hidden_ids = {
        row.probe_id for row in private_report(eng, signed["review"]["review_id"]).results
    }
    hidden_ids -= PUBLIC_PROBES
    review_text = json.dumps(signed["review"])
    assert not any(f'"{probe}"' in review_text for probe in hidden_ids)


def test_recognizer_setting_does_not_change_trial_or_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def outcome(environment: str | None, folder: Path) -> tuple[Any, Any]:
        folder.mkdir()
        app = build_app(folder, monkeypatch, "zh")
        if environment is not None:
            monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", environment)
        try:
            with TestClient(app) as client:
                session = make_session(app, client, "zh", folder / "engineer")
                session.advance_world()
                ticket = session.seeded()
                rows = session.ok(trial(session, ticket, {"freshness_guard": "warn"}, "t"))
                made = session.ok(draft(session, ticket, "d"))["draft"]
                report = session.ok(sign(session, ticket, made["id"], "s"))["review"]["report"]
                full = private_report(session, report["id"])
                # Rule-based: no recognizer record on any reviewed execution.
                assert all(r.actual and r.actual.recognition is None for r in full.results)
                trial_rows = [
                    (r["id"], r["result"], r["actual_status"], r["answer_summary"])
                    for r in rows["trial"]["rows"]
                ]
                reviewed = (
                    report["status"],
                    report["hidden"],
                    [
                        (r["probe_id"], r["result"], r["actual_status"])
                        for r in report["public_results"]
                    ],
                    [(f["kind"], f["status"], f["probe_ids"]) for f in report["findings"]],
                )
                return trial_rows, reviewed
        finally:
            monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
            app.state.store.close()

    plain = outcome(None, tmp_path / "plain")
    configured = outcome(str(tmp_path / "no-such-recognizers"), tmp_path / "configured")
    assert configured == plain


def test_engineer_records_survive_an_api_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(tmp_path, monkeypatch, "en")
    try:
        with TestClient(app) as client:
            first = make_session(app, client, "en", tmp_path / "engineer")
            first.advance_world()
            ticket = first.seeded()
            first.ok(trial(first, ticket, {"freshness_guard": "warn"}, "t"))
            made = first.ok(draft(first, ticket, "d"))["draft"]
            signed = first.ok(sign(first, ticket, made["id"], "s"))
            before = first.ok(first.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    finally:
        app.state.store.close()
    restarted = build_app(tmp_path, monkeypatch, "en")
    try:
        with TestClient(restarted) as client:
            again = Eng(restarted, client, first.sid, first.token, "en", first.root)
            after = again.ok(again.read("/engineer/tickets/" + ticket["id"]))["ticket"]
            assert after == before
            assert [t["kind"] for t in after["trials"]] == ["trial"]
            assert [d["id"] for d in after["drafts"]] == [made["id"]]
            assert after["review_budget"] == {"used": 1, "limit": 3}
            review = again.ok(again.read("/engineer/reviews/" + signed["review"]["review_id"]))
            assert review["review"]["report"] == signed["review"]["report"]
            repeated = again.ok(sign(again, ticket, made["id"], "s-again"))
            assert repeated["signoff"]["already_signed"] is True
    finally:
        restarted.state.store.close()


def test_experiments_per_ticket_are_capped(eng: Eng, monkeypatch: pytest.MonkeyPatch) -> None:
    from career_lab.engineer import session as engineer_session

    monkeypatch.setattr(engineer_session, "EXPERIMENT_LIMIT", 2)
    eng.advance_world()
    ticket = eng.seeded()
    eng.ok(trial(eng, ticket, {}, "t1"))
    eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "r",
        )
    )
    capped = trial(eng, ticket, {"freshness_guard": "warn"}, "t3")
    assert capped.status_code == 409 and capped.json()["code"] == "engineer_trial_limit_reached"
    # A retry of an existing experiment still answers.
    assert eng.ok(trial(eng, ticket, {}, "t1"))["trial"]["counts"]["total"] == 4


def test_catalog_deployment_selects_the_session_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.regression.published import write_catalog

    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("CAREER_LAB_ENGINEER_ROOT", str(tmp_path / "engineer"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    app = create_runtime_app("sqlite:///" + str(tmp_path / "source.db"))
    try:
        with TestClient(app) as client:
            english = make_session(app, client, "en", tmp_path / "engineer")
            ticket = english.seeded()
            detail = english.ok(english.read("/engineer/tickets?ticket_id=" + ticket["id"]))
            assert detail["ticket"]["target_tests"][0]["query"] == TARGET_QUERY["en"]
            assert detail["ticket"]["work_language"] == "en"
            response = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_urgent_v2", "work_language": "zh"},
            )
            assert response.status_code == 200, response.text
            created = response.json()
            variant = Eng(
                app, client, created["session_id"], created["token"], "zh", tmp_path / "engineer"
            )
            # The variant has no engineer regression suite, so it has no engineer path.
            refused = variant.call(
                "/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "seed"
            )
            assert refused.status_code == 409
            assert refused.json()["code"] == "engineer_suite_unavailable"
    finally:
        app.state.store.close()
