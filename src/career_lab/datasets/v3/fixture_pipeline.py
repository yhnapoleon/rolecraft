"""Reproducible synthetic W07 publication for the W07→W08 boundary.

Uses the real exporter, G0 verifier, aggregation and publication audit. These
numeric fixtures prove wiring only, never human validity or research quality.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from career_lab.contracts.v2.core import ObjectRef,EvidenceRefV2,VersionPoint,SourceIdentity,Executor,FileRef,digest
from career_lab.contracts.v2.data import RelationInput,Lineage,Provenance
from career_lab.contracts.v2.evaluation import EvidencePackageV2,CandidateEvidenceV2
from .common import json_bytes,sha,write_new
from .export import SourceObject,FrozenSnapshot,ExportUnit,export_snapshot
from .g0 import verify_numeric
from .release import publish_exports,audit_release


def build_fixture_release(output,*,workspace):
    output=Path(output);workspace=Path(workspace).resolve();output.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(['git','-C',str(workspace),'rev-parse','HEAD'],text=True).strip()
    runtime={p.relative_to(workspace).as_posix():sha(p.read_bytes()) for p in sorted((workspace/'src/career_lab').rglob('*.py'))}
    identity=SourceIdentity(base_commit=commit,source_digest=digest(runtime))
    write_new(output/'runtime-identity.json',{'commit':commit,'runtime_hashes':runtime,'source_digest':identity.source_digest})
    contributions=[];expected={}
    for split,field,operator,threshold in [('train','capacity','>=',8),('dev','version','==',2)]:
        for group in range(2):
            for label,value in [('SUPPORTED',threshold),('CONTRADICTED',1),('INSUFFICIENT',None)]:
                sid=f'fixture-{split}-{group}-{label.lower()}'
                root=output/'sources'/sid;root.mkdir(parents=True)
                capture=VersionPoint(business_seq=6,workspace_revision=3,storage_revision=8)
                # Group zero evaluates an earlier, still-valid fact; group one
                # evaluates at the capture point. Both are explicit horizons.
                point=VersionPoint(business_seq=2 if group==0 else 6,workspace_revision=1,storage_revision=3)
                sources=[];candidates=[]
                for i,text in enumerate([json.dumps({field:value} if value is not None else {'status':'unknown'}),
                                          'capacity planning note' if split=='train' else 'release archive notice']):
                    ref=ObjectRef(session_id=sid,kind='document',object_id=f'document-{i}',version=1)
                    until=4 if group==0 else None
                    sources.append(SourceObject(ref,text,VersionPoint(business_seq=1,workspace_revision=0,storage_revision=1),('learner',),validity_known=True,valid_until_seq=until))
                    evidence_ref=EvidenceRefV2(**ref.model_dump(mode='json'),observed_at_seq=1,valid_until_seq=until)
                    candidates.append(CandidateEvidenceV2(id=f'candidate-{i}',text=text,ref=evidence_ref))
                body=dict(item_id=sid,task_type='relation',claim=f'{field} {operator} {threshold}',subjects=(candidates[0].ref,),
                          purpose='exploration',as_of=point,candidate_evidence=tuple(candidates),rule_context={},applicability='undetermined',completeness='complete')
                # Hash the complete schema payload including public defaults.
                blank=EvidencePackageV2.model_construct(**body,input_hash='0'*64)
                payload=blank.model_dump(mode='json',exclude={'input_hash'})
                evidence=EvidencePackageV2(**payload,input_hash=digest(payload))
                snapshot=FrozenSnapshot(sid,'learner',capture,tuple(sources),identity.source_digest,'fixture')
                write_new(root/'snapshot.json',{'fixture':True,'session_id':sid,'actor_id':'learner','point':capture.model_dump(mode='json'),
                    'origin':'fixture','source_digest':identity.source_digest,'objects':[asdict(s) | {'ref':s.ref.model_dump(mode='json'),'available_at':s.available_at.model_dump(mode='json')} for s in sources]})
                file_ref=FileRef(path='snapshot.json',sha256=sha((root/'snapshot.json').read_bytes()))
                provenance=Provenance(command='W07 fixture_pipeline: generated numeric fixtures; no business execution',source=identity,
                    executor=Executor(id='w07-fixture-generator',kind='system'),actual_sources=(file_ref,),captured_at='2026-10-07T00:00:00Z')
                lineage=Lineage(structure_id=f'fixture-{split}',component_id=sid,session_id=sid,run_id=sid,fact_root_ids=(sid,))
                unit=ExportUnit('relation',RelationInput(evidence=evidence),lineage,provenance,split=split,language='en',evaluation_time_known=True)
                result=export_snapshot(snapshot,[unit])
                if result.quarantined or len(result.records)!=1:raise ValueError(result.quarantined)
                annotations=[verify_numeric(r,evidence_evaluable=not(group==1 and label=="SUPPORTED")) for r in result.records]
                if annotations[0].final.label!=label:raise ValueError('fixture expectation mismatch')
                expected[result.records[0].record_id]={'label':label,'reference_seq':point.business_seq,'capture_seq':capture.business_seq,'split':split,'evidence_evaluable':annotations[0].final.evidence_evaluable}
                contributions.append({'export':result,'source_root':root,'policies':{'snapshot.json':{'sha256':file_ref.sha256,'review_status':'approved','scope':'synthetic fixture only'}},'annotations':annotations})
    release=output/'release';manifest=publish_exports(release,contributions,fixture=True)
    report={'scope':'synthetic fixture; no formal E1/E2 or research test','producer_commit':commit,'producer_runtime_digest':identity.source_digest,
            'release_root':str(release.resolve()),'release_hash':sha((release/'manifest.json').read_bytes()),
            'split_hash':sha((release/'split-manifest.json').read_bytes()),'release_id':manifest['id'],
            'audit':audit_release(release),'expected_records':expected,'external_calls':0}
    write_new(output/'publication.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build_fixture_release(args.output,workspace=args.workspace),ensure_ascii=False))


if __name__=='__main__':main()
