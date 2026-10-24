<#
Use this project's Python environment, which lives OUTSIDE OneDrive.

    . .\scripts\dev_env.ps1          # dot-source once per PowerShell session
    . .\scripts\dev_env.ps1 -Sync    # also bring the environment in line with uv.lock

The repository sits in a OneDrive-synced folder, and OneDrive interferes with virtual environments
(locked and restored files during installs). The environment is therefore kept in
%LOCALAPPDATA%\confidentiality-detector\venv.

This script affects only the current PowerShell session. It sets UV_PROJECT_ENVIRONMENT, so that
`uv sync` and `uv run` use that environment instead of creating .venv inside the repository, and
it activates the environment, so that `python`, `pytest` and `confidentiality-detector` resolve to
it. No global uv or Python setting is changed. VS Code terminals of this workspace get the same
variable from .vscode/settings.json.
#>
param([switch]$Sync)

$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "confidentiality-detector\venv"
$python = Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts\python.exe"

if ($Sync -or -not (Test-Path $python)) {
    uv sync --frozen --project (Split-Path $PSScriptRoot -Parent)
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit code $LASTEXITCODE)" }
}

. (Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts\activate.ps1")
Write-Host "confidentiality-detector environment: $env:UV_PROJECT_ENVIRONMENT"
