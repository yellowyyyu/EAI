# -*- coding: utf-8 -*-
"""回忆：相关 × 重要 × 新近 打分检索；用则强化（越用越熟）。"""
from __future__ import annotations

from datetime import datetime

from . import util


def _recency(ts: str, kind: str, cfg: dict, now: datetime | None) -> float:
    hl = float(cfg["halflife_days"].get(kind, 365))
    if kind == "identity" or hl <= 0:
        return 1.0
    return 0.5 ** (util.age_days(ts, now) / hl)


def recall(store, query: str, k: int = 8, scope: str | None = None, kinds=None,
           include_archived: bool = False, reinforce: bool = True,
           now: datetime | None = None) -> list:
    """检索记忆。返回条目列表（原记录字段 + score/rel/rec），按 score 降序。"""
    cfg = getattr(store, "cfg", None) or util.load_config()
    w = cfg["weights"]
    bump = float(cfg.get("reinforce_bump", 0.02))

    pairs = store.search(query, k=max(k * 3, 20), kinds=kinds, include_archived=include_archived)
    if not pairs:
        return []

    scored = []
    for rec, rel in pairs:
        recency = _recency(rec["ts"], rec["kind"], cfg, now)
        score = w["rel"] * rel + w["imp"] * rec["importance"] + w["rec"] * recency
        if scope and rec["scope"] == scope:
            score += w.get("scope_bonus", 0.0)
        item = dict(rec)
        item["score"] = round(score, 4)
        item["rel"] = round(rel, 4)
        item["rec"] = round(recency, 4)
        scored.append(item)

    scored.sort(key=lambda r: -r["score"])
    top = scored[:k]
    if reinforce:
        for t in top:
            if t["score"] >= 0.35:
                store.reinforce(t["id"], bump)
    return top


def project_context(store, scope: str, k: int = 6, now: datetime | None = None) -> list:
    """项目开场用：按 scope 取现行条目，重要度 + 新近度合成排序。不强化。"""
    if not scope:
        return []
    cfg = getattr(store, "cfg", None) or util.load_config()
    rows = store.conn.execute(
        """SELECT * FROM memories WHERE scope=? AND status='active'
           ORDER BY updated_ts DESC LIMIT ?""",
        (scope, max(k * 4, 24)),
    ).fetchall()
    out = []
    for row in rows:
        rec = store._row(row)
        recency = _recency(rec["ts"], rec["kind"], cfg, now)
        rec["score"] = round(0.6 * rec["importance"] + 0.4 * recency, 4)
        out.append(rec)
    out.sort(key=lambda r: -r["score"])
    return out[:k]
