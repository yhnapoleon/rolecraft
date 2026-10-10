"""Read-time freshness and later recorded actions for immutable outcome previews.

A read compares the key conditions recorded with a preview against the caller's current
authorized view. Nothing is evaluated again: no model call, no new preview and no change to the
stored record. Business actions recorded after the preview are listed beside it with their own
identities and points, so a prediction never becomes "what was executed".
"""

from collections import Counter

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.evaluation import _PreviewActual as PreviewActual
from career_lab.contracts.v2.evaluation import _PreviewChange as PreviewChange
from career_lab.contracts.v2.evaluation import _PreviewConditions as PreviewConditions
from career_lab.contracts.v2.evaluation import _PreviewState as PreviewState
from career_lab.storage.v2_store import TransactionView

CONFIG_IDENTITY = frozenset({"id", "session_id", "version", "config_version"})
# Repeated tools also report how many separate records were made after the preview.
COUNTED = frozenset({"tests.create", "work_products.shares.create"})


def current_conditions(view: TransactionView) -> PreviewConditions:
    """The key business conditions a preview formed now would depend on."""
    scenario = view.private_scenario_state
    return PreviewConditions(
        config_version=view.state.config_version,
        resources=dict(view.state.resources),
        source_versions=dict(scenario.source_versions) if scenario is not None else None,
    )


def preview_state(view: TransactionView, record: C.StoredObject) -> PreviewState:
    preview = C.FeedbackV2.model_validate(record.content)
    inputs = tuple(
        ref for ref in (preview.input_refs or (preview.subject,)) if ref.kind == "product"
    )
    # Records without recorded conditions predate this check; treat them as business previews.
    business = preview.preview_conditions is None or any(
        value is not None for value in preview.preview_conditions.model_dump().values()
    )
    changes = input_changes(view, inputs)
    if business:
        changes += condition_changes(view, preview, record)
    return PreviewState(
        feedback=record.ref,
        status="stale" if changes else "current",
        changes=changes,
        superseded_by=superseding_preview(view, inputs),
        actual=later_actions(view, record, inputs, business),
        checked_at=C.VersionPoint(
            **view.state.model_dump(
                include={"business_seq", "workspace_revision", "storage_revision"}
            )
        ),
    )


def input_changes(view: TransactionView, inputs: tuple[C.ObjectRef, ...]) -> tuple:
    changes = []
    for ref in inputs:
        head = max(
            (
                row.ref
                for row in view.objects
                if row.ref.kind == "product" and row.ref.object_id == ref.object_id
            ),
            key=lambda found: found.version,
            default=ref,
        )
        if head.version > ref.version:
            changes.append(
                PreviewChange(condition="input", before=ref.version, after=head.version, ref=head)
            )
    return tuple(changes)


def condition_changes(
    view: TransactionView, preview: C.FeedbackV2, record: C.StoredObject
) -> tuple:
    recorded = preview.preview_conditions
    changes = []
    before = (
        recorded.config_version
        if recorded is not None
        else configuration_at(view, record.created_storage_revision)
    )
    if before is not None and before != view.state.config_version:
        changes.append(
            PreviewChange(
                condition="configuration",
                before=before,
                after=view.state.config_version,
                ref=current_configuration(view),
            )
        )
    if recorded is not None and recorded.resources is not None:
        now = dict(view.state.resources)
        keys = sorted(
            k for k in {*now, *recorded.resources} if now.get(k) != recorded.resources.get(k)
        )
        if keys:
            decisions = [
                row
                for row in view.objects
                if row.ref.kind == "business_decision"
                and row.created_storage_revision > record.created_storage_revision
            ]
            changes.append(
                PreviewChange(
                    condition="resources",
                    before={k: recorded.resources.get(k) for k in keys},
                    after={k: now.get(k) for k in keys},
                    ref=max(decisions, key=lambda row: row.created_storage_revision).ref
                    if decisions
                    else None,
                )
            )
    scenario = view.private_scenario_state
    if recorded is not None and recorded.source_versions is not None and scenario is not None:
        now = dict(scenario.source_versions)
        old = recorded.source_versions
        keys = sorted(k for k in {*now, *old} if now.get(k) != old.get(k))
        if keys:
            changes.append(
                PreviewChange(
                    condition="materials",
                    before={k: old.get(k) for k in keys},
                    after={k: now.get(k) for k in keys},
                )
            )
    return tuple(changes)


