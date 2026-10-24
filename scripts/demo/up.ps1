# RoleCraft demo: up. See docs/RUN-DEMO.md. Options: scripts/demo/up.ps1 --help
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv not found; install it from https://docs.astral.sh/uv/"
  exit 127
}
uv run --no-project --python 3.12 scripts/demo/launcher.py up @args
exit $LASTEXITCODE
