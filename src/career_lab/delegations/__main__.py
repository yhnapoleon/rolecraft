"""Run the delegation server factory; shared global CLI registration remains with workbench."""

import argparse
import sys

from career_lab.contracts import v2 as C
from .factory import create_scenario_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--scenario-package", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        app = create_scenario_app(
            database_url=args.database_url, scenario_package=args.scenario_package
        )
    except C.ProtocolError as error:
        print(error.code, file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
