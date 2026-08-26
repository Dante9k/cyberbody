$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv。请先按 CONTRIBUTING.md 安装开发依赖。"
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
} finally {
    Pop-Location
}

Write-Host "全部质量检查已通过。"
