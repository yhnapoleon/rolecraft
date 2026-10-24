# RoleCraft demo: down. See docs/RUN-DEMO.md. Options: scripts/demo/down.ps1 --help
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv not found; install it from https://docs.astral.sh/uv/"
  exit 127
}
uv run --no-project --python 3.12 scripts/demo/launcher.py down @args
exit $LASTEXITCODE
