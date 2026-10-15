# -*- coding: utf-8 -*-
"""桩：eai.util 的最小实现（仅测试用；接口与 specs/10_core.md 冻结版一致）。"""

from __future__ import annotations

import json
import os
import random
import time


def eai_home() -> str:
    """EAI 根目录：环境变量 EAI_HOME 优先；否则从本文件上溯定位。"""
    env = os.environ.get("EAI_HOME")
    if env:
        return os.path.abspath(env)
    # tests/stubs/eai/util.py → tests/stubs/eai → tests/stubs → tests → EAI
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        d = os.path.dirname(d)
    return d


def new_id() -> str:
    """'m' + YYYYMMDDHHMMSS + '-' + 4 位随机 hex（可排序）。"""
    return "m" + time.strftime("%Y%m%d%H%M%S") + "-%04x" % random.randrange(0x10000)


def load_config() -> dict:
    """读取 $EAI_HOME/config.json；不存在或坏文件就返回空 dict。"""
    path = os.path.join(eai_home(), "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
