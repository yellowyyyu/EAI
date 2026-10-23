# EAI 一条命令安装（Windows）
# 用法：powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/yellowyyyu/EAI/main/tools/bootstrap.ps1 | iex"
$ErrorActionPreference = "Stop"
$repo = "https://github.com/yellowyyyu/EAI.git"
$dest = Join-Path $env:USERPROFILE "EAI"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "没找到 git，请先安装 Git：https://git-scm.com/downloads"
}

if (Test-Path (Join-Path $dest ".git")) {
    Write-Host "更新已有安装：$dest"
    git -C $dest pull --ff-only
} else {
    Write-Host "下载到 $dest"
    git clone --depth 1 $repo $dest
}

$py = Get-Command python -ErrorAction SilentlyContinue
$pyargs = @()
if (-not $py) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { throw "没找到 Python，请先安装 Python 3.8+：https://www.python.org/downloads/" }
    $pyargs = @("-3")
}

& $py.Source @pyargs (Join-Path $dest "tools\install.py") --yes
