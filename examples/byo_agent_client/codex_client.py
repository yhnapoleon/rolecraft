"""Official installed Codex MCP transport probe without starting a model turn.

Uses an ephemeral protocol session, transient configuration overrides and only
explicit tool calls. Does not edit the user's Codex configuration or credentials.
"""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


class CodexMcpClient:
    def __init__(self, config_path, *, cwd, executable="codex"):
        config_path = str(Path(config_path).resolve())
        self.cwd = str(Path(cwd).resolve())
        server = {
            "command": sys.executable,
            "args": ["-m", "career_lab.mcp", "--config", config_path],
            "cwd": self.cwd,
            "startup_timeout_sec": 20,
            "tool_timeout_sec": 30,
            "required": True,
        }
        # JSON strings/arrays are valid TOML values; the table is serialized
        # explicitly so no shell interpolates credentials, paths or commands.
        table = (
            "{ rolecraft = { "
            + ", ".join(key + " = " + json.dumps(value) for key, value in server.items())
            + " } }"
        )
        self.process = subprocess.Popen(
            [
                executable,
                "app-server",
                "--stdio",
                "-c",
                "mcp_servers=" + table,
                "-c",
                "plugins={}",
                "-c",
                "features.apps=false",
            ],
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        )
        self.messages = queue.Queue()
        self.stderr = []
        self.calls = []
        self.sequence = 0

        def output():
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({"probe_error": "invalid_client_protocol"})
            self.messages.put({"probe_error": "client_closed"})

        def errors():
            for line in self.process.stderr:
                self.stderr.append(line)

        self.reader = threading.Thread(target=output, daemon=True)
        self.reader.start()
        self.errors = threading.Thread(target=errors, daemon=True)
        self.errors.start()
        try:
            self.rpc(
                "initialize",
                {
                    "clientInfo": {"name": "rolecraft-mcp-transport-check", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.send({"method": "initialized"})
            started = self.rpc(
                "thread/start",
                {
                    "cwd": self.cwd,
                    "ephemeral": True,
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                    "config": {
                        "mcp_servers": {"rolecraft": server},
                        "plugins": {},
                        "features.apps": False,
                    },
                },
            )
            self.thread_id = started["thread"]["id"]
        except Exception:
            self.close()
            raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def rpc(self, method, params, *, seconds=40):
        self.sequence += 1
        identifier = self.sequence
        self.calls.append(method)
        self.send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + seconds
        while True:
            try:
                value = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("codex_client_timeout") from None
            if "probe_error" in value:
                raise RuntimeError(value["probe_error"])
            if value.get("id") == identifier:
                if "error" in value:
                    raise RuntimeError(
                        "codex_client_rpc_failed: " + str(value["error"].get("code"))
                    )
                return value["result"]
            # Never accept an unexpected approval or external server request.
            if "id" in value and "method" in value:
                self.send(
                    {
                        "id": value["id"],
                        "error": {
                            "code": -32601,
                            "message": "Transport probe does not approve requests",
                        },
                    }
                )
            if time.monotonic() >= deadline:
                raise RuntimeError("codex_client_timeout")

    def inventory(self):
        return self.rpc(
            "mcpServerStatus/list",
            {"threadId": self.thread_id, "serverName": "rolecraft", "detail": "toolsAndAuthOnly"},
        )

    def call(self, name, arguments):
        return self.rpc(
            "mcpServer/tool/call",
            {
                "threadId": self.thread_id,
                "server": "rolecraft",
                "tool": name,
                "arguments": arguments,
            },
        )

    def close(self):
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
        self.errors.join(1)
