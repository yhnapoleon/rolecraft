"""Build locale runtimes offline from immutable W02 content; never repair at startup."""
import argparse,json,hashlib,subprocess,sys,shutil
from pathlib import Path
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule

def reviewed_authored_identity(source, package):
    """Prove unchanged authored bytes against the exact independently reviewed manifest."""
    folder=Path('scenarios/pm_pilot/v2/variants/reviews')
    approval=json.loads((folder/'content-approval-2.9.0.json').read_text())
    lineage=json.loads((folder/'authored-lineage-2.9.6.json').read_text())
    approved={(x['scenario_id'],x['work_language'],x['scenario_hash']) for x in approval['bundles']}
    match=next((x for x in lineage['bundles'] if Path(x['root']).resolve()==source.resolve()),None)
    if match is None:return None
    raw=match['reviewed_manifest_text'].encode()
    identity=hashlib.sha256(raw).hexdigest()
    if approval.get('verdict')!='accepted' or approval.get('scope')!='authored_content_only' or (package.bundle.id,package.locale,identity) not in approved:
        raise RuntimeError('Source content lacks an exact independent approval')
    previous=json.loads(raw);current=json.loads((source/'manifest.json').read_text())
    if {k:v for k,v in previous.items() if k!='files'}!={k:v for k,v in current.items() if k!='files'}:
        raise RuntimeError('Authored manifest metadata changed')
    if {r['path'] for r in previous['files']}!={r['path'] for r in current['files']}:
        raise RuntimeError('Authored file membership changed')
    for ref in previous['files']:
        if not ref['path'].startswith('runtime/') and hashlib.sha256((source/ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise RuntimeError('Previously reviewed authored content changed: '+ref['path'])
    return identity


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    authored=Path('scenarios/pm_pilot/v2');sources=[authored,authored/'locales/en',*[source for name in ['pm_pilot_urgent','pm_pilot_capacity15'] for source in [authored/'variants'/name,authored/'variants'/name/'locales/en']]]
    entries=[]
    for source in sources:
        package=load_package(source);locale=package.locale;target=args.output/package.bundle.id/locale
        if target.exists():raise RuntimeError('Output exists; use a fresh build directory')
        target.mkdir(parents=True);(target/'manifest.json').write_bytes((source/'manifest.json').read_bytes())
        for ref in package.bundle.files:
            path=target/ref.path;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/ref.path,path)
        evidence=args.output/(package.bundle.id+'-'+locale+'-rebind.json')
        result=subprocess.run([sys.executable,'docs/integration/rebind_runtime.py','--root',str(target),'--with-w05','--evidence',str(evidence)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr or result.stdout)
        module=ScenarioModule(target)
        entries.append({'root':str(target.resolve()),'work_language':locale,'scenario_hash':module.package.content_hash,'authored_manifest':package.content_hash,'reviewed_authored_manifest':reviewed_authored_identity(source,package),'content_unchanged':True,'rebind_evidence':str(evidence.resolve())})
    index=args.output/'catalog.json';index.write_text(json.dumps({'schema_version':1,'scenarios':entries},ensure_ascii=False,indent=2)+'\n');print(index.resolve())

if __name__=='__main__':main()
