"""Local registration/recovery/review tools. No training or network/provider calls."""

import argparse
import json
from pathlib import Path

from career_lab.contracts.v2.core import FileRef, ProtocolError

from .advisory import RegisteredAdvisory
from .core import INPUT
from .registry import register_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--registry", type=Path, required=True)
    register.add_argument("--bundle-root", type=Path, required=True)
    register.add_argument("--bundle-hash", required=True)
    register.add_argument("--bundle-path", default="model-bundle.json")
    register.add_argument(
        "--scope", choices=["synthetic_fixture", "external_candidate"], required=True
    )
    for name in ("predict", "recover", "review"):
        command = commands.add_parser(name)
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--registration-path", required=True)
        command.add_argument("--registration-hash", required=True)
        if name in ("predict", "recover"):
            command.add_argument("--journal", type=Path, required=True)
            command.add_argument("--request-id", required=True)
        if name == "predict":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--language", choices=["zh", "en"], required=True)
            command.add_argument("--allow-synthetic", action="store_true")
            command.add_argument("--retry-of")
        if name == "review":
            command.add_argument("--release-root", type=Path, required=True)
            command.add_argument("--release-hash", required=True)
            command.add_argument("--split-hash", required=True)
            command.add_argument("--partition", choices=["train", "dev"], default="dev")
            command.add_argument("--task", choices=["relation", "criterion"], required=True)
            command.add_argument("--fixture", action="store_true")
            command.add_argument("--producer-predictions", type=Path)
    verify = commands.add_parser("verify-return", help="Check a frozen label/evidence return")
    verify.add_argument("--dataset-root", type=Path, required=True)
    verify.add_argument("--dataset-hash", required=True)
    verify.add_argument("--predictions", type=Path, required=True)
    verify.add_argument("--partition", default="dev")
    verify.add_argument("--checkpoint-manifest", type=Path)
    verify.add_argument("--registry", type=Path)
    verify.add_argument("--registration-path")
    verify.add_argument("--registration-hash")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-return":
            from .return_verification import verify_return

            result = verify_return(
                args.dataset_root,
                args.dataset_hash,
                args.predictions,
                partition=args.partition,
                checkpoint_manifest=args.checkpoint_manifest,
                registry_root=args.registry,
                registration_path=args.registration_path,
                registration_hash=args.registration_hash,
            )
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 2 if result["status"] == "rejected" else 0
        if args.command == "register":
            ref = register_bundle(
                args.registry,
                args.bundle_root,
                FileRef(path=args.bundle_path, sha256=args.bundle_hash),
                scope=args.scope,
            )
            result = {
                "registration": ref.model_dump(mode="json"),
                "mode": "advisory",
                "quality_validated": False,
                "training_performed": False,
            }
        else:
            ref = FileRef(path=args.registration_path, sha256=args.registration_hash)
            if args.command in ("predict", "recover"):
                adapter = RegisteredAdvisory(
                    args.registry,
                    ref,
                    args.journal,
                    allow_synthetic=getattr(args, "allow_synthetic", False),
                )
                if args.command == "recover":
                    result = adapter.recover(args.request_id)
                else:
                    item = INPUT.validate_json(args.input.read_bytes())
                    result = adapter.predict(
                        item,
                        request_id=args.request_id,
                        work_language=args.language,
                        retry_of=args.retry_of,
                    )
            else:
                from career_lab.experiments.v3.training.data import ReleaseReader
                from career_lab.experiments.v3.training.review import review_registered

                reader = ReleaseReader(
                    args.release_root,
                    FileRef(path="manifest.json", sha256=args.release_hash),
                    FileRef(path="split-manifest.json", sha256=args.split_hash),
                    allow_fixture=args.fixture,
                )
                rows = reader.load(args.partition, args.task)
                producer = (
                    json.loads(args.producer_predictions.read_bytes())
                    if args.producer_predictions
                    else None
                )
                result = review_registered(args.registry, ref, rows, producer_predictions=producer)
                result["release_scope"] = reader.scope_report()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(
            json.dumps(
                {
                    "error": getattr(error, "code", type(error).__name__),
                    "record_id": getattr(error, "record_id", None),
                    "quality_validated": False,
                    "message": str(error)
                    if isinstance(error, ProtocolError)
                    else "invalid input or unavailable local artifact",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
