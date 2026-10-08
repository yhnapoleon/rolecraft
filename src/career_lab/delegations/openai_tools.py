"""OpenAI function descriptions over the existing authorized W06 tools.

No provider SDK or model call is made here. Parameters, business request IDs and
execution remain on the same HTTP boundary used by the MCP client.
"""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import re

from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure


def function_name(tool_name):
    """Stable, collision-resistant alias within OpenAI's 64-character alphabet."""
    readable = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name)[:40]
    return "rolecraft_" + readable + "_" + sha256(tool_name.encode()).hexdigest()[:12]


def function_tools(tools, *, api="responses"):
    """Project available tools without changing the frozen parameter schema."""
    if api not in {"responses", "chat_completions"}:
        raise ValueError("api must be responses or chat_completions")
    result = []
    names = set()
    for tool in sorted(tools, key=lambda item: item.name):
        if not tool.available:
            continue
        alias = function_name(tool.name)
        if alias in names:
            raise RemoteFailure("tool_registration_ambiguous")
        names.add(alias)
        function = {
            "name": alias,
            "description": (
                "RoleCraft " + tool.name + " (" + tool.capability + "). "
                "Uses the current delegated permissions and business rules. "
                "Keep the original command.request_id after an unknown result; "
                "use requests.read to recover it."
            ),
            "parameters": deepcopy(tool.parameters),
            # Strict conversion would make optional/defaulted fields required
            # and change the existing protocol. Server validation still applies.
            "strict": False,
        }
        result.append(
            {"type": "function", **function}
            if api == "responses"
            else {"type": "function", "function": function}
        )
    return result


class OpenAIFunctionClient:
    """Translate a function alias, then use the existing public HTTP client.

    Listing is not authorization to execute later. Both dispatch and the HTTP
    client refresh current permissions; no stale catalogue grants access.
    The caller must explicitly choose which generated call to execute.
    """

    def __init__(self, config_path, *, timeout=15.0):
        self.backend = HttpAgentClient(config_path, timeout=timeout)

    def tools(self, *, api="responses"):
        return function_tools(self.backend.tools(), api=api)

    def call(self, name, arguments):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                raise RemoteFailure("tool_arguments_invalid", 422) from None
        if not isinstance(arguments, dict):
            raise RemoteFailure("tool_arguments_invalid", 422)
        matched = [tool for tool in self.backend.tools() if function_name(tool.name) == name]
        if not matched:
            raise RemoteFailure("tool_unknown", 404)
        if len(matched) != 1:
            raise RemoteFailure("tool_registration_ambiguous")
        # Preserve the HTTP client's current availability/error semantics too.
        return self.backend.call(matched[0].name, arguments)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export currently authorized OpenAI function tools; no model call."
    )
    parser.add_argument(
        "--config", required=True, help="Path to the private W06 delegate config (not a token)."
    )
    parser.add_argument("--api", choices=("responses", "chat_completions"), default="responses")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(OpenAIFunctionClient(args.config).tools(api=args.api), ensure_ascii=False))
    except RemoteFailure as error:
        parser.exit(1, error.code + "\n")
    except (OSError, ValueError):
        parser.exit(1, "private_configuration_or_schema_invalid\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
