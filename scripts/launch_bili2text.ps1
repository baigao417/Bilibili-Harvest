param(
    [switch]$Doctor
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path

Set-Location -LiteralPath $projectRoot

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[ERROR] Python launcher 'py' was not found in PATH."
    Write-Host "Install Python 3.12 and ensure the py launcher is available."
    Write-Host "Download: https://www.python.org/downloads/windows/"
    Read-Host "Press Enter to close"
    exit 1
}

$args = @("-3.12", "scripts/launcher.py")
if ($Doctor) {
    $args += "--doctor"
}

& py @args
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] BilibiliHarvest failed to start. Exit code: $exitCode"
    Write-Host "Try: py -3.12 scripts/launcher.py --doctor"
    Read-Host "Press Enter to close"
}

exit $exitCode
