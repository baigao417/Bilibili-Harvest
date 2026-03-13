param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$starterScript = (Resolve-Path -LiteralPath (Join-Path $projectRoot "scripts\start_bili2text_background.ps1")).Path

$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$valueName = "BilibiliHarvestBackground"
$valueData = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$starterScript`" -Quiet"

New-Item -Path $runKeyPath -Force | Out-Null
Set-ItemProperty -Path $runKeyPath -Name $valueName -Value $valueData

Write-Host "Autostart installed for current user."
Write-Host "Registry: $runKeyPath\$valueName"

if ($StartNow) {
    & $starterScript
}
