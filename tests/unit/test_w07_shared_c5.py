"""Fixed semantic cases against c5 and the versioned origin binding shape."""
import itertools
from test_w07_pipeline import make_case
from career_lab.contracts.v2.data import AnnotationDecision,semantic_decision_key
from career_lab.datasets.v3.attestation import semantic_key,same_semantics,validate_decision
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.origin import binding
from career_lab.contracts.v2.core import digest


def test_c5_shared_semantic_function_matches_fixed_valid_decision_matrix(tmp_path):
    snap,units,_=make_case(tmp_path);row=export_snapshot(snap,units[:1]).records[0];payload=row.model_input.model_dump(mode='json')
    cases=[]
    for label,app,evaluable,targets,representative,reason in itertools.product(['SUPPORTED','CONTRADICTED'],['applicable','undetermined'],[True,False],[(('e1',),),(('e1',),('e2',))],['e1','e2'],['first explanation','second explanation']):
        if (representative,) not in targets:continue
        raw=AnnotationDecision(task_type='relation',label=label,applicability=app,evidence_evaluable=evaluable,evidence_ids=(representative,),acceptable_evidence_sets=targets,missing_reason=reason)
        parsed=validate_decision(raw.model_dump_json(),payload);cases.append(parsed)
    def fixed(d):return (d.task_type,d.label,d.applicability,d.evidence_evaluable,frozenset(frozenset(g) for g in d.acceptable_evidence_sets))
    for left,right in itertools.product(cases,repeat=2):
        assert semantic_key(left)==semantic_decision_key(left)
        assert same_semantics(left,right)==(fixed(left)==fixed(right))
    assert len(cases)==48


def test_origin_binding_retains_exact_v1_keys_and_metadata_only_values(tmp_path):
    snap,units,_=make_case(tmp_path);result=export_snapshot(snap,units[:1]);row=result.records[0];source=result.source_snapshots[0]
    assert binding(row,source)=={'protocol':'w07-source-origin-v1','record_id':row.record_id,'origin':'fixture','session_id':row.lineage.session_id,
        'lineage_hash':digest(row.lineage),'snapshot_digest':source['snapshot_digest'],'source_digest':row.provenance.source.source_digest,
        'source_files':[r.model_dump(mode='json') for r in row.provenance.actual_sources]}
