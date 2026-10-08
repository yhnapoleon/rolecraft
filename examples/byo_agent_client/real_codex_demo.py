"""Run one real Codex model turn against the delegated RoleCraft MCP server.

Only --execute starts inference. Preflight checks the existing subscription and
configuration without creating a model turn. A completed turn is NOT product QA
acceptance: inspect recorded server effects and complete the human hand-back.
"""

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import re
import httpx

from career_lab.delegations.credentials import load_credentials, redact
from career_lab.delegations.http_client import HttpAgentClient, safe_id
from examples.byo_agent_client.workflow import save

PROVIDER = "rolecraft_subscription_demo"
AUTHORIZED_WRITES = ("read_material", "work_products.create", "tests.create")
DEMO_TOOLS = (
    "observation",
    "tools",
    "materials.list",
    "tests.list",
    "requests.read",
    "work_products.list",
    "work_products.versions.list",
    *AUTHORIZED_WRITES,
)

DISABLED_FEATURES = (
    "apps",
    "hooks",
    "shell_tool",
    "unified_exec",
    "multi_agent",
    "multi_agent_v2",
    "browser_use",
    "computer_use",
    "image_generation",
    "memories",
    "remote_plugin",
    "fast_mode",
    "goals",
)


class DemoFailure(Exception):
    pass


