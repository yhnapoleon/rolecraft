"""Runtime rebinding cannot carry content approval onto changed source material."""
from pathlib import Path
import importlib.util
import shutil
import pytest
from career_lab.scenarios.v2.loader import load_package

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('prepare_lineage',ROOT/'docs/integration/prepare_scenarios.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

@pytest.mark.parametrize('change',[None,'content','metadata'])
def test_lineage_checks_original_approved_manifest_and_actual_bytes(tmp_path,monkeypatch,change):
    relative=Path('scenarios/pm_pilot/v2/variants/pm_pilot_urgent')
    source=ROOT/relative;package=load_package(source);target=tmp_path/relative
    target.mkdir(parents=True)
    for rel in ['manifest.json',*[ref.path for ref in package.bundle.files]]:
        destination=target/rel;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/rel,destination)
    reviews=tmp_path/'scenarios/pm_pilot/v2/variants/reviews';reviews.mkdir()
    for name in ['authored-lineage-2.9.6.json','content-approval-2.9.0.json']:
        shutil.copyfile(ROOT/'scenarios/pm_pilot/v2/variants/reviews'/name,reviews/name)
    monkeypatch.chdir(tmp_path)
    if change=='content':
        with (target/'materials/brief-v1.md').open('a') as f:f.write('\nAltered business deadline.\n')
    elif change=='metadata':
        import json
        manifest=__import__('json').loads((target/'manifest.json').read_text());manifest['revision']='unreviewed';(target/'manifest.json').write_text(json.dumps(manifest))
    if change:
        with pytest.raises(RuntimeError,match='changed'):prepare.reviewed_authored_identity(target,package)
    else:
        assert prepare.reviewed_authored_identity(target,package)=='09604036833180f0f5d16185798f24cb13e04184d86fa5b6c97a3cd09abea505'
