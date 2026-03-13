param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$launcherPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot "scripts\launcher.py")).Path
$launcherArg = "scripts/launcher.py"

function Write-Info {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host $Message
    }
}

function Get-BackgroundProcesses {
    param([string]$LauncherPath)
    $escaped = [regex]::Escape($LauncherPath)
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe", "py.exe") -and
            ($_.CommandLine -match $escaped -or $_.CommandLine -match "scripts[\\/]+launcher\.py") -and
            $_.CommandLine -match "--background"
        }
}

$running = @(Get-BackgroundProcesses -LauncherPath $launcherPath)
if ($running.Count -gt 0) {
    Write-Info "Background service is already running (PID: $($running[0].ProcessId))."
    exit 0
}

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    throw "Python launcher 'py' was not found in PATH."
}

$pythonExe = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
if (-not $pythonExe) {
    throw "Failed to resolve Python 3.12 executable."
}

$proc = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList @($launcherArg, "--background") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if ($proc.HasExited) {
    throw "Background service exited immediately. Run 'py -3.12 scripts/launcher.py --background' to inspect logs."
}

Write-Info "Background service started (PID: $($proc.Id))."