def session_binding(credentials):
    """Read the fixed work language from the authorized, live v4 context.

    This operator check does not disclose owner credentials or introduce a
    language override. Scoped grants that cannot read this endpoint fail closed.
    """
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
        response = client.get(
            credentials.api_url + "/sessions/" + safe_id(credentials.session_id) + "/workbench",
            headers={"Authorization": "Bearer " + credentials.token},
        )
    if response.status_code != 200:
        raise DemoFailure("authorized_session_binding_unavailable")
    try:
        wire = response.json()
        binding = wire["result"]["result"]["session"]
        if (
            wire.get("schema_version") != 2
            or binding.get("protocol") != 2
            or binding.get("sessionId") != credentials.session_id
            or binding.get("workLanguage") not in {"zh", "en"}
            or not re.fullmatch("[a-f0-9]{64}", binding.get("scenarioHash", ""))
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise DemoFailure("session_binding_invalid") from None
    return {key: binding[key] for key in ("protocol", "sessionId", "workLanguage", "scenarioHash")}


def overrides(config_path, server_cwd):
    server = {
        "command": sys.executable,
        "args": ["-m", "career_lab.mcp", "--config", str(config_path)],
        "cwd": str(server_cwd),
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 30,
        "required": True,
        "enabled_tools": list(DEMO_TOOLS),
        "tools": {name: {"approval_mode": "approve"} for name in AUTHORIZED_WRITES},
    }

    def toml(value):
        if isinstance(value, dict):
            return (
                "{ " + ", ".join(json.dumps(k) + " = " + toml(v) for k, v in value.items()) + " }"
            )
        return json.dumps(value)

    table = toml({"rolecraft": server})
    settings = [
        "mcp_servers=" + table,
        "plugins={}",
        "model_provider=" + json.dumps(PROVIDER),
        'web_search="disabled"',
        "model_providers." + PROVIDER + '.name="RoleCraft subscription demo"',
        "model_providers." + PROVIDER + ".requires_openai_auth=true",
        "model_providers." + PROVIDER + '.wire_api="responses"',
        "model_providers." + PROVIDER + ".request_max_retries=0",
        "model_providers." + PROVIDER + ".stream_max_retries=0",
    ]
    # The operator explicitly authorized this bounded demonstration. Apply that
    # authorization only to these exact local MCP tools in this child process.
    # No global config is changed; RoleCraft still enforces each grant and scope.
    return settings + ["features." + key + "=false" for key in DISABLED_FEATURES]


class CodexAgentDemo:
    def __init__(self, config_path, run_dir, *, executable="codex", server_cwd=None):
        self.config_path = Path(config_path).resolve()
        self.credentials = load_credentials(self.config_path)
        self.directory = Path(run_dir).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.agent_cwd = self.directory / "agent-workspace"
        self.agent_cwd.mkdir(mode=0o700)
        self.thread_id = self.turn_id = None
        self.sent = []
        self.events = []
        self.completed_turns = {}
        self.sequence = 0
        self.report = {
            "status": "preparing",
            "session_id": self.credentials.session_id,
            "api_url": self.credentials.api_url,
            "model_turn_started": False,
            "demo_accepted": False,
            "human_handback": "pending",
            "driver_business_calls": False,
            "automatic_turn_retries": 0,
        }
        self.persist()
        cwd = Path(server_cwd or Path(__file__).resolve().parents[2])
        args = [executable, "app-server", "--stdio"]
        for value in overrides(self.config_path, cwd):
            args.extend(["-c", value])
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"PYTHONPATH", "OPENAI_API_KEY", "CODEX_API_KEY"}
        }
        self.process = subprocess.Popen(
            args,
            cwd=self.agent_cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.messages = queue.Queue()

        def read():
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({"demo_error": "invalid_codex_protocol"})
            self.messages.put({"demo_error": "codex_closed"})

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def persist(self):
        value = {**self.report, "protocol_calls": self.sent, "events": self.events}
        save(self.directory / "codex-agent-trace.json", redact(value, self.credentials.token))

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def receive(self, deadline):
        try:
            value = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            raise DemoFailure("codex_timeout") from None
        if "demo_error" in value:
            raise DemoFailure(value["demo_error"])
        if "id" in value and "method" in value:
            self.send(
                {
                    "id": value["id"],
                    "error": {"code": -32601, "message": "Demo needs explicit operator review"},
                }
            )
            self.report["pending_request_method"] = value["method"]
            self.persist()
            raise DemoFailure("operator_review_required")
        method, params = value.get("method"), value.get("params", {})
        if method and params.get("threadId") == self.thread_id and self.thread_id is not None:
            if method in {
                "item/started",
                "item/completed",
                "turn/started",
                "turn/completed",
                "error",
                "thread/tokenUsage/updated",
            }:
                self.events.append({"method": method, "params": params})
                self.persist()
            item = params.get("item", {})
            if item.get("type") in {
                "commandExecution",
                "fileChange",
                "webSearch",
                "imageGeneration",
                "collabAgentToolCall",
            }:
                raise DemoFailure("unexpected_non_rolecraft_action")
            if item.get("type") == "mcpToolCall" and item.get("server") != "rolecraft":
                raise DemoFailure("unexpected_mcp_server")
            if method == "turn/started":
                self.turn_id = params["turn"]["id"]
                self.report.update(turn_id=self.turn_id, model_turn_started=True)
                self.persist()
            if method == "error" and params.get("willRetry") is True:
                raise DemoFailure("unexpected_model_retry")
            if method == "turn/completed":
                self.completed_turns[params["turn"]["id"]] = params["turn"]
        return value

    def rpc(self, method, params, *, seconds=30):
        self.sequence += 1
        identifier = self.sequence
        self.sent.append(method)
        self.persist()
        self.send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = self.receive(deadline)
            if value.get("id") == identifier and "method" not in value:
                if "error" in value:
                    raise DemoFailure("codex_rpc_failed")
                return value["result"]
        raise DemoFailure("codex_timeout")

    def preflight(self):
        self.rpc(
            "initialize",
            {
                "clientInfo": {"name": "rolecraft-real-agent-demo", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized"})
        account = self.rpc("account/read", {"refreshToken": False}).get("account") or {}
        if account.get("type") != "chatgpt":
            raise DemoFailure("existing_chatgpt_subscription_required")
        self.report["auth"] = {"type": account["type"], "plan_type": account.get("planType")}
        config = self.rpc("config/read", {"includeLayers": False})["config"]
        provider = config.get("model_providers", {}).get(PROVIDER, {})
        expected = config.get("features", {})
        server = config.get("mcp_servers", {}).get("rolecraft", {})
        if (
            config.get("model_provider") != PROVIDER
            or config.get("web_search") != "disabled"
            or provider.get("request_max_retries") != 0
            or provider.get("stream_max_retries") != 0
            or any(expected.get(key) is not False for key in DISABLED_FEATURES)
        ):
            raise DemoFailure("effective_demo_configuration_mismatch")
        if set(server.get("enabled_tools", [])) != set(DEMO_TOOLS) or any(
            server.get("tools", {}).get(name, {}).get("approval_mode") != "approve"
            for name in AUTHORIZED_WRITES
        ):
            raise DemoFailure("explicit_demo_tool_authorization_missing")
        self.report.update(
            status="preflight_complete",
            retry_configuration={"request": 0, "stream": 0},
            disabled_features=list(DISABLED_FEATURES),
            allowed_tools=list(DEMO_TOOLS),
            explicitly_authorized_writes=list(AUTHORIZED_WRITES),
        )
        self.persist()
        return self.report

    def run_turn(self, task, *, language, model=None, timeout=300):
        if self.report["status"] != "preflight_complete" or self.report.get(
            "model_turn_requested", False
        ):
            raise DemoFailure("fresh_preflight_required")
        if language not in {"zh", "en"} or not task.strip() or not 1 <= timeout <= 900:
            raise DemoFailure("demo_input_invalid")
        binding = session_binding(self.credentials)
        if binding["workLanguage"] != language:
            raise DemoFailure("work_language_mismatch")
        self.report.update(
            session_binding=binding, requested_language=language, work_language_verified=True
        )
        self.persist()
        # Verify the delegate/source boundary before starting a paid/quota turn.
        observation = HttpAgentClient(self.config_path).observation(self.credentials.session_id)
        if not observation.visible_sources:
            raise DemoFailure("human_investigation_required")
        if "submit" in {tool.capability for tool in observation.tools if tool.available}:
            raise DemoFailure("human_submission_must_remain_separate")
        params = {
            "cwd": str(self.agent_cwd),
            "ephemeral": True,
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "baseInstructions": "You are the learner's external Agent. Use only the authorized RoleCraft MCP tools. "
            "Do not use files, shell, browser, other servers or other agents. Respect source permissions. "
            "Keep request_id for recovery after unknown outcomes. Do not adopt or formally submit. "
            "Return actual product/test references and unresolved issues for the human to review.",
        }
        if model:
            params["model"] = model
        started = self.rpc("thread/start", params)
        self.thread_id = started["thread"]["id"]
        if (
            started.get("modelProvider") != PROVIDER
            or started.get("sandbox", {}).get("type") != "readOnly"
        ):
            raise DemoFailure("codex_execution_profile_mismatch")
        self.report.update(
            model=started.get("model"),
            provider=started.get("modelProvider"),
            thread_id=self.thread_id,
            status="running",
            model_turn_requested=True,
        )
        self.persist()
        prompt = (
            "Work in "
            + ("Chinese" if language == "zh" else "English")
            + ". RoleCraft session_id: "
            + self.credentials.session_id
            + ". Begin by reading the current observation.\n\n"
            + task
        )
        try:
            turn = self.rpc(
                "turn/start",
                {"threadId": self.thread_id, "input": [{"type": "text", "text": prompt}]},
                seconds=45,
            )["turn"]
            self.turn_id = turn["id"]
            self.report.update(turn_id=self.turn_id, model_turn_started=True)
            self.persist()
            deadline = time.monotonic() + timeout
            while self.turn_id not in self.completed_turns:
                if time.monotonic() >= deadline:
                    raise DemoFailure("codex_turn_timeout")
                self.receive(deadline)
            completed = self.completed_turns[self.turn_id]
            self.report["turn_status"] = completed["status"]
            calls = [
                e["params"]["item"]
                for e in self.events
                if e["method"] == "item/completed"
                and e["params"].get("item", {}).get("type") == "mcpToolCall"
            ]
            self.report["model_mcp_calls"] = len(calls)
            self.report["business_request_ids"] = list(
                dict.fromkeys(
                    call.get("arguments", {}).get("command", {}).get("request_id")
                    for call in calls
                    if isinstance(call.get("arguments"), dict)
                    and call.get("arguments", {}).get("command", {}).get("request_id")
                )
            )
            if completed["status"] != "completed":
                raise DemoFailure("codex_turn_" + completed["status"])
            if not calls:
                raise DemoFailure("no_model_mcp_calls_observed")
            self.report["status"] = "agent_turn_completed_pending_product_verification"
            self.persist()
            return self.report
        except Exception as error:
            self.report.update(
                status="incomplete",
                failure_code=str(error) if isinstance(error, DemoFailure) else "demo_unconfirmed",
            )
            self.persist()
            self.interrupt()
            raise

    def interrupt(self):
        if self.thread_id and self.turn_id and self.turn_id not in self.completed_turns:
            try:
                self.rpc(
                    "turn/interrupt",
                    {"threadId": self.thread_id, "turnId": self.turn_id},
                    seconds=5,
                )
            except Exception:
                pass

    def close(self):
        self.interrupt()
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        self.reader.join(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Start one real model turn using the existing subscription",
    )
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--language", choices=("zh", "en"))
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    if args.execute and (not args.task_file or not args.language):
        parser.error("--execute needs --task-file and --language")
    demo = None
    try:
        demo = CodexAgentDemo(args.config, args.run_dir)
        demo.preflight()
        if args.execute:
            demo.run_turn(
                args.task_file.read_text(),
                language=args.language,
                model=args.model,
                timeout=args.timeout,
            )
        print(demo.report["status"] + "; product acceptance remains unverified.")
        return 0
    except Exception as error:
        if demo:
            demo.report.update(
                status="incomplete",
                failure_code=str(error) if isinstance(error, DemoFailure) else "demo_unconfirmed",
            )
            demo.persist()
        print(
            "Incomplete; preserve the trace and original service requests. No automatic retry.",
            file=sys.stderr,
        )
        return 1
    finally:
        if demo:
            demo.close()


if __name__ == "__main__":
    raise SystemExit(main())
