import argparse
import json
from pathlib import Path
from career_lab.contracts.v2.core import FileRef,ProtocolError,read_file
from career_lab.models.v3.bundle import load_bundle
from career_lab.models.v3.core import INPUT
from .data import ReleaseReader
from .pipeline import run_development
from .freeze import verify_freeze


def register_commands(commands):
    train=commands.add_parser("train-v3",help="Local W08 train/dev pipeline; no held-out evaluation")
    train.add_argument("--release-root",type=Path,required=True);train.add_argument("--release-hash",required=True)
    train.add_argument("--split-hash",required=True);train.add_argument("--output",type=Path,required=True)
    train.add_argument("--workspace",type=Path,required=True);train.add_argument("--fixture",action="store_true")
    train.add_argument("--task",choices=["relation","criterion"],default="relation")
    train.add_argument("--epochs",type=int,default=4);train.add_argument("--dimension",type=int,default=8)
    train.add_argument("--seed",type=int,default=5002);train.add_argument("--max-tokens",type=int,default=128)
    train.set_defaults(w08_handler=dispatch)
    check=commands.add_parser("check-freeze-v3");check.add_argument("--root",type=Path,required=True)
    check.add_argument("--freeze-hash",required=True);check.set_defaults(w08_handler=dispatch)
    infer=commands.add_parser("predict-v3");infer.add_argument("--root",type=Path,required=True)
    infer.add_argument("--bundle-hash",required=True);infer.add_argument("--input",type=Path,required=True);infer.set_defaults(w08_handler=dispatch)


def dispatch(args):
    if args.command=="train-v3":
        reader=ReleaseReader(args.release_root,FileRef(path="manifest.json",sha256=args.release_hash),FileRef(path="split-manifest.json",sha256=args.split_hash),allow_fixture=args.fixture)
        return run_development(reader,args.output,workspace=args.workspace,task=args.task,epochs=args.epochs,dimension=args.dimension,seed=args.seed,max_tokens=args.max_tokens)
    if args.command=="check-freeze-v3":
        frozen=verify_freeze(args.root,FileRef(path="freeze.json",sha256=args.freeze_hash))
        return {"freeze_id":frozen["id"],"valid":True,"test_content_opened":False}
    model,bundle=load_bundle(args.root,FileRef(path="model-bundle.json",sha256=args.bundle_hash))
    item=INPUT.validate_json(args.input.read_bytes())
    release=json.loads(read_file(args.root,bundle.training_release))
    return model.predict(item).as_dict() | {"training_release":bundle.training_release.model_dump(mode="json"),
        "training_scope":"synthetic_pipeline" if release.get("fixture") else "development_unconfirmed"}


def main(argv=None):
    parser=argparse.ArgumentParser(description="W08 draft-contract development tools; all outputs advisory")
    register_commands(parser.add_subparsers(dest="command",required=True));args=parser.parse_args(argv)
    try:result=dispatch(args)
    except (ValueError,KeyError,OSError) as exc:
        print(json.dumps({"error":getattr(exc,"code",type(exc).__name__),"record_id":getattr(exc,"record_id",None),"details":getattr(exc,"report",None),"message":str(exc) if isinstance(exc,ProtocolError) else "invalid input or unavailable resource"},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
