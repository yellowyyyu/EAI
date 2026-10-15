#!/usr/bin/env bash
# EAI 一键安装（Linux / macOS）
set -e
cd "$(dirname "$0")/.."
PY="$(command -v python3 || command -v python)"
PYTHONUTF8=1 PYTHONPATH="$PWD/src" "$PY" tools/install.py "$@"
