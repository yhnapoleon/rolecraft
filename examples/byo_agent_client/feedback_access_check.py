"""Narrow SQ-04/SQ-08 check through public standard-service endpoints."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from career_lab.contracts import v2 as C
from examples.byo_agent_client.service_check import ServiceCheck, require
from examples.byo_agent_client.workflow import save


def reference_ids(value):
    if isinstance(value, dict):
        result = (
            {value["object_id"]}
            if {"session_id", "kind", "object_id", "version"} <= value.keys()
            else set()
        )
        return result | set().union(*(reference_ids(x) for x in value.values()))
    if isinstance(value, list):
        return set().union(*(reference_ids(x) for x in value))
    return set()


def run(api_url, output, source, database, scenario):
    check = ServiceCheck(api_url, output)
    report = {
        "status": "running",
        "normal_v4_verified": False,
        "history_bridge": False,
        "sq04_scope": "completed external feedback-response recovery/replay racing explicit revocation",
        "sq08_scope": "actual first feedback: full delegate equality and one omitted source projection",
    }
    try:
        created = check.owner(
            "POST",
            "/sessions",
            {"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "zh"},
        )
        check.sid, check.token = created["session_id"], created["token"]
        check.secrets.append(check.token)
        check.trace.update(session_id=check.sid, purpose="standard_feedback_access")
        save(
            check.directory / "owner.json",
            {"api_url": api_url, "session_id": check.sid, "token": check.token},
        )
        prefix = "/sessions/" + check.sid
        read = check.human(
            "read_material",
            "/actions",
            {
                "tool": "read_material",
                "material": {
                    "session_id": check.sid,
                    "kind": "material",
                    "object_id": "brief",
                    "version": 1,
                },
            },
        )
        work = check.human(
            "work_products.create",
            "/work-products",
            {
                "kind": "text",
                "purpose": "plan",
                "title": "待查试点依据",
                "content": "先保留试点范围，核实真实处理时间与人工安排后再决定。",
                "evidence_refs": [read["result"]["fragments"][0]["ref"]],
            },
        )["result"]["ref"]
        context = check.owner("GET", prefix + "/workbench")["result"]["result"]
        config = context["timeline"]["workspace"]["config"]
        exact = {
            "session_id": check.sid,
            "kind": "config",
            "object_id": config["id"],
            "version": config["version"],
            "config_version": config["config_version"],
        }
        sub = check.human(
            "submissions.create",
            "/submissions",
            {"decision": "defer_with_conditions", "products": [work], "config": exact},
        )["result"]["submission"]
        env = dict(
            os.environ,
            PYTHONPATH=str(source / "src"),
            CAREER_LAB_SCENARIO_V2=str(scenario),
            PYTHONDONTWRITEBYTECODE="1",
        )
        with (check.directory / "worker.log").open("w") as log:
            done = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "career_lab.cli",
                    "worker",
                    "--once",
                    "--provider",
                    "local",
                    "--database-url",
                    "sqlite:///" + str(database),
                ],
                cwd=source,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=40,
            )
        require(done.returncode == 0, "worker_failed")
        feedback_path = "/feedback/" + sub["object_id"]
        original = check.owner("GET", prefix + feedback_path)["result"]["result"]["items"][0]
        require(len(original["rule_items"]) == 14, "actual_feedback_required")

        def grant(objects=None):
            payload = {
                "agent_label": "Feedback access audit",
                "capabilities": ["read", "act"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            }
            if objects is not None:
                payload["allowed_objects"] = sorted(objects)
            value = check.human("delegations.create", "/delegations", payload)["result"]["result"]
            check.secrets.append(value["token"])
            return value

        full = grant()

        def request(token, method, suffix, body=None):
            r = check.http.request(
                method, prefix + suffix, json=body, headers={"Authorization": "Bearer " + token}
            )
            return {"http_status": r.status_code, "body": r.json()}

        whole = request(full["token"], "GET", feedback_path)
        require(
            whole["http_status"] == 200
            and C.digest(whole["body"]["result"]["result"]["items"][0]) == C.digest(original),
            "full_agent_feedback_changed",
        )
        ids = reference_ids(original) | {
            original["id"],
            sub["object_id"],
            work["object_id"],
            exact["object_id"],
        }
        require("brief" in ids, "optional_source_missing")
        limited = grant(ids - {"brief"})
        reduced = request(limited["token"], "GET", feedback_path)
        report.update(
            session_id=check.sid,
            original_feedback=original,
            full_agent_feedback=whole,
            restricted_feedback=reduced,
            omitted_source="brief",
        )
        save(check.directory / "access-check.json", report)
        require(reduced["http_status"] == 200, "restricted_feedback_unavailable")
        narrowed = reduced["body"]["result"]["result"]["items"][0]
        require(narrowed.get("read_projection") == "partial", "restricted_feedback_not_projected")
        report["sq08_projection"] = {
            "partial": True,
            "same_feedback_id": narrowed["id"] == original["id"],
            "unchanged_rule_explanations": [
                x["criterion"]
                for x in narrowed["rule_items"]
                if any(
                    y["criterion"] == x["criterion"] and y["explanation"] == x["explanation"]
                    for y in original["rule_items"]
                )
            ],
            "changed_rule_explanations": [
                x["criterion"]
                for x in narrowed["rule_items"]
                if any(
                    y["criterion"] == x["criterion"] and y["explanation"] != x["explanation"]
                    for y in original["rule_items"]
                )
            ],
        }
        response_path = "/feedback/" + original["id"] + "/responses"
        body = check.command(
            "feedback.responses.create",
            {
                "feedback_id": original["id"],
                "feedback_version": original["version"],
                "kind": "objection",
                "section": "rule_items",
                "criterion": "R1.target",
                "text": "请保留证据不足的边界，不将这份记录当作已验证的理解。",
                "evidence": [],
            },
        )
        sent = request(full["token"], "POST", response_path, body)
        require(sent["http_status"] == 200, "feedback_response_not_created")
        require(
            sent["body"]["executor"] == full["delegation"]["executor"],
            "feedback_response_identity_wrong",
        )
        revoke = check.command("delegations.revoke", {"delegation_id": full["delegation"]["id"]})
        before = check.owner("GET", prefix)
        barrier = threading.Barrier(3)

        def race(action):
            barrier.wait()
            if action == "recover":
                return action, request(full["token"], "GET", "/requests/" + body["request_id"])
            if action == "replay":
                return action, request(full["token"], "POST", response_path, body)
            return action, request(
                check.token, "DELETE", "/delegations/" + full["delegation"]["id"], revoke
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = dict(pool.map(race, ("recover", "replay", "revoke")))
        require(outcomes["revoke"]["http_status"] == 200, "revoke_failed")
        for key in ("recover", "replay"):
            require(outcomes[key]["http_status"] in (200, 403), "race_unexpected_result")
        after = request(full["token"], "GET", "/requests/" + body["request_id"])
        require(after["http_status"] == 403, "post_revoke_recovery_allowed")
        require(check.owner("GET", prefix) == before, "replay_changed_world")
        rows = check.owner("GET", prefix + response_path)["result"]["result"]["items"]
        require(len(rows) == 1, "duplicate_feedback_response")
        require(
            C.digest(check.owner("GET", prefix + feedback_path)["result"]["result"]["items"][0])
            == C.digest(original),
            "original_feedback_changed",
        )
        check.human(
            "delegations.revoke",
            "/delegations/" + limited["delegation"]["id"],
            {"delegation_id": limited["delegation"]["id"]},
            method="DELETE",
        )
        report.update(
            status="narrow_feedback_access_verified",
            race=outcomes,
            after_revocation=after,
            response_count=1,
            original_feedback_unchanged=True,
            remaining=[
                "scope mutation and queued-job expiry combinations not covered",
                "no final candidate or normal-v4 claim",
            ],
        )
        save(check.directory / "access-check.json", report)
        return report
    except Exception as error:
        report.update(
            status="incomplete", failure_code=getattr(error, "code", type(error).__name__)
        )
        save(check.directory / "access-check.json", report)
        raise
    finally:
        check.http.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("api-url", "run-dir", "source", "database", "scenario-root"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    print(
        run(
            a.api_url,
            Path(a.run_dir),
            Path(a.source).resolve(),
            Path(a.database).resolve(),
            Path(a.scenario_root).resolve(),
        )["status"]
    )
