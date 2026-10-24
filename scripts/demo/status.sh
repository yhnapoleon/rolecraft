#!/bin/sh
# RoleCraft demo: status. See docs/RUN-DEMO.md. Options: scripts/demo/status.sh --help
cd "$(dirname "$0")/../.." || exit 1
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; install it from https://docs.astral.sh/uv/" >&2
  exit 127
fi
exec uv run --no-project --python 3.12 scripts/demo/launcher.py status "$@"
