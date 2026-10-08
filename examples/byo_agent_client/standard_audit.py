"""Public HTTP/official MCP audit against an already pinned standard service.

The supplied worker runs the same frozen standard CLI and database. No custom
history reader, role generator, storage handler or private source is installed.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from examples.byo_agent_client.service_check import ServiceCheck, require
from examples.byo_agent_client.codex_client import CodexMcpClient
from examples.byo_agent_client.workflow import save


FORBIDDEN = {
    "generation_audit",
    "prompt_messages",
    "prompt_hash",
    "context_hash",
    "history_revision",
    "private_prompt",
    "received_shares",
    "internal_disclosures",
    "role_context",
}


def public(value):
    if isinstance(value, dict):
        require(not (set(value) & FORBIDDEN), "private_role_field_exposed")
        for child in value.values():
            public(child)
    elif isinstance(value, list):
        for child in value:
            public(child)


def run(api_url, run_dir, source, database, scenario_root, language):
    check = ServiceCheck(api_url, run_dir)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        PYTHONPATH=str(source / "src"),
        CAREER_LAB_SCENARIO_V2=str(scenario_root),
        PYTHONDONTWRITEBYTECODE="1",
    )
    outputs = []
    denied = []
    summary = {
        "standard_worker": True,
        "history_bridge": False,
        "normal_v4_verified": False,
        "work_language": language,
        "roles": [],
        "public_reads": outputs,
        "denials": denied,
        "model_quality_verified": False,
    }

    def keep():
        save(check.directory / "boundary-audit.json", summary)

    def read(suffix, token, *, expected=200):
        response = check.http.get(
            "/sessions/" + check.sid + suffix, headers={"Authorization": "Bearer " + token}
        )
        require(response.status_code == expected, "public_read_unexpected_status")
        value = response.json()
        public(value)
        outputs.append({"path": suffix, "status": response.status_code, "response": value})
        keep()
        return value

    def grant(capabilities, allowed_objects=None):
        payload = {
            "agent_label": "W06 public-boundary audit",
            "capabilities": capabilities,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        }
        if allowed_objects is not None:
            payload["allowed_objects"] = allowed_objects
        result = check.human("delegations.create", "/delegations", payload)["result"]["result"]
        check.secrets.append(result["token"])
        check.persist()
        return result

    try:
        created = check.owner(
            "POST",
            "/sessions",
            {"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        check.sid, check.token = created["session_id"], created["token"]
        check.secrets.append(check.token)
        check.trace.update(session_id=check.sid, purpose="standard_role_privacy_and_denials")
        save(
            check.directory / "owner.json",
            {"api_url": check.api_url, "session_id": check.sid, "token": check.token},
        )
        summary["session_id"] = check.sid
        summary["binding"] = created["binding"]
        marker = "UNSHARED-WORK-" + uuid4().hex
        work = check.human(
            "work_products.create",
            "/work-products",
            {"kind": "text", "title": "Private working note", "content": marker},
        )["result"]["ref"]
        read_grant = grant(["read"])
        scoped = grant(["read", "act"], ["brief"])
        for role in ("supervisor", "business_lead", "tech_lead"):
            asked = check.human(
                "turns.create",
                "/turns",
                {
                    "role_id": role,
                    "text": "请说明你的职责与当前可引用的资料，不要替我推断私人草稿。"
                    if language == "zh"
                    else "Explain your responsibilities and current source references; do not infer my private drafts.",
                },
            )
            original = check.trace["steps"][-1]["command"]
            with (check.directory / "worker.log").open("a") as log:
                result = subprocess.run(
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
            require(result.returncode == 0, "standard_role_worker_failed")
            request = read("/requests/" + original["request_id"], check.token)
            require(
                request["jobs"] and all(j["status"] == "completed" for j in request["jobs"]),
                "role_job_not_complete",
            )
            timeline = read("/timeline", check.token)["result"]["result"]
            replies = [
                o
                for o in timeline["objects"]
                if o["ref"]["kind"] == "role_reply" and o["content"]["role_id"] == role
            ]
            require(len(replies) == 1, "actual_reply_missing")
            ref = replies[0]["ref"]
            body = replies[0]["content"]
            require(marker not in json.dumps(body), "unshared_draft_disclosed")
            check.human("turns.display", "/turns/display", {"ref": ref})
            for who, token in [("human", check.token), ("read_delegate", read_grant["token"])]:
                obj = read(
                    "/objects/role_reply/" + ref["object_id"] + "/" + str(ref["version"]), token
                )
                require(obj["content"]["text"] == body["text"], "reply_body_changed")
                obs = read("/observation?limit=1&since_seq=0", token)["result"]
                require(
                    any(
                        f.get("text") == body["text"] and f.get("acquired_via") == "displayed"
                        for f in obs["visible_sources"]
                    ),
                    "actual_display_not_recovered",
                )
            summary["roles"].append(
                {"role": role, "reply": ref, "text": body["text"], "not_shared_marker_absent": True}
            )
            keep()
        # A scoped Agent receives a real response, not an unavailable endpoint.
        obs = read("/observation?limit=1&since_seq=0", scoped["token"])["result"]
        require(
            {m["id"] for m in obs["catalog"]} == {"brief"} and not obs["visible_sources"],
            "scoped_observation_expanded",
        )
        for suffix in (
            "/objects/product/" + work["object_id"] + "/1",
            "/objects/product/missing-product/1",
        ):
            read(suffix, scoped["token"], expected=404)
            denied.append(
                {
                    "source": "raw_http",
                    "status": 404,
                    "operation": "objects.read",
                    "executor": scoped["delegation"]["executor"],
                }
            )
        command = check.command("submissions.create", {"decision": "no_go", "products": [work]})
        response = check.http.post(
            "/sessions/" + check.sid + "/submissions",
            json=command,
            headers={"Authorization": "Bearer " + read_grant["token"]},
        )
        require(response.status_code == 403, "read_delegate_gained_submit")
        denied.append(
            {
                "source": "raw_http",
                "status": response.status_code,
                "code": response.json().get("code"),
                "request_id": command["request_id"],
                "operation": command["operation"],
                "executor": read_grant["delegation"]["executor"],
            }
        )
        cfg = check.directory / "read-delegate.json"
        save(cfg, {"api_url": api_url, "session_id": check.sid, "token": read_grant["token"]})
        mcp = CodexMcpClient(cfg, cwd=Path(__file__).resolve().parents[2])
        try:
            value = mcp.call(
                "observation", {"session_id": check.sid, "query": {"since_seq": 0, "limit": 1}}
            )
            public(value)
            require(not value.get("isError"), "mcp_observation_failed")
            fragments = value["structuredContent"]["result"]["visible_sources"]
            summary["mcp_observation"] = value["structuredContent"]
            keep()
            require(
                all(
                    any(row["text"] == fragment["text"] for fragment in fragments)
                    for row in summary["roles"]
                ),
                "mcp_display_missing",
            )
            summary["official_codex_mcp_calls"] = mcp.calls
        finally:
            mcp.close()
        for issued in (read_grant, scoped):
            check.human(
                "delegations.revoke",
                "/delegations/" + issued["delegation"]["id"],
                {"delegation_id": issued["delegation"]["id"]},
                method="DELETE",
            )
        summary["status"] = "standard_current_role_privacy_verified"
        summary["legacy_r1_history"] = "not_verified_here"
        check.trace["status"] = "completed"
        check.persist()
        keep()
        return summary
    except Exception as error:
        summary.update(
            status="incomplete", failure_code=getattr(error, "code", type(error).__name__)
        )
        keep()
        raise
    finally:
        check.http.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("api-url", "run-dir", "source", "database", "scenario-root", "language"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    value = run(
        a.api_url,
        Path(a.run_dir),
        Path(a.source).resolve(),
        Path(a.database).resolve(),
        Path(a.scenario_root).resolve(),
        a.language,
    )
    print(value["status"])
