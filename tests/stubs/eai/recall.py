# -*- coding: utf-8 -*-
"""桩：eai.recall 的最小实现（仅测试用；接口与 specs/10_core.md §5 一致）。"""

from __future__ import annotations


def recall(store, query, k: int = 8, scope=None, kinds=None,
           include_archived: bool = False, reinforce: bool = True, now=None) -> list:
    """召回：store.search 拿候选，按 0.55·相关 + 0.30·重要 + 0.15·新近 打分排序。"""
    hits = store.search(query, k, kinds=kinds, scope=scope,
                        include_archived=include_archived)
    out = []
    for rec, rel in hits:
        d = dict(rec)
        try:
            imp = float(d.get("importance") or 0.5)
        except (TypeError, ValueError):
            imp = 0.5
        d["rel"] = float(rel)
        d["rec"] = 1.0          # 桩：新近度恒为 1
        d["score"] = round(0.55 * float(rel) + 0.30 * imp + 0.15 * 1.0, 4)
        out.append(d)
    out.sort(key=lambda d: -d["score"])
    return out


def project_context(store, scope, k: int = 6) -> list:
    """项目开场用：scope 命中为主的简版实现。"""
    hits = store.search("", k, scope=scope) if scope else []
    if not hits:
        hits = store.search(scope or "", k, scope=scope)
    out = []
    for rec, rel in hits[:k]:
        d = dict(rec)
        d["score"] = float(rel)
        out.append(d)
    return out
