"""Module-owned commands; top-level career-lab integration is a shared-file request."""

import argparse
import json
from pathlib import Path

from career_lab.contracts.v2.core import Executor, ObjectRef, ProtocolError, VersionPoint
from career_lab.contracts.v2.data import Lineage, Provenance

from .common import read_json
from .export import ExportUnit, FrozenSnapshot, SourceObject, export_snapshot
from .labeling import AnnotationBatch
from .live_cli import authorize, connection_arguments, export_live, register_authorization
from .quality import QualityError
from .release import audit_release, load_export, publish_exports, publish_release, save_export


def register_commands(commands):
    """Accept the existing argparse subparser collection; do not replace its CLI."""
    export = commands.add_parser(
        "export", help="Export an authorized live session or an explicit fixture snapshot"
    )
    export.set_defaults(w07_handler=dispatch)
    source = export.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--live", action="store_true")
    export.add_argument("--units", type=Path)
    export.add_argument("--authorization", type=Path)
    connection_arguments(export)
    register_authorization(commands).set_defaults(w07_handler=dispatch)
    export.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-data")
    validate.set_defaults(w07_handler=dispatch)
    validation_source = validate.add_mutually_exclusive_group(required=True)
    validation_source.add_argument("--release", type=Path)
    validation_source.add_argument("--export", type=Path, action="append")
    label = commands.add_parser("label")
    label.set_defaults(w07_handler=dispatch)
    ops = label.add_subparsers(dest="operation", required=True)
    prepare = ops.add_parser("prepare")
    prepare.add_argument("--export", type=Path, required=True)
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--policies", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--annotation-version", required=True)
    prepare.add_argument("--executor-id", required=True)
    issue = ops.add_parser(
        "issue", help="Issue one offline request; uncertain requests are not silently reissued"
    )
    issue.add_argument("--batch", type=Path, required=True)
    issue.add_argument("--record-id", required=True)
    issue.add_argument("--phase", type=int, choices=(1, 2, 3), required=True)
    issue.add_argument("--retry-failed", action="store_true")
    receive = ops.add_parser("receive")
    receive.add_argument("--batch", type=Path, required=True)
    receive.add_argument("--receipt", type=Path, required=True)
    status = ops.add_parser("status")
    status.add_argument("--batch", type=Path, required=True)
    publish = commands.add_parser("publish")
    publish.set_defaults(w07_handler=dispatch)
    source_group = publish.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--export", type=Path)
    source_group.add_argument(
        "--sources",
        type=Path,
        help="JSON list of export/source_root/policies/batch paths, one per source",
    )
    publish.add_argument("--batch", type=Path)
    publish.add_argument("--source-root", type=Path)
    publish.add_argument("--policies", type=Path)
    publish.add_argument("--output", type=Path, required=True)
    publish.add_argument("--fixture", action="store_true")
    publish.add_argument("--allow-pending", action="store_true")


def dispatch(args):
    if args.command == "authorize":
        return authorize(args)
    if args.command == "export":
        if args.live:
            return export_live(args)
        if args.units is None:
            raise ProtocolError("offline_units_required")
        raw = read_json(args.snapshot)
        # Offline supplied snapshots cannot attest live runtime provenance.
        if raw["origin"] != "fixture":
            raise ProtocolError("live_snapshot_adapter_required")
        objects = tuple(
            SourceObject(
                ObjectRef.model_validate(x["ref"]),
                x["text"],
                VersionPoint.model_validate(x["available_at"]),
                tuple(x["readers"]),
                x.get("usage", "visible"),
                x.get("validity_known", False),
                x.get("valid_from_seq", 0),
                x.get("valid_until_seq"),
            )
            for x in raw["objects"]
        )
        snapshot = FrozenSnapshot(
            raw["session_id"],
            raw["actor_id"],
            VersionPoint.model_validate(raw["point"]),
            objects,
            raw["source_digest"],
            raw["origin"],
        )
        units = [
            ExportUnit(
                x["family"],
                x["model_input"],
                Lineage.model_validate(x["lineage"]),
                Provenance.model_validate(x["provenance"]),
                x.get("split", "train"),
                x.get("language", "zh"),
                x.get("label_tier", "G2"),
                x.get("evaluation_time_known", False),
            )
            for x in read_json(args.units)
        ]
        result = export_snapshot(snapshot, units)
        save_export(args.output, result)
        return {
            "records": len(result.records),
            "quarantined": list(result.quarantined),
            "origin": result.origin,
        }
    if args.command == "validate-data":
        if args.export:
            from .export_audit import audit_exports

            return audit_exports(args.export)
        return audit_release(args.release)
    if args.command == "label":
        if args.operation == "prepare":
            result = load_export(args.export)
            batch = AnnotationBatch.create(
                args.output,
                result.records,
                annotation_version=args.annotation_version,
                executor=Executor(id=args.executor_id, kind="external_agent"),
                source_root=args.source_root,
                policies=read_json(args.policies),
            )
            return batch.manifest
        batch = AnnotationBatch(args.batch)
        if args.operation == "issue":
            return batch.claim(args.record_id, args.phase, retry_failed=args.retry_failed)
        if args.operation == "receive":
            return batch.receive(read_json(args.receipt))
        return {
            "usage": batch.usage(),
            "annotations": [batch.annotation(r).model_dump(mode="json") for r in batch.records],
        }
    if args.command == "publish":
        if args.sources:
            contributions = []
            for entry in read_json(args.sources):
                base = args.sources.resolve().parent
                exported = load_export(base / entry["export"])
                batch = AnnotationBatch(base / entry["batch"]) if entry.get("batch") else None
                c = {
                    "export": exported,
                    "source_root": base / entry["source_root"],
                    "policies": read_json(base / entry["policies"]),
                }
                if batch:
                    c.update(
                        annotations=[batch.annotation(r) for r in batch.records],
                        annotation_artifacts=batch.artifacts(),
                    )
                contributions.append(c)
            return publish_exports(
                args.output, contributions, fixture=args.fixture, allow_pending=args.allow_pending
            )
        if args.source_root is None or args.policies is None:
            raise ProtocolError("single_export_source_context_required")
        result = load_export(args.export)
        batch = AnnotationBatch(args.batch) if args.batch else None
        return publish_release(
            args.output,
            result,
            source_root=args.source_root,
            policies=read_json(args.policies),
            annotations=[batch.annotation(r) for r in batch.records] if batch else None,
            annotation_artifacts=batch.artifacts() if batch else None,
            fixture=args.fixture,
            allow_pending=args.allow_pending,
        )
    raise ProtocolError("unknown_command")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dataset export and annotation tools")
    register_commands(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except QualityError as exc:
        print(
            json.dumps(
                {"error": exc.code, "report": exc.report}, ensure_ascii=False, allow_nan=False
            )
        )
        return 2
    except (ValueError, KeyError, TypeError, OSError) as exc:
        message = (
            str(exc)
            if isinstance(exc, ProtocolError)
            else "invalid input or unavailable file; inspect the authorized local source"
        )
        print(
            json.dumps(
                {"error": getattr(exc, "code", type(exc).__name__), "message": message},
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0
