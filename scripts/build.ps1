$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv。请先按 README 安装开发依赖。"
}

if (Get-Process -Name "cyberbody" -ErrorAction SilentlyContinue) {
    throw "cyberbody 正在运行，便携目录中的文件可能被锁定。请先执行 cyberbody.exe stop 或退出应用。"
}

Push-Location $ProjectRoot
try {
    & $Python -m ruff check src tests scripts cyberbody_entry.py
    if ($LASTEXITCODE -ne 0) { throw "Ruff 检查失败。" }

    & $Python -m ruff format --check src tests scripts cyberbody_entry.py
    if ($LASTEXITCODE -ne 0) { throw "Ruff 格式检查失败。" }

    & $Python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "mypy 类型检查失败。" }

    & $Python -m bandit -q -r src -c pyproject.toml
    if ($LASTEXITCODE -ne 0) { throw "Bandit 安全检查失败。" }

    & $Python -m pytest --cov=cyberbody --cov-report=term-missing
    if ($LASTEXITCODE -ne 0) { throw "测试失败。" }

    & $Python scripts\privacy_audit.py
    if ($LASTEXITCODE -ne 0) { throw "隐私扫描失败。" }

    & $Python scripts\check_docs.py
    if ($LASTEXITCODE -ne 0) { throw "文档链接检查失败。" }

    & $Python -m PyInstaller --noconfirm --clean cyberbody.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }

    $Archive = Join-Path $ProjectRoot "dist\cyberbody-Windows-x64.zip"
    Compress-Archive -LiteralPath (Join-Path $ProjectRoot "dist\cyberbody") -DestinationPath $Archive -CompressionLevel Optimal -Force
    $Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
    "$($Hash.Hash)  $([System.IO.Path]::GetFileName($Archive))" | Set-Content -LiteralPath "$Archive.sha256" -Encoding ascii
} finally {
    Pop-Location
}

Write-Host "构建完成：$ProjectRoot\dist\cyberbody-Windows-x64.zip"
