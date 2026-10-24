"""MCP copies of tool results, sized for an Agent's context.

The public routes, their responses and the contract stay unchanged; only the copy an Agent
receives over MCP (stdio or Streamable HTTP) differs. Full parameter schemas already reach the
Agent through tools/list, so observation leaves its optional tool catalogue out and tools names
each tool and its availability only.
"""

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.delegations.http_client import RemoteFailure

# Characters in one tool result. Claude Code moves results over 50,000 characters into a local
# file, which the Agent can open only with file or shell permissions.
RESULT_LIMIT = 20_000
# Never callable through this connection: outside the authorization, or never enabled for an
# Agent. Other codes are temporary (session state, an unready module) and stay listed.
CLOSED_TO_AGENT = frozenset(
    {
        "capability_forbidden",
        "action_forbidden",
        "human_adoption_required",
        "private_worker_unavailable",
        "atomic_job_limit_unavailable",
    }
)


def tool_index(rows, failure):
    """Name, capability and availability of each tool this connection can call now or later."""
    try:
        tools = [C.ToolSchema.model_validate(row) for row in rows]
    except (ValidationError, TypeError):
        raise RemoteFailure(failure, 503) from None
    return [
        {
            "name": tool.name,
            "capability": tool.capability,
            "available": tool.available,
            "unavailable_code": tool.unavailable_code,
        }
        for tool in sorted(tools, key=lambda t: t.name)
        if tool.unavailable_code not in CLOSED_TO_AGENT
    ]


def agent_view(name, arguments, result):
    """The MCP copy of one public tool result."""
    if name == "observation":
        # Without its optional tools the copy is still a valid public Observation.
        observation = result.get("result") if isinstance(result, dict) else None
        if not isinstance(observation, dict):
            raise RemoteFailure("observation_contract_invalid", 503)
        rest = {key: value for key, value in observation.items() if key != "tools"}
        return {**result, "result": rest}
    if name == "tools":
        outer = result.get("result") if isinstance(result, dict) else None
        page = outer.get("result") if isinstance(outer, dict) else None
        if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
            raise RemoteFailure("tools_contract_invalid", 503)
        tools = tool_index(page["tools"], "tools_contract_invalid")
        return {**result, "result": {**outer, "result": {**page, "tools": tools}}}
    if name == "materials.list":
        return material_page(arguments.get("query") or {}, result)
    return result


def material_page(query, result):
    """Apply the advertised cursor and limit; the public route returns its first page only."""
    window = C.PageRequest.model_validate({k: query[k] for k in ("cursor", "limit") if k in query})
    outer = result.get("result") if isinstance(result, dict) else None
    page = outer.get("result") if isinstance(outer, dict) else None
    if not isinstance(page, dict) or not isinstance(page.get("materials"), list):
        # Another registration's page shape (results are V2Response, not a fixed model).
        return result
    rows, more = page["materials"], page.get("next_cursor") is not None
    end = window.cursor + window.limit
    if more and end > len(rows):
        # Rows past the route's first page are not in hand; never answer with a short page.
        raise RemoteFailure("materials_page_unavailable", 503)
    next_cursor = end if end < len(rows) or more else None
    sliced = {**page, "materials": rows[window.cursor : end], "next_cursor": next_cursor}
    return {**result, "result": {**outer, "result": sliced}}
