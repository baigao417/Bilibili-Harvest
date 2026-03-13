param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$launcherPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot "scripts\launcher.py")).Path

function Write-Info {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host $Message
    }
}

$escaped = [regex]::Escape($launcherPath)
$targets = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe", "py.exe") -and
            ($_.CommandLine -match $escaped -or $_.CommandLine -match "scripts[\\/]+launcher\.py") -and
            $_.CommandLine -match "--background"
        }
)

if ($targets.Count -eq 0) {
    Write-Info "No background service process found."
    exit 0
}

foreach ($proc in $targets) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Info "Stopped background service PID: $($proc.ProcessId)"
    } catch {
        Write-Info "Failed to stop PID $($proc.ProcessId): $($_.Exception.Message)"
    }
}
