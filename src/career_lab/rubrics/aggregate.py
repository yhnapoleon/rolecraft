from career_lab.rubrics.checks import CriterionResult


def aggregate_items(items, rubric):
    mapping = {i.criterion_id: i for i in items}
    if len(mapping) != len(items) or mapping.keys() - {c.id for c in rubric.criteria}:
        raise ValueError("duplicate or unknown criteria")
    scores = {"MET": 2, "PARTIAL": 1, "NOT_MET": 0}
    dimensions = []
    for dimension in rubric.dimensions:
        entries = [
            mapping.get(
                c.id, CriterionResult(criterion_id=c.id, label="INSUFFICIENT", review_required=True)
            )
            for c in rubric.criteria
            if c.dimension == dimension.id
        ]
        applicable = [i for i in entries if i.label != "NOT_APPLICABLE"]
        if not applicable:
            continue
        n = len(applicable)
        unknown = sum(i.label == "INSUFFICIENT" or i.review_required for i in applicable)
        total = sum(scores.get(i.label, 0) for i in applicable)
        possible = sum(
            2 if i.label == "INSUFFICIENT" or i.review_required else scores[i.label]
            for i in applicable
        )
        dimensions.append(
            {
                "id": dimension.id,
                "weight": dimension.weight,
                "lower": total / (2 * n),
                "upper": possible / (2 * n),
                "coverage": (n - unknown) / n,
            }
        )
    if not dimensions:
        return {
            "status": "unscorable",
            "lower": None,
            "upper": None,
            "coverage": 0,
            "dimensions": [],
        }
    weight = sum(d["weight"] for d in dimensions)
    report = {
        key: sum(d[key] * d["weight"] for d in dimensions) / weight
        for key in ("lower", "upper", "coverage")
    }
    report["status"] = (
        "pending_review"
        if report["coverage"] < 1 or any(i.review_required for i in items)
        else "scored"
    )
    return report | {"dimensions": dimensions}
