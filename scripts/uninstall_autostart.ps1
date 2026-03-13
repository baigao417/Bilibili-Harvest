param(
    [switch]$StopNow
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$stopperScript = (Resolve-Path -LiteralPath (Join-Path $projectRoot "scripts\stop_bili2text_background.ps1")).Path

$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$valueName = "BilibiliHarvestBackground"

try {
    Remove-ItemProperty -Path $runKeyPath -Name $valueName -ErrorAction Stop
    Write-Host "Autostart removed."
} catch {
    Write-Host "Autostart entry not found."
}

if ($StopNow) {
    & $stopperScript
}
