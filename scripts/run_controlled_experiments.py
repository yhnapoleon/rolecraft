import argparse
import json
from pathlib import Path
from career_lab.experiments.study import run_development, freeze_study, run_confirmatory


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["dev", "freeze", "test"])
    p.add_argument("--output", type=Path, default=Path("runs/controlled-v2"))
    p.add_argument(
        "--manifest", type=Path, default=Path("data/releases/controlled-v2/manifest.json")
    )
    p.add_argument("--models", type=Path, default=Path("runs/models/controlled-v2"))
    a = p.parse_args()
    if a.stage == "dev":
        result = run_development(a.manifest, a.models, a.output)
    elif a.stage == "freeze":
        result = freeze_study(a.manifest, a.models, a.output)
    else:
        result = run_confirmatory(a.output)
    target = Path("docs/reports") / f"controlled-v2-{a.stage}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {name: r["metrics"]["macro_f1"] for name, r in result.get("e1", {}).items()}
            or {"freeze_id": result["id"]}
        )
    )


if __name__ == "__main__":
    main()
