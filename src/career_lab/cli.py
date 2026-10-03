import argparse
import json
from pathlib import Path

from career_lab.scenarios.loader import ScenarioLoadError, load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="career-lab", description="ISY5002 career training backend tools")
    commands = parser.add_subparsers(dest="command", required=True)
    scenario = commands.add_parser("scenario", help="Scenario authoring tools")
    operations = scenario.add_subparsers(dest="operation", required=True)
    validate = operations.add_parser("validate", help="Validate frozen scenario, references and content hashes")
    validate.add_argument("path", type=Path, help="Path to scenario.yaml")
    data = commands.add_parser("data", help="Dataset build and audit")
    data_ops = data.add_subparsers(dest="operation", required=True)
    build = data_ops.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    audit = data_ops.add_parser("audit")
    audit.add_argument("--manifest", type=Path, required=True)
    evaluation = commands.add_parser("eval", help="Independent evaluation")
    eval_ops = evaluation.add_subparsers(dest="operation", required=True)
    run = eval_ops.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    train = commands.add_parser("train-baselines", help="Fit CPU supervised models using train/dev only")
    train.add_argument("--manifest", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    demo = commands.add_parser("demo", help="Run full backend workflow without a frontend")
    demo.add_argument("--database-url", default="sqlite:///career_lab.db")
    demo.add_argument("--scenario", type=Path, default=Path("scenarios/pm_pilot/v1/scenario.yaml"))
    demo.add_argument("--output", type=Path)
    package = commands.add_parser("package", help="Build a source release excluding credentials")
    package.add_argument("--output", type=Path, required=True)
    for command in ("serve", "worker"):
        server = commands.add_parser(command)
        server.add_argument("--database-url", default=None)
        server.add_argument("--provider", choices=["local", "deepseek", "openai"], default="local")
        if command == "serve":
            server.add_argument("--host", default="127.0.0.1")
            server.add_argument("--port", type=int, default=8000)
        else:
            server.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "demo":
        from career_lab.demo import run_demo
        result = run_demo(args.database_url, args.scenario)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"session_id": result["session_id"], "status": result["state_status"], "replay_stable": result["replay_stable"]}))
        return 0
    if args.command == "package":
        from career_lab.packaging import package_release
        print(package_release(Path.cwd(), args.output))
        return 0
    if args.command in {"serve", "worker"}:
        import os
        import time
        from career_lab.api.app import create_app
        from career_lab.runtime.model_adapter import LocalModel, OpenAICompatibleModel
        from career_lab.jobs.worker import Worker
        model = LocalModel()
        if args.provider != "local":
            defaults = {"deepseek": ("ds.txt", "https://api.deepseek.com", "deepseek-chat"), "openai": ("openai.txt", "https://api.openai.com/v1", "gpt-4.1-mini")}
            key_file, url, name = defaults[args.provider]
            model = OpenAICompatibleModel.from_key_file(Path(os.getenv("CAREER_LAB_KEY_FILE", key_file)), base_url=os.getenv("CAREER_LAB_BASE_URL", url), model=os.getenv("CAREER_LAB_MODEL", name))
        app = create_app(args.database_url, model=model)
        if args.command == "serve":
            import uvicorn
            uvicorn.run(app, host=args.host, port=args.port)
        else:
            worker = Worker(app.state.jobs, app.state.handlers)
            while True:
                worked = worker.run_once()
                if args.once:
                    break
                if not worked:
                    time.sleep(1)
        return 0
    if args.command == "train-baselines":
        from career_lab.models.training import train_baselines
        print(json.dumps(train_baselines(args.manifest, args.output), indent=2))
        return 0
    if args.command == "data":
        from career_lab.datasets.release import build_release, audit_release
        result = {"manifest": str(build_release(args.output))} if args.operation == "build" else audit_release(args.manifest)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "eval":
        import yaml
        from career_lab.evals.runner import RunnerConfig, run_eval
        config = RunnerConfig.model_validate(yaml.safe_load(args.config.read_text(encoding="utf-8")))
        print(run_eval(config).model_dump_json(indent=2))
        return 0
    try:
        spec = load_scenario(args.path)
    except ScenarioLoadError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps({"valid": True, "scenario_id": spec.id, "version": spec.version,
                      "content_hash": spec.content_hash, "roles": len(spec.roles),
                      "materials": len(spec.materials), "criteria": len(spec.rubric.criteria)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

