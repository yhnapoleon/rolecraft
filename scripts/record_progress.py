"""Record a verified task result in both plan and append-only execution log."""

import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("task", type=int)
p.add_argument("status")
p.add_argument("evidence")
p.add_argument("--date", default="2026-10-03")
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
plan = root / "docs/plans/career-training-implementation-plan.md"
text = plan.read_text(encoding="utf-8")
lines = text.splitlines()
for i, line in enumerate(lines):
    if line.startswith(f"### Task {a.task} "):
        lines.insert(i + 1, f"\n**{a.date} 实施状态：{a.status}。** {a.evidence}\n")
        break
plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
with (root / "docs/reports/implementation-progress.md").open("a", encoding="utf-8") as f:
    f.write(f"\n## Task {a.task}：{a.status}\n\n{a.evidence}\n")
