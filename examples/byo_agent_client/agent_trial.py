"""Human setup and hand-back for one real, separately launched Codex turn.

This operator never generates the Agent's work or tests. Inspection is read-only;
adoption/submission require a separate explicit CLI invocation with an exact ref.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx

from career_lab.contracts import v2 as C
from career_lab.delegations.credentials import load_credentials, redact
from career_lab.delegations.http_client import safe_id
from examples.byo_agent_client.service_check import ServiceCheck, require
from examples.byo_agent_client.workflow import save


def prepare(api_url, run_dir, language):
    check = ServiceCheck(api_url, run_dir)
    try:
        created = check.owner(
            "POST",
            "/sessions",
            {"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        check.sid, check.token = created["session_id"], created["token"]
        check.secrets.append(check.token)
        require(created["binding"]["workLanguage"] == language, "work_language_mismatch")
        check.trace.update(
            session_id=check.sid, session=redact(created, ""), purpose="human_setup_for_real_agent"
        )
        save(
            check.directory / "owner.json",
            {"api_url": check.api_url, "session_id": check.sid, "token": check.token},
        )
        prefix = "/sessions/" + check.sid
        catalog = check.owner("GET", prefix + "/observation")["result"]["catalog"]
        for name in ("brief", "policy"):
            material = next(row for row in catalog if row["id"] == name)
            ref = {
                "session_id": check.sid,
                "kind": "material",
                "object_id": name,
                "version": material["version"],
            }
            check.human("read_material", "/actions", {"tool": "read_material", "material": ref})
        context = check.owner("GET", prefix + "/workbench")["result"]["result"]
        config = context["timeline"]["workspace"]["config"]
        query = "会议室预约入口在哪里？" if language == "zh" else "Where can I book a meeting room?"
        tested = check.human(
            "tests.create", "/tests", {"query": query, "config_version": config["config_version"]}
        )
        grant = check.human(
            "delegations.create",
            "/delegations",
            {
                "agent_label": "Codex " + language,
                "capabilities": ["read", "act"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
            },
        )["result"]["result"]
        check.secrets.append(grant["token"])
        save(
            check.directory / "delegate.json",
            {"api_url": check.api_url, "session_id": check.sid, "token": grant["token"]},
        )
        check.trace.update(
            status="prepared",
            work_language=language,
            delegation_id=grant["delegation"]["id"],
            authoritative_binding=context["session"],
            human_test=tested["result"]["test"]["id"],
        )
        check.persist()
        save(
            check.directory / "trial.json",
            {
                "session_id": check.sid,
                "work_language": language,
                "binding": context["session"],
                "delegation_id": grant["delegation"]["id"],
                "executor": grant["delegation"]["executor"],
                "status": "awaiting_real_agent",
                "human_handback": False,
            },
        )
        return {"session_id": check.sid, "work_language": language, "status": "prepared"}
    finally:
        check.http.close()


def inspect(run_dir, demo_dir):
    directory, demo_dir = Path(run_dir), Path(demo_dir)
    owner = load_credentials(directory / "owner.json")
    delegate = load_credentials(directory / "delegate.json")
    trial = json.loads((directory / "trial.json").read_text())
    trace = json.loads((demo_dir / "codex-agent-trace.json").read_text())
    require(
        owner.session_id == delegate.session_id == trial["session_id"] == trace["session_id"],
        "session_mismatch",
    )
    require(
        trace.get("model_turn_started") is True and trace.get("automatic_turn_retries") == 0,
        "real_turn_required",
    )
    report = {
        "session_id": owner.session_id,
        "model": trace.get("model"),
        "provider": trace.get("provider"),
        "work_language": trial["work_language"],
        "binding": trial["binding"],
        "turn_status": trace.get("turn_status"),
        "mode": "read_only_actual_service_verification",
        "requests": [],
        "returned_work": [],
        "tests": [],
        "denials": [],
        "counts_by_executor": {},
        "human_handback": False,
        "normal_v4_verified": False,
    }
    with httpx.Client(
        base_url=owner.api_url,
        timeout=20,
        trust_env=False,
        headers={"Authorization": "Bearer " + owner.token},
    ) as client:
        prefix = "/sessions/" + safe_id(owner.session_id)
        for request_id in trace.get("business_request_ids", []):
            response = client.get(prefix + "/requests/" + safe_id(request_id))
            row = {"request_id": request_id, "http_status": response.status_code}
            if response.status_code == 200:
                result = C.RequestResult.model_validate(response.json())
                require(
                    result.executor.model_dump(mode="json") == trial["executor"],
                    "server_executor_mismatch",
                )
                row.update(
                    status=result.status,
                    operation=result.operation,
                    executor=result.executor.model_dump(mode="json"),
                    response=result.response.model_dump(mode="json"),
                )
                kind = result.executor.kind
                report["counts_by_executor"][kind] = report["counts_by_executor"].get(kind, 0) + 1
            else:
                row["status"] = (
                    "not_found_or_not_visible" if response.status_code == 404 else "unconfirmed"
                )
            report["requests"].append(row)
        for suffix, key in [("/work-products", "returned_work"), ("/tests", "tests")]:
            response = client.get(prefix + suffix)
            require(response.status_code == 200, "history_unavailable")
            rows = response.json()["result"]["result"]["tests" if suffix == "/tests" else "items"]
            for row in rows:
                actor = row.get("executor") or row.get("execution", {}).get("executor")
                if actor == trial["executor"]:
                    report[key].append(row)
        # Denied client calls remain protocol evidence, not fabricated server
        # transactions. Never claim absence from a partial or unknown window.
        for event in trace.get("events", []):
            item = event.get("params", {}).get("item", {})
            if (
                event.get("method") == "item/completed"
                and item.get("type") == "mcpToolCall"
                and item.get("status") == "failed"
            ):
                wire = (item.get("result") or {}).get("structuredContent") or {}
                code, status = wire.get("code"), wire.get("status")
                kind = (
                    "permission_denied"
                    if status in (401, 403)
                    else "not_found_or_not_visible"
                    if status == 404
                    else "validation_failed"
                    if status == 422
                    else "client_approval_required"
                    if "approval" in str(item.get("error"))
                    else "unconfirmed"
                )
                report["denials"].append(
                    {
                        "tool": item.get("tool"),
                        "status": "failed",
                        "source": "codex_protocol",
                        "classification": kind,
                        "code": code,
                        "http_status": status,
                        "error": item.get("error"),
                    }
                )
    setup = json.loads((directory / "trace.json").read_text())
    for step in setup.get("steps", []):
        response = step.get("response", {})
        actor = response.get("executor")
        if (
            step.get("status") == "responded"
            and isinstance(actor, dict)
            and actor.get("kind") == "human"
        ):
            report["counts_by_executor"]["human"] = report["counts_by_executor"].get("human", 0) + 1
    report["count_boundary"] = (
        "Only confirmed business requests in this trial, grouped by server executor; control-plane calls and protocol refusals are separate. Not complete session activity or learning efficiency."
    )
    report["status"] = (
        "verified_agent_effects_pending_human"
        if report["returned_work"]
        and report["tests"]
        and all(r["status"] == "completed" for r in report["requests"])
        else "effects_incomplete"
    )
    save(directory / "agent-inspection.json", redact(redact(report, owner.token), delegate.token))
    return report


def handback(run_dir, product_id, version):
    directory = Path(run_dir)
    owner = load_credentials(directory / "owner.json")
    delegate = load_credentials(directory / "delegate.json")
    trial = json.loads((directory / "trial.json").read_text())
    inspected = json.loads((directory / "agent-inspection.json").read_text())
    require(
        owner.session_id == delegate.session_id == trial["session_id"] == inspected["session_id"],
        "session_mismatch",
    )
    selected = next(
        (
            p
            for p in inspected["returned_work"]
            if p["product_id"] == product_id and p["version"] == version
        ),
        None,
    )
    require(
        selected is not None and inspected["status"] == "verified_agent_effects_pending_human",
        "verified_exact_work_required",
    )
    path = directory / "human-handback.json"
    require(not path.exists(), "handback_already_started_recover_original_requests")
    report = {
        "session_id": owner.session_id,
        "status": "prepared",
        "operator": "user_authorized_test_operator",
        "source_product": {"product_id": product_id, "version": version},
        "steps": [],
        "normal_v4_verified": False,
    }

    def persist():
        save(path, redact(redact(report, owner.token), delegate.token))

    persist()
    with httpx.Client(
        base_url=owner.api_url,
        timeout=20,
        trust_env=False,
        headers={"Authorization": "Bearer " + owner.token},
    ) as client:
        prefix = "/sessions/" + safe_id(owner.session_id)

        def get(suffix):
            response = client.get(prefix + suffix)
            require(response.status_code == 200, "human_read_unavailable")
            return response.json()

        def command(method, suffix, operation, payload):
            state = get("")["state"]
            body = C.Command(
                schema_version=2,
                request_id=uuid4().hex,
                expected_version=state["business_seq"],
                expected_workspace_revision=state["workspace_revision"],
                operation=operation,
                payload=payload,
            )
            step = {"command": body.model_dump(mode="json"), "status": "unconfirmed"}
            report["steps"].append(step)
            persist()
            response = client.request(method, prefix + suffix, json=body.model_dump(mode="json"))
            step["http_status"] = response.status_code
            persist()
            require(response.status_code == 200, "human_action_unconfirmed")
            step.update(status="responded", response=response.json())
            persist()
            return response.json()

        live = get("/objects/product/" + safe_id(product_id) + "/" + str(version))["content"]
        require(
            C.digest(live) == C.digest(selected) and live["executor"] == trial["executor"],
            "returned_work_changed",
        )
        adopted = command(
            "POST",
            "/work-products/" + safe_id(product_id) + "/adoption",
            "work_products.adopt",
            {
                "product_id": product_id,
                "product_version": version,
                "expected_head": version,
                "status": "adopted",
            },
        )
        config = get("/workbench")["result"]["result"]["timeline"]["workspace"]["config"]
        config_ref = {
            "session_id": owner.session_id,
            "kind": "config",
            "object_id": config["id"],
            "version": config["version"],
            "config_version": config["config_version"],
        }
        submitted = command(
            "POST",
            "/submissions",
            "submissions.create",
            {
                "decision": "defer_with_conditions",
                "products": [adopted["result"]["ref"]],
                "config": config_ref,
            },
        )
        require(submitted["executor"]["kind"] == "human", "submission_actor_invalid")
        command(
            "DELETE",
            "/delegations/" + safe_id(trial["delegation_id"]),
            "delegations.revoke",
            {"delegation_id": trial["delegation_id"]},
        )
        denied = client.get(
            prefix + "/observation", headers={"Authorization": "Bearer " + delegate.token}
        )
        require(denied.status_code in (401, 403), "revocation_not_verified")
        report.update(
            status="human_adopt_submit_revoke_completed_feedback_pending",
            submission=submitted["result"]["submission"],
            revocation_http_status=denied.status_code,
        )
        persist()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "inspect", "handback"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--language", choices=("zh", "en"))
    parser.add_argument("--demo-dir", type=Path)
    parser.add_argument("--product-id")
    parser.add_argument("--version", type=int)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        if not args.api_url or not args.language:
            parser.error("prepare needs api-url and language")
        result = prepare(args.api_url, args.run_dir, args.language)
    elif args.action == "inspect":
        if not args.demo_dir:
            parser.error("inspect needs demo-dir")
        result = inspect(args.run_dir, args.demo_dir)
    else:
        if not args.product_id or not args.version:
            parser.error("handback needs exact product-id and version")
        result = handback(args.run_dir, args.product_id, args.version)
    print(
        json.dumps(
            {k: result.get(k) for k in ("session_id", "work_language", "status")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
