from career_lab.datasets.scenario_matrix import TEMPLATES, evaluate


def test_matrix_is_structural_and_each_family_has_all_splits():
    assert len(TEMPLATES) == 24
    assert len({t.id for t in TEMPLATES}) == 24
    families = {t.family for t in TEMPLATES}
    assert len(families) == 6
    for family in families:
        subset = [t for t in TEMPLATES if t.family == family]
        assert [t.split for t in subset] == ["train", "train", "dev", "test"]
        assert len({str(t.expression) for t in subset}) == 4


def test_three_valued_logic_and_boundary():
    expr = ("le", "participants", "capacity")
    assert evaluate(expr, {"participants": 30, "capacity": 30}) is True
    assert evaluate(expr, {"participants": 31, "capacity": 30}) is False
    assert evaluate(expr, {"participants": 30}) is None
    assert (
        evaluate(("and", expr, ("eq", "approved", 1)), {"participants": 31, "capacity": 30})
        is False
    )
    assert evaluate(("or", expr, ("eq", "approved", 1)), {"approved": 1}) is True
