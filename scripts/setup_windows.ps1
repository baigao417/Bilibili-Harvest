$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot

function Write-ChineseLine {
    param([int[]]$Codes)
    Write-Host (-join ($Codes | ForEach-Object { [char]$_ }))
}

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
Write-ChineseLine -Codes @(0x540e,0x53f0,0x670d,0x52a1,0x5df2,0x542f,0x52a8,0x3002)
Write-ChineseLine -Codes @(0x4e0b,0x4e00,0x6b65,0xff1a)
Write-ChineseLine -Codes @(0x20,0x20,0x31,0x2e,0x20,0x6253,0x5f00,0x20,0x43,0x68,0x72,0x6f,0x6d,0x65,0x20,0x6269,0x5c55,0x7ba1,0x7406,0x9875,0x9762)
Write-ChineseLine -Codes @(0x20,0x20,0x32,0x2e,0x20,0x52a0,0x8f7d,0x20,0x62,0x72,0x6f,0x77,0x73,0x65,0x72,0x5f,0x65,0x78,0x74,0x65,0x6e,0x73,0x69,0x6f,0x6e,0x2f,0x20,0x76ee,0x5f55,0x4e3a,0x5df2,0x89e3,0x538b,0x6269,0x5c55)
Write-ChineseLine -Codes @(0x20,0x20,0x33,0x2e,0x20,0x6253,0x5f00,0x6269,0x5c55,0x20,0x64,0x61,0x73,0x68,0x62,0x6f,0x61,0x72,0x64)
Write-ChineseLine -Codes @(0x20,0x20,0x34,0x2e,0x20,0x6309,0x5411,0x5bfc,0x5b8c,0x6210,0x81ea,0x52a8,0x914d,0x5bf9)
Write-ChineseLine -Codes @(0x5982,0x679c,0x4f60,0x770b,0x5230,0x6258,0x76d8,0x56fe,0x6807,0xff0c,0x8bf4,0x660e,0x684c,0x9762,0x7aef,0x5df2,0x7ecf,0x8fd0,0x884c,0x3002)
