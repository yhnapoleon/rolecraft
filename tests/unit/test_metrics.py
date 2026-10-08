from career_lab.evals.metrics import summarize


def test_false_deduction_and_infrastructure_denominator():
    report = summarize(
        [
            {
                "gold_label": "MET",
                "predicted_label": "NOT_MET",
                "label_correct": False,
                "joint_correct": False,
                "error_class": None,
                "group": "a",
            },
            {
                "gold_label": "MET",
                "predicted_label": None,
                "label_correct": False,
                "joint_correct": False,
                "error_class": "infrastructure_error",
                "group": "b",
            },
        ]
    )
    assert report["accuracy"] == 0
    assert report["false_deduction"] == 0.5
    assert report["infrastructure_errors"] == 1
