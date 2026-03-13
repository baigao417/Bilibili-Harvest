$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot

Write-Host "== BilibiliHarvest Windows Setup =="
Write-Host "project_root: $projectRoot"

where.exe py > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Python Launcher (py) was not found. Install Python 3.10+ first. Recommended version: 3.12."
}

$pythonVersion = & py -3.12 -V 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.12 was not found. Falling back to the default py launcher."
    $pythonVersion = & py -V
}
Write-Host "python: $pythonVersion"

& py -3.12 -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

& py -3.12 scripts\launcher.py --doctor
if ($LASTEXITCODE -ne 0) {
    throw "Doctor check failed. Fix the environment issues above before continuing."
}

& powershell -ExecutionPolicy Bypass -File .\scripts\install_shortcut.ps1
if ($LASTEXITCODE -ne 0) {
    throw "Creating the desktop shortcut failed."
}

& powershell -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1 -StartNow
if ($LASTEXITCODE -ne 0) {
    throw "Installing autostart failed."
}

Write-Host "Starting the tray service..."
Start-Process -FilePath "py" -ArgumentList "-3.12", "scripts\launcher.py" -WorkingDirectory $projectRoot | Out-Null

Write-Host ""
Write-Host "Tray service started."
Write-Host "Next:"
Write-Host "  1. Open Chrome Extensions"
Write-Host "  2. Load browser_extension/ as an unpacked extension"
Write-Host "  3. Open the extension dashboard"
Write-Host "  4. Finish auto-pairing"
