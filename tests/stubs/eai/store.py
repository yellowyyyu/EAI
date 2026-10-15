# -*- coding: utf-8 -*-
"""桩：eai.store.MemoryStore 的最小实现（仅测试用）。

与正式版（SQLite + FTS5）的差别：换成一个 JSON 文件 + 朴素子串匹配。
数据落在 $EAI_HOME/memory/stub_store.json；首次访问自动播种 3 条示例记忆。
接口签名与 specs/10_core.md §4 保持一致，dict 进 dict 出。
"""

from __future__ import annotations

import json
import os
import time

from .util import eai_home, new_id

_SEED = [
    {
        "id": "m20261010090000-0123",
        "ts": "2026-10-10 09:00:00",
        "updated_ts": "2026-10-10 09:00:00",
        "kind": "fact",
        "scope": "general",
        "title": "EAI 管家项目开工",
        "text": "EAI 私人管家项目的记忆系统在这一天开工。",
        "entities": ["EAI"],
        "importance": 0.6,
        "confidence": 0.8,
        "source": {"via": "stub"},
        "last_used_ts": None,
        "use_count": 0,
        "supersedes": None,
        "superseded_by": None,
        "status": "active",
        "meta": {},
    },
    {
        "id": "m20261011100000-0456",
        "ts": "2026-10-11 10:00:00",
        "updated_ts": "2026-10-11 10:00:00",
        "kind": "preference",
        "scope": "general",
        "title": "喜欢短句直给",
        "text": "主人喜欢短句直给的汇报，不要客套话。",
        "entities": [],
        "importance": 0.8,
        "confidence": 0.8,
        "source": {"via": "stub"},
        "last_used_ts": None,
        "use_count": 0,
        "supersedes": None,
        "superseded_by": None,
        "status": "active",
        "meta": {},
    },
    {
        "id": "m20261012110000-0789",
        "ts": "2026-10-12 11:00:00",
        "updated_ts": "2026-10-12 11:00:00",
        "kind": "project",
        "scope": "示例项目",
        "title": "示例项目论文改稿",
        "text": "示例项目论文正在按审稿意见改稿。",
        "entities": ["示例项目"],
        "importance": 0.6,
        "confidence": 0.8,
        "source": {"via": "stub"},
        "last_used_ts": None,
        "use_count": 0,
        "supersedes": None,
        "superseded_by": None,
        "status": "active",
        "meta": {},
    },
]


class MemoryStore:
    """最小可用的记忆库桩：JSON 文件 + 朴素匹配。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.path.join(eai_home(), "memory", "memory.db")
        self._path = os.path.join(eai_home(), "memory", "stub_store.json")
        self._records = self._load()

    # ---------------- 内部 ----------------

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [dict(r) for r in data if isinstance(r, dict)]
        except (OSError, ValueError):
            pass
        records = [dict(r) for r in _SEED]
        self._records = records
        self._save()
        return records

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._records, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except OSError:
            pass

    @staticmethod
    def _norm(s) -> str:
        return "".join(str(s or "").split()).lower()

    @staticmethod
    def _tokens(query) -> list:
        q = str(query or "").strip().lower()
        for ch in ("，", ",", "、", "。", "；", ";"):
            q = q.replace(ch, " ")
        return [t for t in q.split() if t]

    # ---------------- 规格接口 ----------------

    def add(self, rec: dict, dedupe: bool = True) -> dict:
        rec = dict(rec or {})
        if not rec.get("id"):
            rec["id"] = new_id()
        text = str(rec.get("text", ""))
        if dedupe and text:
            for r in self._records:
                if self._norm(r.get("text")) == self._norm(text):
                    if rec.get("updated_ts"):
                        r["updated_ts"] = rec["updated_ts"]
                    try:
                        r["importance"] = max(float(r.get("importance") or 0.0),
                                              float(rec.get("importance") or 0.0))
                    except (TypeError, ValueError):
                        pass
                    self._save()
                    return {"action": "merged", "id": r["id"]}
        self._records.append(rec)
        self._save()
        return {"action": "inserted", "id": rec["id"]}

    def get(self, mid: str):
        for r in self._records:
            if r.get("id") == mid:
                return dict(r)
        return None

    def search(self, query: str, k: int = 10, kinds=None, scope=None,
               include_archived: bool = False) -> list:
        tokens = self._tokens(query)
        hits = []
        for r in self._records:
            if not include_archived and r.get("status", "active") != "active":
                continue
            if kinds and r.get("kind") not in kinds:
                continue
            if scope and r.get("scope") != scope:
                continue
            title = str(r.get("title", "")).lower()
            hay = " ".join([title, str(r.get("text", "")),
                            " ".join(str(e) for e in (r.get("entities") or []))]).lower()
            rel = 0.0
            for t in tokens:
                if t in title:
                    rel = max(rel, 0.95)
                elif t in hay:
                    rel = max(rel, 0.75)
            if rel > 0.0:
                hits.append((dict(r), rel))
        hits.sort(key=lambda p: (-p[1], str(p[0].get("ts", ""))))
        try:
            limit = max(0, int(k))
        except (TypeError, ValueError):
            limit = 10
        return hits[:limit]

    def reinforce(self, mid: str, bump: float = 0.02) -> None:
        for r in self._records:
            if r.get("id") == mid:
                try:
                    imp = float(r.get("importance") or 0.0)
                except (TypeError, ValueError):
                    imp = 0.0
                r["importance"] = min(1.0, imp + bump * (1.0 - imp))
                r["use_count"] = int(r.get("use_count") or 0) + 1
                r["last_used_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._save()
                return

    def counts(self) -> dict:
        by_kind, by_scope, chars = {}, {}, 0
        for r in self._records:
            kind = str(r.get("kind") or "?")
            sc = str(r.get("scope") or "?")
            by_kind[kind] = by_kind.get(kind, 0) + 1
            by_scope[sc] = by_scope.get(sc, 0) + 1
            chars += len(str(r.get("text", "")))
        return {"total": len(self._records), "by_kind": by_kind,
                "by_scope": by_scope, "chars": chars}

    def log_event(self, kind: str, memory_id=None, **detail) -> None:
        return None
