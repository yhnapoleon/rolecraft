from career_lab.rubrics.aggregate import aggregate_items
from career_lab.rubrics.checks import CriterionResult


def two_item_rubric(spec):
    dimension = next(d for d in spec.rubric.dimensions if d.id == "R3").model_copy(update={"weight": 100})
    return spec.rubric.model_copy(update={"dimensions": (dimension,), "criteria": tuple(c for c in spec.rubric.criteria if c.dimension == "R3")})


def test_bounds_and_coverage(spec):
    report = aggregate_items([CriterionResult(criterion_id="R3.capacity", label="MET"), CriterionResult(criterion_id="R3.resources", label="INSUFFICIENT")], two_item_rubric(spec))
    assert report["lower"] == .5
    assert report["upper"] == 1.0
    assert report["coverage"] == .5
    assert report["status"] == "pending_review"


def test_all_not_applicable_unscorable(spec):
    report = aggregate_items([CriterionResult(criterion_id=c.id, label="NOT_APPLICABLE") for c in spec.rubric.criteria], spec.rubric)
    assert report["status"] == "unscorable"
    assert report["lower"] is None


def test_provisional_partial_retains_possible_full_credit(spec):
    rubric = two_item_rubric(spec)
    report = aggregate_items([CriterionResult(criterion_id="R3.capacity", label="PARTIAL", review_required=True), CriterionResult(criterion_id="R3.resources", label="NOT_APPLICABLE")], rubric)
    assert report["lower"] == .5
    assert report["upper"] == 1
    assert report["coverage"] == 0
