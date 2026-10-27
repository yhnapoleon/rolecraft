"""R4.functional_tests facts from what each run's own records show (evaluation_facts).

The frozen definition's two example categories, normal and out-of-scope requests, are read
off the scope recognizer and the run's outcome; declared categories never count."""

from types import SimpleNamespace as S

from career_lab.scenarios.v2.evaluation_facts import functional_coverage

scope = lambda label, fallback=False: S(task="scope", label=label, fallback=fallback)  # noqa: E731


def run(
    query,
    *,
    label="in",
    status="answered",
    code=None,
    cited=(("policy", 2),),
    now=None,
    at=1,
    fallback=False,
    declared=None,
):
    return S(
        query=query,
        status=status,
        error_code=code,
        citations=tuple(S(object_id=m, version=v) for m, v in cited),
        execution=S(source_versions=now or {"policy": 2, "faq": 1}),
        recognition=(scope(label, fallback),) if label else None,
        as_of=S(storage_revision=at),
        declared_category=declared,
    )


def mars(at=2, status="fallback"):
    return run(
        "What is the weather on Mars?",
        label="out",
        status=status,
        code="outside_scope_ood",
        cited=(),
        at=at,
    )


def test_both_categories_met_when_current_and_handed_over():
    assert functional_coverage([run("Hotel cap?"), mars()]) == (["normal", "out_of_scope"], True)


def test_a_normal_answer_from_an_outdated_version_does_not_meet_acceptance():
    stale = run("Hotel cap?", cited=(("policy", 1),))
    warned = run("Taxi limit?", status="answered_with_warning", cited=(("policy", 1),))
    assert functional_coverage([stale, mars()]) == (["normal", "out_of_scope"], False)
    assert functional_coverage([warned, mars()]) == (["normal", "out_of_scope"], False)
    # A run that failed (no hand-off to a person) is not an actual test, as the rule treats it;
    # it covers no category.
    assert functional_coverage([run("Hotel cap?"), mars(status="failed")]) == (["normal"], True)


def test_one_category_only():
    assert functional_coverage([run("Hotel cap?"), run("Leave days?", cited=(("faq", 1),))]) == (
        ["normal"],
        True,
    )


def test_no_record_stays_unknown():
    assert functional_coverage([]) is None
    assert functional_coverage([run("Hotel cap?", label=None), mars()]) is None
    # The rule fallback is not the scope recognizer's judgement.
    assert functional_coverage([run("Hotel cap?", fallback=True)]) is None


def test_only_the_latest_run_of_a_question_counts_and_declared_categories_are_ignored():
    before = run("Hotel cap?", cited=(("policy", 1),), at=1, declared="out_of_scope")
    after = run("Hotel  cap?", at=3, declared="near_boundary")
    assert functional_coverage([before, after, mars(at=2)]) == (["normal", "out_of_scope"], True)
    # A run that found nothing is placed but belongs to neither category.
    nothing = run("Printer?", status="fallback", code="no_retrieval_hit", cited=(), at=4)
    assert functional_coverage([after, nothing]) == (["normal"], True)
