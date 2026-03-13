$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$desktopPath = [Environment]::GetFolderPath("Desktop")
$batPath = Join-Path $projectRoot "scripts\launch_bili2text.bat"

if (-not (Test-Path -LiteralPath $batPath)) {
    throw "Launcher not found: $batPath"
}

$shell = New-Object -ComObject WScript.Shell

$iconPath = Join-Path $projectRoot "favicon.ico"
function New-DesktopShortcut {
    param(
        [string]$Name,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$Description
    )

    $shortcutPath = Join-Path $desktopPath "$Name.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    if ($Arguments) {
        $shortcut.Arguments = $Arguments
    }
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = $Description
    if (Test-Path -LiteralPath $iconPath) {
        $shortcut.IconLocation = "$iconPath,0"
    }
    $shortcut.Save()
    Write-Host "Shortcut created: $shortcutPath"
}

New-DesktopShortcut `
    -Name "BilibiliHarvest" `
    -TargetPath $batPath `
    -Arguments "" `
    -Description "Launch BilibiliHarvest tray service"

Write-Host "Foreground target: $batPath"
if (-not (Test-Path -LiteralPath $iconPath)) {
    Write-Host "Icon file not found, shortcut will use default icon."
}
