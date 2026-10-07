"""Explicit no-model create/test example. Human adoption/submission stay separate."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from byo_agent_client.workflow import run


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,help='Private delegate JSON config path')
    parser.add_argument('--journal',type=Path,required=True,help='Private persistent request/result journal; reused on resume')
    parser.add_argument('--config-version',type=int,required=True)
    parser.add_argument('--query',default='Which source supports this draft?')
    args=parser.parse_args(argv)
    try:record=run(args.config,args.journal,config_version=args.config_version,query=args.query)
    except Exception:
        print('example_stopped; retain the journal and recover the original request before retrying',file=sys.stderr);return 1
    print('Completed '+str(len(record['steps']))+' explicit Agent operations; human review is next.');return 0


if __name__=='__main__':raise SystemExit(main())
