param(
    [string]$Destination = "..\Bilibili-Harvest-public"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$destinationPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot $Destination) -ErrorAction SilentlyContinue)
if ($null -eq $destinationPath) {
    $destinationPath = Join-Path $projectRoot $Destination
} else {
    $destinationPath = $destinationPath.Path
}

Write-Host "Exporting clean public snapshot..."
Write-Host "source: $projectRoot"
Write-Host "dest:   $destinationPath"

if (Test-Path -LiteralPath $destinationPath) {
    Remove-Item -LiteralPath $destinationPath -Recurse -Force
}
New-Item -ItemType Directory -Path $destinationPath | Out-Null

$excludeDirs = @(
    ".git",
    ".venv",
    "__pycache__",
    "skills",
    "config\batches",
    "config\tmp",
    "audio",
    "bilibili_video",
    "outputs"
)

$excludeFiles = @(
    "config\runtime.json",
    "cookies.txt"
)

$robocopyArgs = @(
    $projectRoot,
    $destinationPath,
    "/MIR",
    "/XD"
) + $excludeDirs + @(
    "/XF"
) + $excludeFiles

& robocopy @robocopyArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) {
    throw "robocopy failed with exit code $rc"
}

foreach ($rel in $excludeFiles) {
    $target = Join-Path $destinationPath $rel
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force
    }
}

foreach ($rel in @("skills", "config\batches", "config\tmp", "audio", "bilibili_video", "outputs")) {
    $target = Join-Path $destinationPath $rel
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

Write-Host ""
Write-Host "Public snapshot exported successfully."
Write-Host "Next steps:"
Write-Host "  cd `"$destinationPath`""
Write-Host "  git init"
Write-Host "  git branch -M main"
Write-Host "  git remote add origin https://github.com/baigao417/Bilibili-Harvest.git"
Write-Host "  git add ."
Write-Host "  git commit -m `"Initial public release`""
