$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot

Write-Host "== BilibiliHarvest Windows Setup =="
Write-Host "project_root: $projectRoot"

where.exe py > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "未检测到 Python Launcher(py)。请先安装 Python 3.10+，推荐 3.12。"
}

$pythonVersion = & py -3.12 -V 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未检测到 Python 3.12，尝试使用默认 py。"
    $pythonVersion = & py -V
}
Write-Host "python: $pythonVersion"

& py -3.12 -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "依赖安装失败。"
}

& py -3.12 scripts\launcher.py --doctor
if ($LASTEXITCODE -ne 0) {
    throw "doctor 检查失败，请先修复环境问题。"
}

& powershell -ExecutionPolicy Bypass -File .\scripts\install_shortcut.ps1
if ($LASTEXITCODE -ne 0) {
    throw "创建桌面快捷方式失败。"
}

& powershell -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1 -StartNow
if ($LASTEXITCODE -ne 0) {
    throw "安装开机自启失败。"
}

Write-Host "首次启动后台托盘服务..."
Start-Process -FilePath "py" -ArgumentList "-3.12", "scripts\launcher.py" -WorkingDirectory $projectRoot | Out-Null

Write-Host ""
Write-Host "后台已启动，请在 Chrome 中加载 browser_extension/ 并打开 dashboard 完成自动配对。"
