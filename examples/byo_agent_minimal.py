"""Explicit no-model create/test example. Human adoption/submission stay separate."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from byo_agent_client.workflow import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Private delegate JSON config path')
    parser.add_argument('--journal', type=Path, required=True, help='Private persistent request/result journal; reused on resume')
    parser.add_argument('--config-version', type=int, required=True)
    parser.add_argument('--query', default='Which source supports this draft?')
    parser.add_argument('--wait-seconds', type=float, default=5.0, help='Bounded wait per request (0–30); 0 queries once')
    args = parser.parse_args(argv)
    try:
        record = run(args.config, args.journal, config_version=args.config_version,
                     query=args.query, wait_seconds=args.wait_seconds)
    except Exception:
        print('example_stopped; retain the journal and recover the original request before retrying', file=sys.stderr)
        return 1
    if record['status'] == 'completed':
        print('Completed ' + str(len(record['steps'])) + ' explicit Agent operations; human review is next.')
        return 0
    step = next(step for step in record['steps'] if step['status'] != 'completed')
    print('Request ' + step['command']['request_id'] + ': ' + record['status'] + '; no later operation was started.')
    for job in step['request_result']['jobs']:
        print('Job ' + job['job_id'] + ': ' + job['status'])
    print('Recover with requests.read using the same request_id, or resume this journal after resolving the reported state.')
    return 1 if record['status'] == 'failed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
