"""Build delegation observations from public query handlers and authorized history.

The shared store supplies history inside the current query transaction. This
module never reads SQL, private scenario state, role prompts or source files.
"""

from dataclasses import dataclass
from typing import Callable

from career_lab.api.modules import V2Response
from career_lab.contracts import v2 as C
from career_lab.storage.role_memory import RoleDisplay, RoleReply
from career_lab.storage.v2_store import TransactionView
from .observation import PublicSources


@dataclass(frozen=True)
class MaterialReadReceipt:
    event: C.PublicEvent
    fragments: tuple[C.DisclosedFragment, ...]


@dataclass(frozen=True)
class PublicHistoryWindow:
    as_of: C.VersionPoint
    events: tuple[C.PublicEvent, ...]
    material_reads: tuple[MaterialReadReceipt, ...]
    next_seq: int
    acquisitions_complete: bool


def stored_history(view, page, auth):
    """The integration-owned transaction port; no out-of-transaction fallback."""
    reader = getattr(view, "public_history", None)
    if not callable(reader):
        raise C.ProtocolError("observation_history_unavailable", status=503)
    return reader(page, auth)


def point(state):
    return C.VersionPoint(
        **state.model_dump(include={"business_seq", "workspace_revision", "storage_revision"})
    )


def no_later(left, right):
    return all(
        getattr(left, field) <= getattr(right, field)
        for field in ("business_seq", "workspace_revision", "storage_revision")
    )


class WorkspaceSources:
    """Production projection over the same public view used by Gateway.query.

    history_reader(view, page, auth) must return an authoritative same-window
    PublicHistoryWindow. It is the sole integration seam still missing in c9.
    """

    def __init__(self, registry, *, history_reader: Callable = stored_history):
        self.registry, self.history_reader = registry, history_reader
        self.unavailable_code = (
            "observation_history_unavailable"
            if history_reader is stored_history
            and "public_history" not in TransactionView.__dataclass_fields__
            else None
        )

    def catalog(self, view, auth):
        operation = self.registry.operations.get("materials.list")
        if operation is None:
            if "material" in self.registry.reference_resolvers:
                raise C.ProtocolError("material_catalog_unavailable", status=503)
            return ()
        if (
            operation.mutates
            or operation.capability != "read"
            or operation.response_model is not V2Response
        ):
            raise C.ProtocolError("material_catalog_contract_invalid", status=503)
        if auth.allowed_actions is not None and "materials.list" not in auth.allowed_actions:
            return ()
        cursor = 0
        result = []
        while True:
            page = C.ResourcePage(cursor=cursor, limit=100)
            data = V2Response.model_validate(operation.handler(view, page, auth)).result
            if (
                data.get("retrieved_at") != point(view.state).model_dump(mode="json")
                or data.get("catalog_is_not_acquired_knowledge") is not True
            ):
                raise C.ProtocolError("material_catalog_window_invalid", status=503)
            result.extend(C.MaterialMetadata.model_validate(row) for row in data["materials"])
            following = data.get("next_cursor")
            if following is None:
                return tuple(result)
            if not isinstance(following, int) or following <= cursor:
                raise C.ProtocolError("material_catalog_cursor_invalid", status=503)
            cursor = following

    def __call__(self, view, page, auth):
        at = point(view.state)
        if page.cursor or (page.as_of_seq is not None and page.as_of_seq != at.business_seq):
            raise C.ProtocolError("observation_window_unsupported", status=422)
        history = self.history_reader(view, page, auth)
        if (
            not isinstance(history, PublicHistoryWindow)
            or history.as_of != at
            or history.acquisitions_complete is not True
        ):
            raise C.ProtocolError("observation_history_unavailable", status=503)
        if view.reference_allowed is None:
            raise C.ProtocolError("reference_view_required", status=503)

        def permitted(ref):
            if ref.session_id != auth.session_id or ref.kind in {
                "role_context",
                "scenario_state",
                "job_context",
            }:
                return False
            try:
                return view.reference_allowed(ref)
            except C.ProtocolError:
                return False

        observed = []
        versions = {}
        seen = set()
        for receipt in history.material_reads:
            event = receipt.event
            if (
                event.session_id != auth.session_id
                or event.type != "material_read"
                or not 0 < event.seq <= at.business_seq
            ):
                raise C.ProtocolError("material_receipt_invalid", status=503)
            for fragment in receipt.fragments:
                ref = fragment.ref
                if (
                    ref.kind != "material"
                    or ref.object_id != event.data.get("material_id")
                    or ref.version != event.data.get("version")
                    or ref.observed_at_seq > event.seq
                    or (ref.quote is not None and fragment.text != ref.quote)
                ):
                    raise C.ProtocolError("material_receipt_invalid", status=503)
                if not permitted(ref):
                    continue
                key = (C.canonical(ref), event.id)
                if key in seen:
                    continue
                seen.add(key)
                # Keep the authorized words and exact reference, discard internal
                # fact identifiers. Receipt of text never proves understanding.
                observed.append(
                    C.ObservedFragment(
                        ref=ref,
                        text=fragment.text,
                        channel=fragment.channel,
                        verification=fragment.verification,
                        audience="learner",
                        acquired_via="material_read",
                        acquired_at_seq=event.seq,
                    )
                )
                bare = C.ObjectRef.model_validate(
                    ref.model_dump(include=set(C.ObjectRef.model_fields))
                )
                versions[C.canonical(bare)] = bare

        objects = {C.canonical(row.ref): row for row in view.objects}
        for row in view.objects:
            if row.ref.kind != "role_display":
                continue
            display = RoleDisplay.model_validate(row.content)
            reply_row = objects.get(C.canonical(display.reply))
            if reply_row is None or not permitted(display.reply):
                continue
            reply = RoleReply.model_validate(reply_row.content)
            if not no_later(reply.as_of, display.as_of) or not no_later(display.as_of, at):
                raise C.ProtocolError("role_display_window_invalid", status=503)
            ref = C.EvidenceRefV2(
                **display.reply.model_dump(mode="json"),
                observed_at_seq=display.as_of.business_seq,
                quote=reply.text,
                span_start=0,
                span_end=len(reply.text),
            )
            observed.append(
                C.ObservedFragment(
                    ref=ref,
                    text=reply.text,
                    channel="dialogue",
                    verification="verified",
                    audience="learner",
                    acquired_via="displayed",
                    acquired_at_seq=display.as_of.business_seq,
                )
            )
            versions[C.canonical(display.reply)] = display.reply

        events = tuple(
            event for event in history.events if all(permitted(ref) for ref in event.refs)
        )
        return PublicSources(
            as_of=at,
            catalog=self.catalog(view, auth),
            visible_sources=tuple(observed),
            actual_disclosures=(),
            read_versions=tuple(versions.values()),
            events=events,
            next_seq=history.next_seq,
        )
