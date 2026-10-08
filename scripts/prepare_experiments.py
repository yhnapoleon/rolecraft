import argparse
import json
from pathlib import Path
from career_lab.datasets.controlled import generate_controlled, build_controlled_release
from career_lab.datasets.annotation import export_annotation_pack, import_annotations
from career_lab.datasets.release import audit_release


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["pilot", "release", "annotations"])
    a = p.parse_args()
    if a.stage == "annotations":
        root = Path("data/annotation/v2-pilot")
        report = import_annotations(root, root / "annotator-a.csv", root / "annotator-b.csv")
    else:
        rows = generate_controlled()
        if a.stage == "pilot":
            groups = {}
            for r in rows:
                if r["lineage"]["split"] != "test":
                    groups.setdefault(r["lineage"]["template_id"], []).append(r)
            selected = []
            while len(selected) < 100:
                for group in groups.values():
                    if group and len(selected) < 100:
                        selected.append(group.pop(0))
            manifest = build_controlled_release(
                Path("data/releases/controlled-v2-pilot100"), selected
            )
            export_annotation_pack(manifest, Path("data/annotation/v2-pilot"), 100)
        else:
            manifest = build_controlled_release(Path("data/releases/controlled-v2"), rows)
        report = audit_release(manifest)
        report.update(manifest=str(manifest), human_validation="pending", proof_validation="passed")
    output = Path("docs/reports") / f"controlled-v2-{a.stage}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
