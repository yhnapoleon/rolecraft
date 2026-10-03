"""Create two versioned experience variants; same causal template, not new data groups."""
import hashlib
import json
from pathlib import Path

import yaml

from career_lab.scenarios.loader import load_scenario

source = Path("scenarios/pm_pilot/v1")
for name, field, value, before, after in (("urgent", "deadline_day", 5, "第7", "第5"), ("capacity15", "capacity", 15, "30", "15")):
    target = Path("scenarios") / f"pm_pilot_{name}" / "v1"
    if target.exists():
        load_scenario(target / "scenario.yaml")
        continue
    (target / "materials").mkdir(parents=True)
    for path in (source / "materials").glob("*.md"):
        (target / "materials" / path.name).write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8", newline="\n")
    data = yaml.safe_load((source / "scenario.yaml").read_text(encoding="utf-8").replace(before, after))
    data["id"] = f"pm_pilot_{name}"
    data["title"] += f"（{name}变体）"
    data["constraints"][field] = value
    next(f for f in data["facts"] if f["id"] == field)["value"] = value
    (target / "scenario.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    (target / "rubric.yaml").write_text((source / "rubric.yaml").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    files = sorted([target / "scenario.yaml", target / "rubric.yaml", *target.glob("materials/*.md")])
    manifest = {"scenario_id": data["id"], "version": 1, "files": {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    load_scenario(target / "scenario.yaml")
    print(data["id"])
