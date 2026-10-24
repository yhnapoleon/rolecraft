"""Rerun the engineer demo and write its real public reviews, Chinese and English.

    .venv/bin/python -m scripts.engineer_review_samples --output runs/local/engineer-review-samples

For each work language, a fresh database and a fresh practice session: open the scenario's
engineer ticket straight from the engineer card (the system puts the pilot live first), then
sign two drafts as the person: the root-cause fix (``freshness_guard: warn``) and the demo's
over-broad change (the warning plus ``min_score: 0.2``). Each review is read back through
``GET /engineer/reviews/{review_id}`` and written as the ``review`` object that
``engineer.reviews.read`` returns (``report`` and ``evaluation`` included):

    <output>/zh-root-cause.json  zh-demo-overreach.json  en-root-cause.json  en-demo-overreach.json

The output directory must not exist. The database, the engineer directory and the private
review store live in a temporary directory removed afterwards. Rule-based retrieval only, no
model provider, nothing else is written.
"""

import argparse
import json
import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario

PUBLIC = ("F01", "F04", "F05", "F12")
TEXT = {
    "zh": {
        "warn_reason": "索引仍是旧版政策，回答要带过期提醒。",
        "root_explanation": "索引落后于新发布的政策时，回答附上过期提醒，其余设置不变。",
        "threshold_reason": "调低门槛，想把新政策通知也找回来。",
        "overreach_explanation": "加上过期提醒，同时把检索门槛调到 0.2，想把新政策通知也找回来。",
        "impact_note": "其他引用旧版资料的回答也可能带上提醒；门槛变化可能让更多问题得到回答。",
    },
    "en": {
        "warn_reason": "The index still holds the older policy; answers should carry a warning.",
        "root_explanation": "Warn when the indexed policy is older than the published notice; "
        "nothing else changes.",
        "threshold_reason": "Lower the threshold to find the newer notice too.",
        "overreach_explanation": "Add the stale-index warning and lower the threshold to 0.2 "
        "to find the newer notice.",
        "impact_note": "Other answers from older sources may now carry a warning; the lower "
        "threshold may answer more questions.",
    },
}


@contextmanager
def environment(work: Path) -> Iterator[None]:
    """The runtime reads its directories from the environment; restore it afterwards."""
    values = {
        "CAREER_LAB_SCENARIO_ARCHIVE": str(work / "archive"),
        "CAREER_LAB_ENGINEER_ROOT": str(work / "engineer"),
        "CAREER_LAB_SCENARIO_CATALOG": None,
        "CAREER_LAB_RECOGNIZERS": None,
    }
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Session:
    def __init__(self, client: TestClient, language: str):
        created = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        created.raise_for_status()
        body = created.json()
        self.client, self.language = client, language
        self.sid, self.headers = body["session_id"], {"Authorization": "Bearer " + body["token"]}

    def result(self, response: Any) -> dict[str, Any]:
        if response.status_code != 200:
            raise SystemExit(f"{response.request.url.path}: {response.text}")
        return response.json()["result"]

    def read(self, path: str) -> dict[str, Any]:
        return self.result(self.client.get(f"/sessions/{self.sid}{path}", headers=self.headers))

    def act(self, path: str, operation: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.client.get(f"/sessions/{self.sid}", headers=self.headers).json()["state"]
        return self.result(
            self.client.post(
                f"/sessions/{self.sid}{path}",
                headers=self.headers,
                json={
                    "schema_version": 2,
                    "request_id": key,
                    "operation": operation,
                    "payload": payload,
                    "expected_version": state["business_seq"],
                    "expected_workspace_revision": state["workspace_revision"],
                },
            )
        )


def signed_review(
    session: Session,
    ticket_id: str,
    key: str,
    changes: dict[str, Any],
    explanation: str,
    statements: list[dict[str, Any]],
) -> dict[str, Any]:
    base = f"/engineer/tickets/{ticket_id}"
    draft = session.act(
        base + "/drafts",
        "engineer.submissions.draft",
        "draft-" + key,
        {
            "ticket_id": ticket_id,
            "changes": changes,
            "explanation": explanation,
            "change_statements": statements,
            "claimed_results": dict.fromkeys(PUBLIC, "pass"),
        },
    )["draft"]
    signed = session.act(
        base + "/signoffs",
        "engineer.submissions.sign",
        "sign-" + key,
        {
            "ticket_id": ticket_id,
            "draft_id": draft["id"],
            "impact_note": TEXT[session.language]["impact_note"],
        },
    )
    return session.read("/engineer/reviews/" + signed["review"]["review_id"])["review"]


def language_samples(language: str, work: Path) -> dict[str, dict[str, Any]]:
    root = default_installed_scenario()
    if language == "en":
        root = root / "locales" / "en"
    text = TEXT[language]
    with environment(work):
        app = create_runtime_app(
            "sqlite:///" + str(work / "source.db"), provider="local", scenario_root=root
        )
        try:
            with TestClient(app) as client:
                session = Session(client, language)
                ticket = session.act(
                    "/engineer/tickets", "engineer.tickets.create", "ticket", {"from": "seeded"}
                )["ticket"]
                baseline = ticket["baseline_config"]
                warning = {
                    "field": "freshness_guard",
                    "before": baseline["freshness_guard"],
                    "after": "warn",
                    "reason": text["warn_reason"],
                }
                root_cause = signed_review(
                    session,
                    ticket["id"],
                    "root-cause",
                    {"freshness_guard": "warn"},
                    text["root_explanation"],
                    [warning],
                )
                overreach = signed_review(
                    session,
                    ticket["id"],
                    "demo-overreach",
                    {"freshness_guard": "warn", "min_score": 0.2},
                    text["overreach_explanation"],
                    [
                        warning,
                        {
                            "field": "min_score",
                            "before": baseline["min_score"],
                            "after": 0.2,
                            "reason": text["threshold_reason"],
                        },
                    ],
                )
        finally:
            app.state.store.close()
            app.state.v2_store.db.engine.dispose()
    return {"root-cause": root_cause, "demo-overreach": overreach}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, required=True, help="New directory for samples")
    output = parser.parse_args(argv).output
    if output.exists():
        raise SystemExit(f"output exists: {output}")
    samples = {}
    for language in ("zh", "en"):
        with tempfile.TemporaryDirectory(prefix="engineer-samples-") as work:
            for name, review in language_samples(language, Path(work)).items():
                samples[f"{language}-{name}.json"] = review
    output.mkdir(parents=True)
    for name, review in samples.items():
        (output / name).write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    for name, review in samples.items():
        labels = {c["criterion"][:2]: c["label"] for c in review["evaluation"]["criteria"]}
        hidden = review["report"]["hidden_comparison"]
        print(
            f"{output / name}: E1 {labels['E1']}, E2 {labels['E2']}, "
            f"hidden fixed {hidden['fixed']}, new failures {hidden['new_failures']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
