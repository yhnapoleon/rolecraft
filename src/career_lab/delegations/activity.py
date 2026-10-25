"""The learner's own Agent activity: one row per MCP tool call and per connection, per session.

Append only. A row keeps the time, the delegation, the tool, its capability, the objects it
touched (kind, id, version and a short title when the call itself carried one) and the outcome
code. Tokens, arguments, result bodies and request headers are never stored.

Connection state is derived from the rows plus a per-delegation presence stamp that every MCP
request refreshes (tools/list and ping included), so an idle but running client still shows.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update

from career_lab.engineer.seeded import SEEDED_TICKETS
from career_lab.storage.v2_tables import v2_credentials

_META = MetaData()
# Separate integration tables; the frozen v2 tables are not altered.
agent_activity = Table(
    "v4_agent_activity",
    _META,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String, nullable=False, index=True),
    Column("delegation_id", String, nullable=False),
    Column("at", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("tool", String, nullable=True),
    Column("capability", String, nullable=True),
    Column("objects", Text, nullable=False),
    Column("count", Integer, nullable=True),
    Column("status", String, nullable=False),
    Column("error_code", String, nullable=True),
    Column("client_name", String, nullable=True),
    Column("client_version", String, nullable=True),
)
agent_presence = Table(
    "v4_agent_presence",
    _META,
    Column("session_id", String, primary_key=True),
    Column("delegation_id", String, primary_key=True),
    Column("last_seen", String, nullable=False),
    Column("client_name", String, nullable=True),
    Column("client_version", String, nullable=True),
)

# A client that has made no request for this long counts as idle, not connected.
CONNECTED_WINDOW = timedelta(minutes=10)
PAGE_LIMIT = 200
MAX_OBJECTS = 24
TITLE_LIMIT = 120
# Request ID keys that name one object, by the kind shown to the person.
ID_KINDS = {
    "product_id": "product",
    "item_id": "work_item",
    "review_id": "review",
    "feedback_id": "feedback",
    "ticket_id": "ticket",
    "import_id": "import",
    "request_id": "request",
}
log = logging.getLogger(__name__)


def _now():
    return datetime.now(UTC)


def _text(value, limit=TITLE_LIMIT):
    if not isinstance(value, str) or not value.strip():
        return None
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _version(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _page(structured):
    """The innermost result dict of a gateway read (V2Response nests one or two levels)."""
    page = structured
    for _ in range(3):
        inner = page.get("result") if isinstance(page, dict) else None
        if not isinstance(inner, dict):
            break
        page = inner
    return page if isinstance(page, dict) else {}


def ticket_name(title):
    """The short name of a seeded ticket for its full title in either language, else the title."""
    for entry in SEEDED_TICKETS.values():
        for language, full in entry.get("title", {}).items():
            if title == full and entry.get("short", {}).get(language):
                return entry["short"][language]
    return title


def touched(name, arguments, structured):
    """Objects one call touched and, for list reads, how many rows it returned."""
    arguments = arguments if isinstance(arguments, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    query = arguments.get("query") if isinstance(arguments.get("query"), dict) else {}
    command = arguments.get("command") if isinstance(arguments.get("command"), dict) else {}
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    found: list[dict] = []

    def add(kind, object_id, version=None, title=None):
        if not isinstance(kind, str) or not isinstance(object_id, str) or not object_id:
            return
        key = (kind, object_id)
        for row in found:
            if (row["kind"], row["id"]) == key:
                row["version"] = row["version"] or _version(version)
                row["title"] = row["title"] or _text(title)
                return
        if len(found) < MAX_OBJECTS:
            found.append(
                {"kind": kind, "id": object_id, "version": _version(version), "title": _text(title)}
            )

    page = _page(structured)
    count = None
    if name == "objects.read":
        ref = query.get("ref") if isinstance(query.get("ref"), dict) else {}
        content = structured.get("content") if isinstance(structured.get("content"), dict) else {}
        title = page.get("title") or content.get("title")
        add(ref.get("kind"), ref.get("object_id"), ref.get("version"), title)
    elif name == "materials.list" and isinstance(page.get("materials"), list):
        rows = [r for r in page["materials"] if isinstance(r, dict)]
        count = len(rows)
        for row in rows:
            add("material", row.get("id"), row.get("version"), row.get("title"))
    else:
        lists = [v for v in page.values() if isinstance(v, list)] if name.endswith(".list") else []
        if lists:
            count = len(lists[0])
    # read_material names the document it read as an object reference.
    material = payload.get("material") if isinstance(payload.get("material"), dict) else None
    if material:
        add(material.get("kind"), material.get("object_id"), material.get("version"))
    # Reading tickets names them; later rows on the same ticket borrow the name. A seeded
    # ticket is named by its short name, not its full title.
    if name == "engineer.tickets.read":
        rows = page.get("tickets") if isinstance(page.get("tickets"), list) else []
        for ticket in [*rows, page.get("ticket")]:
            if isinstance(ticket, dict):
                add("ticket", ticket.get("id"), title=ticket_name(ticket.get("title")))
    # Engineer writes answer with the experiment or draft they recorded.
    for key, kind in (("reproduction", "experiment"), ("trial", "experiment"), ("draft", "draft")):
        record = page.get(key)
        if isinstance(record, dict):
            add(kind, record.get("id"))
    for source in (query, payload):
        for key, kind in ID_KINDS.items():
            if key == "request_id" and name != "requests.read":
                continue
            add(kind, source.get(key), title=source.get("title") if source is payload else None)
    if name in {"work_products.create", "work_items.create", "tests.create"}:
        title = payload.get("title") or payload.get("question")
    else:
        title = None
    # A write answers with the exact objects it created or changed.
    for ref in structured.get("objects") or ():
        if isinstance(ref, dict) and ref.get("kind") not in {"event", "transaction"}:
            add(ref.get("kind"), ref.get("object_id"), ref.get("version"), title)
    return found, count


class ActivityLog:
    """Writes never fail the Agent's call: a storage error is logged and the call goes on."""

    def __init__(self, engine):
        self.engine = engine
        _META.create_all(engine)

    def _presence(self, c, session_id, delegation_id, at, client):
        row = (
            c.execute(
                select(agent_presence).where(
                    agent_presence.c.session_id == session_id,
                    agent_presence.c.delegation_id == delegation_id,
                )
            )
            .mappings()
            .first()
        )
        values = {"last_seen": at.isoformat()}
        if client:
            values.update(client_name=client[0], client_version=client[1])
        if row is None:
            c.execute(
                insert(agent_presence).values(
                    session_id=session_id, delegation_id=delegation_id, **values
                )
            )
        else:
            c.execute(
                update(agent_presence)
                .where(
                    agent_presence.c.session_id == session_id,
                    agent_presence.c.delegation_id == delegation_id,
                )
                .values(**values)
            )
        return row

    def seen(self, session_id, delegation_id, client=None):
        """Any MCP request. A first request, a new client, or one after an idle gap connects."""
        try:
            at = _now()
            with self.engine.begin() as c:
                before = self._presence(c, session_id, delegation_id, at, client)
                if client is None:
                    return
                fresh = (
                    before is None
                    or (before["client_name"], before["client_version"]) != tuple(client)
                    or at - datetime.fromisoformat(before["last_seen"]) > CONNECTED_WINDOW
                )
                if fresh:
                    c.execute(
                        insert(agent_activity).values(
                            session_id=session_id,
                            delegation_id=delegation_id,
                            at=at.isoformat(),
                            kind="connected",
                            objects="[]",
                            status="ok",
                            client_name=client[0],
                            client_version=client[1],
                        )
                    )
        except Exception as error:  # noqa: BLE001 - logging must not break the Agent's call
            log.warning("agent activity not recorded: %s", type(error).__name__)

    def called(self, session_id, delegation_id, tool, capability, arguments, result):
        try:
            structured = result.get("structuredContent") if isinstance(result, dict) else None
            failed = bool(isinstance(result, dict) and result.get("isError"))
            code = structured.get("code") if failed and isinstance(structured, dict) else None
            if failed and code is None:
                content = result.get("content") or [{}]
                code = content[0].get("text") if isinstance(content[0], dict) else None
            objects, count = touched(tool, arguments, None if failed else structured)
            at = _now()
            with self.engine.begin() as c:
                self._presence(c, session_id, delegation_id, at, None)
                c.execute(
                    insert(agent_activity).values(
                        session_id=session_id,
                        delegation_id=delegation_id,
                        at=at.isoformat(),
                        kind="tool_call",
                        tool=tool,
                        capability=capability,
                        objects=json.dumps(objects, ensure_ascii=False, separators=(",", ":")),
                        count=count,
                        status="error" if failed else "ok",
                        error_code=_text(code, 80) if failed else None,
                    )
                )
        except Exception as error:  # noqa: BLE001 - logging must not break the Agent's call
            log.warning("agent activity not recorded: %s", type(error).__name__)

    def page(self, session_id, after=None, titles=None, limit=PAGE_LIMIT):
        """Rows after a cursor (the last seq seen), oldest first, and the connection state."""
        after = after or 0
        with self.engine.connect() as c:
            rows = (
                c.execute(
                    select(agent_activity)
                    .where(agent_activity.c.session_id == session_id, agent_activity.c.seq > after)
                    .order_by(agent_activity.c.seq)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            presence = (
                c.execute(
                    select(agent_presence)
                    .where(agent_presence.c.session_id == session_id)
                    .order_by(agent_presence.c.last_seen.desc())
                )
                .mappings()
                .all()
            )
            live = live_grants(c, session_id)
            # Titles a call carried (a material list, a read) name the same object in later rows.
            known = {}
            for (objects,) in c.execute(
                select(agent_activity.c.objects).where(agent_activity.c.session_id == session_id)
            ):
                for obj in json.loads(objects):
                    if obj.get("title"):
                        known[(obj["kind"], obj["id"])] = obj["title"]
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in rows:
            objects = json.loads(row["objects"])
            for obj in objects:
                if obj.get("title") is None:
                    obj["title"] = known.get((obj["kind"], obj["id"]))
                if obj.get("title") is None and titles is not None:
                    obj["title"] = titles(obj["kind"], obj["id"], obj.get("version"))
            items.append(
                {
                    "seq": row["seq"],
                    "at": row["at"],
                    "delegation_id": row["delegation_id"],
                    "kind": row["kind"],
                    "tool": row["tool"],
                    "capability": row["capability"],
                    "objects": objects,
                    "count": row["count"],
                    "status": row["status"],
                    "error_code": row["error_code"],
                    "client": (
                        {"name": row["client_name"], "version": row["client_version"] or ""}
                        if row["client_name"]
                        else None
                    ),
                }
            )
        now = _now()
        state, client, last_seen = "none", None, None
        if presence:
            last_seen = presence[0]["last_seen"]
            client = presence[0]["client_name"]
            # Connected: a grant still in force made a request in the window. A revoked or
            # expired grant's agent can no longer reach the workspace, however recent it was.
            state = (
                "connected"
                if any(
                    row["delegation_id"] in live
                    and now - datetime.fromisoformat(row["last_seen"]) <= CONNECTED_WINDOW
                    for row in presence
                )
                else "idle"
            )
        return {
            "schema_version": 2,
            "items": items,
            "next_cursor": items[-1]["seq"] if items else after,
            "complete": not more,
            "connection": {"state": state, "client": client, "last_seen": last_seen},
            "checked_at": now.isoformat(),
        }


def live_grants(c, session_id):
    """Agent grants of the session that are neither revoked nor expired, by server time."""
    now = _now()
    live = set()
    rows = c.execute(
        select(v2_credentials.c.id, v2_credentials.c.context, v2_credentials.c.revoked).where(
            v2_credentials.c.session_id == session_id
        )
    )
    for identifier, context, revoked in rows:
        if revoked:
            continue
        auth = json.loads(context)
        expires = auth.get("expires_at")
        if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) <= now:
            continue
        live.add(identifier)
    return live


def object_titles(view):
    """Titles of this session's own objects (work, tests, tasks), read once per page."""
    latest: dict[tuple[str, str], tuple[int, str | None]] = {}
    for row in view.objects:
        content = row.content if isinstance(row.content, dict) else {}
        title = next(
            (
                _text(content.get(k))
                for k in ("title", "question", "name", "summary")
                if _text(content.get(k))
            ),
            None,
        )
        key = (row.ref.kind, row.ref.object_id)
        if key not in latest or row.ref.version >= latest[key][0]:
            latest[key] = (row.ref.version, title)

    def lookup(kind, object_id, version):
        hit = latest.get((kind, object_id))
        return hit[1] if hit else None

    return lookup
