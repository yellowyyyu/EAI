# -*- coding: utf-8 -*-
"""记忆存储：SQLite + FTS5（中文二元分词索引）。dict 进 dict 出，别越界裸 SQL。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from . import util

DDL = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'general',
  title TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  entities TEXT NOT NULL DEFAULT '[]',
  importance REAL NOT NULL DEFAULT 0.5,
  confidence REAL NOT NULL DEFAULT 0.8,
  source TEXT NOT NULL DEFAULT '{}',
  last_used_ts TEXT DEFAULT NULL,
  use_count INTEGER NOT NULL DEFAULT 0,
  supersedes TEXT DEFAULT NULL,
  superseded_by TEXT DEFAULT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope);
CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(seg, mid UNINDEXED, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  memory_id TEXT,
  detail TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


class MemoryStore:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = util.memory_dir() / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(DDL)
        self.conn.commit()
        self.cfg = util.load_config()

    def close(self):
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    # ---------------- 内部 ----------------

    def _row(self, row) -> dict:
        rec = dict(row)
        rec["entities"] = util.jload(rec.get("entities"), [])
        rec["source"] = util.jload(rec.get("source"), {})
        rec["meta"] = util.jload(rec.get("meta"), {})
        return rec

    def _seg_for(self, rec: dict) -> str:
        ents = rec.get("entities") or []
        if isinstance(ents, str):
            ents = util.jload(ents, [])
        return util.seg_text(" ".join([str(rec.get("title", "")), str(rec.get("text", "")),
                                       " ".join(map(str, ents))]))

    def _fts_replace(self, mid: str, seg: str) -> None:
        self.conn.execute("DELETE FROM mem_fts WHERE mid=?", (mid,))
        self.conn.execute("INSERT INTO mem_fts(seg, mid) VALUES (?, ?)", (seg, mid))

    def _fts_delete(self, mid: str) -> None:
        self.conn.execute("DELETE FROM mem_fts WHERE mid=?", (mid,))

    def _default_importance(self, kind: str) -> float:
        return float(self.cfg["importance_defaults"].get(kind, 0.5))

    def log_event(self, event: str, memory_id=None, **detail) -> None:
        self.conn.execute(
            "INSERT INTO events(ts, kind, memory_id, detail) VALUES (?,?,?,?)",
            (util.now_str(), event, memory_id, util.jdump(detail)),
        )
        self.conn.commit()

    # ---------------- 写 ----------------

    def add(self, rec: dict, dedupe: bool = True) -> dict:
        """新增一条记忆；dedupe=True 时先做规则查重，重复则合并进旧条。"""
        rec = dict(rec)
        rec.setdefault("id", util.new_id())
        rec.setdefault("ts", util.now_str())
        rec["updated_ts"] = now = rec["ts"]
        kind = rec.get("kind") or "fact"
        rec["kind"] = kind if kind in util.KINDS else "fact"
        rec["scope"] = rec.get("scope") or "general"
        rec["title"] = str(rec.get("title") or "")[:40]
        rec["text"] = str(rec.get("text") or "").strip()
        if not rec["text"]:
            raise ValueError("记忆正文为空，拒绝入库")
        rec["importance"] = float(rec.get("importance", self._default_importance(rec["kind"])))
        rec["importance"] = min(1.0, max(0.0, rec["importance"]))
        rec["confidence"] = float(rec.get("confidence", 0.8))

        if dedupe:
            hit = self._find_dup(rec)
            if hit is not None:
                self._merge_into(hit, rec)
                return {"action": "merged", "id": hit["id"]}

        self.conn.execute(
            """INSERT INTO memories(id, ts, updated_ts, kind, scope, title, text, entities,
                                    importance, confidence, source, status, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'active','{}')""",
            (rec["id"], rec["ts"], now, rec["kind"], rec["scope"], rec["title"], rec["text"],
             util.jdump(rec.get("entities") or []), rec["importance"], rec["confidence"],
             util.jdump(rec.get("source") or {})),
        )
        self._fts_replace(rec["id"], self._seg_for(rec))
        self.conn.commit()
        self.log_event("insert", rec["id"], kind=rec["kind"], scope=rec["scope"])
        return {"action": "inserted", "id": rec["id"]}

    def _find_dup(self, rec: dict):
        """规则查重：正文规范化后完全相等 / 互相包含且长度接近 → 返回旧条。"""
        norm_new = util.normalize_text(rec["text"])
        if not norm_new:
            return None
        for old, _rel in self.search(rec["text"], k=5):
            if old["id"] == rec.get("id"):
                continue
            norm_old = util.normalize_text(old["text"])
            if not norm_old:
                continue
            if norm_old == norm_new:
                return old
            short, long_ = sorted((norm_old, norm_new), key=len)
            if short and short in long_ and len(short) >= 0.8 * len(long_):
                return old
        return None

    def _merge_into(self, old, rec: dict) -> None:
        """把新信息并进旧条：包含关系取长者；互不包含则拼接（防"取更长"顶掉旧条独有信息——
        2026-10-15 回归发现的内容丢失 bug：视觉检查/verify 等条目曾被旧规则吃掉）；正文封顶 400 字。"""
        norm_old = util.normalize_text(old["text"])
        norm_new = util.normalize_text(rec["text"])
        if norm_new and norm_new in norm_old:
            text, title = old["text"], old["title"]
        elif norm_old and norm_old in norm_new:
            text, title = rec["text"], (rec["title"] or old["title"])
        elif norm_old and norm_new:
            text = (old["text"].rstrip("；;。 ") + "；" + rec["text"].strip())[:400]
            title = rec["title"] or old["title"]
        else:
            text, title = rec["text"], (rec["title"] or old["title"])
        ents = list(dict.fromkeys(list(old.get("entities") or []) + list(rec.get("entities") or [])))
        imp = max(old["importance"], rec["importance"])
        scope = old["scope"]
        if scope == "general" and rec["scope"] != "general":
            scope = rec["scope"]
        self.conn.execute(
            """UPDATE memories SET text=?, title=?, entities=?, importance=?, scope=?,
               updated_ts=?, status='active' WHERE id=?""",
            (text, title, util.jdump(ents), imp, scope, util.now_str(), old["id"]),
        )
        self._fts_replace(old["id"], self._seg_for({**old, "text": text, "title": title, "entities": ents}))
        self.conn.commit()
        self.log_event("merge", old["id"], new_text=rec["text"][:80])

    def supersede(self, old_id: str, rec: dict) -> dict:
        """新记忆覆盖旧记忆：旧条归档保留（可考古），新旧双向留指针。"""
        rec = dict(rec)
        rec.setdefault("id", util.new_id())
        rec.setdefault("ts", util.now_str())
        self.conn.execute(
            """INSERT INTO memories(id, ts, updated_ts, kind, scope, title, text, entities,
                                    importance, confidence, source, supersedes, status, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'active', '{}')""",
            (rec["id"], rec["ts"], rec["ts"], rec.get("kind", "fact"), rec.get("scope", "general"),
             rec.get("title", ""), rec["text"], util.jdump(rec.get("entities") or []),
             float(rec.get("importance", self._default_importance(rec.get("kind", "fact")))),
             float(rec.get("confidence", 0.8)), util.jdump(rec.get("source") or {}), old_id),
        )
        self.conn.execute(
            "UPDATE memories SET status='archived', superseded_by=?, updated_ts=? WHERE id=?",
            (rec["id"], util.now_str(), old_id),
        )
        self._fts_replace(rec["id"], self._seg_for(rec))
        self.conn.commit()
        self.log_event("supersede", rec["id"], old_id=old_id)
        return {"action": "superseded", "id": rec["id"], "old_id": old_id}

    def merge(self, old_id: str, rec: dict) -> dict:
        """公开的"并入旧条"操作（供固结仲裁 same/update 调用）。"""
        old = self.get(old_id)
        if not old:
            return self.add(rec, dedupe=False)
        rec = dict(rec)
        rec.setdefault("title", "")
        rec.setdefault("scope", "general")
        rec.setdefault("entities", [])
        rec["importance"] = float(rec.get("importance", self._default_importance(rec.get("kind", "fact"))))
        self._merge_into(old, rec)
        return {"action": "merged", "id": old_id}

    def archive(self, mid: str, reason: str = "") -> dict:
        """归档一条（承诺销账等）。不物理删除，仍可考古。"""
        self.conn.execute(
            "UPDATE memories SET status='archived', updated_ts=? WHERE id=?",
            (util.now_str(), mid),
        )
        self.conn.commit()
        self.log_event("archive", mid, reason=reason)
        return {"action": "archived", "id": mid}

    def reinforce(self, mid: str, bump: float = 0.02) -> None:
        """被回忆命中即强化：用得多 → 记得牢。
        收益随使用次数递减——防"最早露头者"滚雪球锁死席位（评审 M3）。"""
        row = self.conn.execute(
            "SELECT importance, use_count FROM memories WHERE id=?", (mid,)
        ).fetchone()
        if not row:
            return
        eff = bump / (1.0 + 0.5 * row["use_count"])
        imp = min(1.0, row["importance"] + eff * (1 - row["importance"]))
        self.conn.execute(
            "UPDATE memories SET use_count=use_count+1, last_used_ts=?, importance=? WHERE id=?",
            (util.now_str(), imp, mid),
        )
        self.conn.commit()
        self.log_event("recall", mid, importance=round(imp, 4))

    # ---------------- 读 ----------------

    def get(self, mid: str):
        row = self.conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        return self._row(row) if row else None

    def _fts_query(self, match: str, limit: int, include_archived: bool):
        """FTS5 查询；JOIN 直接过滤归档（防被覆盖旧条占满候选名额，评审 M12）。
        返回按匹配度降序的 [mid]；异常写 stderr 后返回空（不静默吞，评审 M1）。"""
        if not match:
            return []
        try:
            rows = self.conn.execute(
                """SELECT mem_fts.mid AS mid FROM mem_fts
                   JOIN memories m ON m.id = mem_fts.mid
                   WHERE mem_fts MATCH ? AND (? OR m.status='active')
                   ORDER BY bm25(mem_fts) ASC LIMIT ?""",
                (match, include_archived, limit),
            ).fetchall()
            return [r["mid"] for r in rows]
        except sqlite3.OperationalError as ex:
            print(f"[eai.store] FTS 查询被拒（已忽略该梯队）：{ex}", file=sys.stderr)
            return []

    def _seg_of(self, mid: str) -> str:
        row = self.conn.execute("SELECT seg FROM mem_fts WHERE mid=? LIMIT 1", (mid,)).fetchone()
        return row["seg"] if row else ""

    def search(self, query: str, k: int = 10, kinds=None, scope=None,
               include_archived: bool = False):
        """检索：短语 → 全词与 → 任一词 → LIKE 兜底。
        rel = 查询词元在条目里的覆盖率（绝对口径，与候选池无关，阈值才有意义，评审 M1）。"""
        q_tokens = util.seg_text(query).split()
        qset = set(q_tokens)
        phrase = util.build_match_phrase(query)
        andq = util.build_match_and(query)

        ordered, seen, like_hit = [], set(), False
        if qset:
            limit = max(k * 3, 12)
            for match in (phrase, andq, util.build_match_or(query)):
                if len(ordered) >= limit:
                    break
                if not match:
                    continue
                for mid in self._fts_query(match, limit, include_archived):
                    if mid not in seen:
                        seen.add(mid)
                        ordered.append(mid)
            if not ordered:  # 单字/特殊字符：LIKE 兜底（design §6.3 承诺的实现）
                rows = self.conn.execute(
                    """SELECT id FROM memories
                       WHERE (text LIKE ? OR title LIKE ?) AND (? OR status='active')
                       LIMIT ?""",
                    (f"%{query}%", f"%{query}%", include_archived, k),
                ).fetchall()
                ordered = [r["id"] for r in rows]
                like_hit = True
        else:
            rows = self.conn.execute(
                """SELECT id FROM memories
                   WHERE (? OR status='active') AND (? IS NULL OR scope=?)
                   ORDER BY importance DESC, updated_ts DESC LIMIT ?""",
                (include_archived, scope, scope, k),
            ).fetchall()
            ordered = [r["id"] for r in rows]

        pos = {mid: i for i, mid in enumerate(ordered)}
        out = []
        for mid in ordered:
            rec = self.get(mid)
            if not rec:
                continue
            if not include_archived and rec["status"] != "active":
                continue
            if kinds and rec["kind"] not in kinds:
                continue
            if scope and rec["scope"] != scope:
                continue
            if like_hit or not qset:
                rel = 0.5
            else:
                matched = len(qset & set(self._seg_of(mid).split()))
                rel = matched / len(qset)
            out.append((rec, rel, pos.get(mid, 0)))
        out.sort(key=lambda t: (-t[1], t[2]))  # 覆盖率降序，同分保持 FTS 相关序
        return [(rec, rel) for rec, rel, _ in out[:k]]

    # ---------------- 统计 ----------------

    def counts(self) -> dict:
        c = self.conn
        total = c.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"]
        active = c.execute("SELECT COUNT(*) n FROM memories WHERE status='active'").fetchone()["n"]
        by_kind = {r["kind"]: r["n"] for r in c.execute(
            "SELECT kind, COUNT(*) n FROM memories WHERE status='active' GROUP BY kind")}
        by_scope = {r["scope"]: r["n"] for r in c.execute(
            "SELECT scope, COUNT(*) n FROM memories WHERE status='active' GROUP BY scope ORDER BY n DESC")}
        chars = c.execute("SELECT COALESCE(SUM(LENGTH(text)+LENGTH(title)),0) n FROM memories").fetchone()["n"]
        span = c.execute("SELECT MIN(ts) a, MAX(ts) b FROM memories").fetchone()
        db_bytes = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                db_bytes += p.stat().st_size
        ev = {r["kind"]: r["n"] for r in c.execute(
            "SELECT kind, COUNT(*) n FROM events GROUP BY kind")}
        return {
            "total": total, "active": active, "archived": total - active,
            "by_kind": by_kind, "by_scope": by_scope, "chars": chars,
            "earliest": span["a"], "latest": span["b"],
            "db_bytes": db_bytes, "events": ev,
        }

    def growth_series(self):
        """按天累计曲线（画增长图用）：[(date, 当日新增, 累计)]。"""
        rows = self.conn.execute(
            "SELECT substr(ts,1,10) d, COUNT(*) n FROM memories GROUP BY d ORDER BY d"
        ).fetchall()
        out, cum = [], 0
        for r in rows:
            cum += r["n"]
            out.append((r["d"], r["n"], cum))
        return out