def configuration_at(view: TransactionView, revision: int) -> int | None:
    versions = [
        row.ref.config_version
        for row in view.objects
        if row.ref.kind == "config"
        and row.created_storage_revision <= revision
        and row.ref.config_version is not None
    ]
    return max(versions, default=None)


def current_configuration(view: TransactionView) -> C.ObjectRef | None:
    rows = [
        row.ref
        for row in view.objects
        if row.ref.kind == "config" and row.ref.config_version == view.state.config_version
    ]
    return max(rows, key=lambda ref: ref.version, default=None)


def superseding_preview(
    view: TransactionView, inputs: tuple[C.ObjectRef, ...]
) -> C.ObjectRef | None:
    newer = [
        row
        for row in view.objects
        if row.ref.kind == "feedback"
        and row.content.get("preview_kind") is not None
        and row.content["subject"]["kind"] == "product"
        and any(
            row.content["subject"]["object_id"] == ref.object_id
            and row.content["subject"]["version"] > ref.version
            for ref in inputs
        )
    ]
    return max(newer, key=lambda row: row.created_storage_revision).ref if newer else None


def later_actions(
    view: TransactionView,
    record: C.StoredObject,
    inputs: tuple[C.ObjectRef, ...],
    business: bool,
) -> tuple[PreviewActual, ...]:
    """Latest recorded action per business tool after the preview, in recorded order."""
    after = record.created_storage_revision
    products = {ref.object_id for ref in inputs}
    decisions = {
        row.content["request"]["object_id"]: row.content
        for row in view.objects
        if row.ref.kind == "business_decision"
    }
    latest: dict[str, tuple[int, PreviewActual]] = {}
    counts: Counter[str] = Counter()
    for row in sorted(view.objects, key=lambda row: row.created_storage_revision):
        if row.created_storage_revision <= after:
            continue
        actual = recorded_action(view, row, after, products, business, decisions)
        if actual is None:
            continue
        counts[actual.operation] += row.ref.version == 1
        latest[actual.operation] = (row.created_storage_revision, actual)
    return tuple(
        actual.model_copy(update={"values": {**actual.values, "count": counts[operation]}})
        if operation in COUNTED
        else actual
        for operation, (_, actual) in sorted(latest.items(), key=lambda item: item[1][0])
    )


def recorded_action(
    view: TransactionView,
    row: C.StoredObject,
    after: int,
    products: set[str],
    business: bool,
    decisions: dict[str, dict],
) -> PreviewActual | None:
    kind, content = row.ref.kind, row.content
    if kind == "share" and content["product"]["object_id"] in products:
        return PreviewActual(
            operation="work_products.shares.create",
            ref=row.ref,
            status="revoked" if content.get("revoked_at") else "shared",
            at=content["shared_at"],
            values={
                "recipient_role": content["recipient_role"],
                "version": content["product"]["version"],
            },
        )
    if kind == "submission":
        versions = [ref["version"] for ref in content["products"] if ref["object_id"] in products]
        if not versions:
            return None
        return PreviewActual(
            operation="submissions.create",
            ref=row.ref,
            status="submitted",
            at=content["as_of"],
            values={
                "decision": content["decision"],
                "version": max(versions),
                "config_version": (content.get("config") or {}).get("config_version"),
            },
        )
    if not business:
        return None
    if kind == "config":
        return PreviewActual(
            operation="configuration.apply",
            ref=row.ref,
            status="applied",
            values={
                "config_version": row.ref.config_version,
                "changed": changed_settings(view, after, content),
            },
        )
    if kind == "business_request":
        decision = decisions.get(row.ref.object_id)
        return PreviewActual(
            operation="actions",
            ref=row.ref,
            status=content["status"],
            at=decision["as_of"] if decision else content["as_of"],
            values={
                "requested": content["requested"],
                **({"granted": decision["granted"]} if decision else {}),
            },
        )
    if kind == "test":
        return PreviewActual(
            operation="tests.create",
            ref=row.ref,
            status=content["status"],
            at=content["as_of"],
            values={"config_version": content["config_ref"].get("config_version")},
        )
    return None


def changed_settings(view: TransactionView, revision: int, applied: dict) -> dict:
    earlier = [
        row
        for row in view.objects
        if row.ref.kind == "config" and row.created_storage_revision <= revision
    ]
    if not earlier:
        return {}
    base = max(earlier, key=lambda row: row.created_storage_revision).content
    return {
        key: value
        for key, value in applied.items()
        if key not in CONFIG_IDENTITY and base.get(key) != value
    }
