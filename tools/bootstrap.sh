#!/usr/bin/env bash
# EAI 一条命令安装（macOS / Linux）
# 用法：curl -fsSL https://raw.githubusercontent.com/yellowyyyu/EAI/main/tools/bootstrap.sh | bash
set -euo pipefail
DEST="$HOME/EAI"

command -v git >/dev/null 2>&1 || { echo "没找到 git，请先安装 Git"; exit 1; }

if [ -d "$DEST/.git" ]; then
  echo "更新已有安装：$DEST"
  git -C "$DEST" pull --ff-only
else
  echo "下载到 $DEST"
  git clone --depth 1 https://github.com/yellowyyyu/EAI.git "$DEST"
fi

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "没找到 Python，请先安装 Python 3.8+"; exit 1; }

PYTHONUTF8=1 "$PY" "$DEST/tools/install.py" --yes
