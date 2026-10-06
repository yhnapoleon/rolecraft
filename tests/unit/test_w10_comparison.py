"""Paired branch comparison tests; metrics are fixture values, not E7 results."""
from dataclasses import replace
import pytest
from career_lab.contracts.v2 import BranchManifest, FileRef, Lineage, ProtocolError
from career_lab.branching.comparison import EvaluatedRun, compare_runs
from test_w10_branching import F, parent_file, prepare, auth, DEFAULT_OBJECT_CODECS, EVENTS
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService


def pair(tmp_path):
    service=BranchService(BranchRepository(tmp_path/"comparison.db"),DEFAULT_OBJECT_CODECS,EVENTS)
    record=prepare(service,tmp_path)
    b=BranchManifest.model_validate(record["manifest"])
    p=EvaluatedRun(run=b.parent_run,session_id="parent",
        lineage=Lineage(structure_id="structure",component_id="component",run_id="parent-run",session_id="parent"),
        split="dev",evaluation=F,runtime=F,seed=3,metrics={"quality":0.7,"cost":10,"unknown":None},
        completed=True,model_calls=2,cost=10)
    c=EvaluatedRun(run=FileRef(path="child.json",sha256="c"*64),session_id=b.lineage.session_id,
        lineage=b.lineage,split="dev",evaluation=F,runtime=F,seed=3,
        metrics={"quality":0.6,"cost":8,"unknown":None},completed=False,model_calls=3,cost=8)
    return p,c,b


DIRECTIONS={"quality":"higher","cost":"lower","unknown":"higher"}


def test_all_improvement_regression_and_unknown_rows_preserved(tmp_path):
    p,c,b=pair(tmp_path)
    result=compare_runs(p,c,b,directions=DIRECTIONS)
    by_name={x["metric"]:x for x in result["metrics"]}
    assert by_name["quality"]["assessment"]=="regressed"
    assert by_name["cost"]["assessment"]=="improved"
    assert by_name["unknown"]["assessment"]=="unknown"
    assert result["child_completed"] is False
    assert result["grouping_unit"]=="parent_run" and result["human_learning_effect"]=="not_measured"


def test_changed_evaluation_refuses_attribution(tmp_path):
    p,c,b=pair(tmp_path)
    with pytest.raises(ProtocolError):
        compare_runs(p,replace(c,evaluation=FileRef(path="different.json",sha256="b"*64)),b,directions=DIRECTIONS)


def test_changed_seed_is_descriptive_only(tmp_path):
    p,c,b=pair(tmp_path)
    result=compare_runs(p,replace(c,seed=8),b,directions=DIRECTIONS)
    assert result["comparison"]=="descriptive_only" and "seed_differs" in result["confounds"]


@pytest.mark.parametrize("bad",["split","component","parent","child_session"])
def test_wrong_lineage_cannot_be_compared(tmp_path,bad):
    p,c,b=pair(tmp_path)
    if bad=="split":c=replace(c,split="test")
    elif bad=="component":c=replace(c,lineage=c.lineage.model_copy(update={"component_id":"different"}))
    elif bad=="parent":p=replace(p,session_id="different")
    else:c=replace(c,session_id="parent")
    with pytest.raises(ProtocolError):compare_runs(p,c,b,directions=DIRECTIONS)


def test_metric_direction_and_finite_values_are_required(tmp_path):
    p,c,b=pair(tmp_path)
    with pytest.raises(ProtocolError):compare_runs(p,c,b,directions={})
    with pytest.raises(ProtocolError):compare_runs(p,replace(c,metrics={"quality":float("nan")}),b,directions=DIRECTIONS)
