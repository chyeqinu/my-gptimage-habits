# my-gptimage-habits 安装脚本（Windows）
# 用法：在本仓库根目录执行  powershell -ExecutionPolicy Bypass -File install\install.ps1 [-Target <目标技能目录>]
# 默认目标：$env:USERPROFILE\.agents\skills\my-gptimage-habits

param(
    [string]$Target = (Join-Path $env:USERPROFILE ".agents\skills\my-gptimage-habits")
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Items     = @("SKILL.md", "README.md", "LICENSE", "VERSION", "CHANGELOG.md", ".env.example", "scripts", "references")

New-Item -ItemType Directory -Force (Split-Path -Parent $Target) | Out-Null
if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
New-Item -ItemType Directory -Force $Target | Out-Null

foreach ($item in $Items) {
    $src = Join-Path $RepoRoot $item
    if (Test-Path $src) {
        Copy-Item $src -Destination $Target -Recurse -Force
    }
}

Get-ChildItem $Target -Recurse -Include "__pycache__" -Force -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "已安装到: $Target"
Write-Host ""
Write-Host "下一步（配置 API key，每台设备一次）："
Write-Host "  python `"$Target\scripts\gimg.py`" --set-key <你的key>"
Write-Host "  验证:   python `"$Target\scripts\gimg.py`" --show-config"
