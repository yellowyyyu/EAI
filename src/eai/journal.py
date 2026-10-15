# -*- coding: utf-8 -*-
"""情景日志：原始经历只增不改，按月分文件（journal/YYYY-MM.jsonl）。"""
from __future__ import annotations

import json
from pathlib import Path

from . import util


def journal_dir() -> Path:
    d = util.memory_dir() / "journal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_for(ts: str) -> Path:
    month = (ts or util.now_str())[:7]  # YYYY-MM
    return journal_dir() / f"{month}.jsonl"


def journal_append(rec: dict) -> None:
    """追加一条经历（唯一合法写操作只有追加）。"""
    rec = dict(rec)
    rec.setdefault("ts", util.now_str())
    p = _path_for(rec["ts"])
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def journal_tail(n: int = 10) -> list:
    """最近 n 条（跨月文件按文件名顺序合并后取尾）。"""
    files = sorted(journal_dir().glob("*.jsonl"))
    lines = []
    for p in files[-3:]:
        try:
            with open(p, encoding="utf-8") as f:
                lines.extend(f.read().splitlines())
        except Exception:
            continue
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out
