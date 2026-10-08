"""Module entry and registration hook; integrator owns the global CLI."""
import argparse,os,sys
from career_lab.delegations.credentials import load_credentials
from career_lab.delegations.http_client import HttpAgentClient
from .protocol import Protocol
from .stdio import serve


def configure(parser):
    parser.add_argument('--config',default=os.environ.get('ROLECRAFT_MCP_CONFIG'),help='Path to private 0600 JSON config; never pass a token in arguments.')
    return parser


def register_cli(subparsers):
    parser=configure(subparsers.add_parser('mcp',help='Delegated stdio MCP'))
    parser.set_defaults(w06_handler=run)
    return parser


def run(args):
    try:
        if not args.config:raise ValueError()
        load_credentials(args.config)
        serve(Protocol(HttpAgentClient(args.config)))
    except Exception:
        print('mcp_configuration_or_transport_unavailable',file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    parser=configure(argparse.ArgumentParser(description='RoleCraft delegated stdio MCP; stdout is protocol only.'))
    return run(parser.parse_args(argv))


if __name__=='__main__':raise SystemExit(main())
