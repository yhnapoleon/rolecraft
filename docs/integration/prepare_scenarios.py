"""Build locale runtimes offline from immutable W02 content; never repair at startup."""
import argparse,json,hashlib,subprocess,sys,shutil
from pathlib import Path
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule

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
        entries.append({'root':str(target.resolve()),'work_language':locale,'scenario_hash':module.package.content_hash,'authored_manifest':package.content_hash,'content_unchanged':True,'rebind_evidence':str(evidence.resolve())})
    index=args.output/'catalog.json';index.write_text(json.dumps({'schema_version':1,'scenarios':entries},ensure_ascii=False,indent=2)+'\n');print(index.resolve())

if __name__=='__main__':main()
