#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台入口：python tools/run_eai.py <子命令> …
等价于在仓库里跑 `python -m eai <子命令>`，不用手动设 PYTHONPATH。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("EAI_HOME", str(ROOT))
    return subprocess.run([sys.executable, "-m", "eai", *sys.argv[1:]],
                          cwd=str(ROOT), env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
