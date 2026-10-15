# -*- coding: utf-8 -*-
"""固结流水线：inbox 收料 → 提炼 → 查重仲裁 → 落库 → 情景日志 + 当日摘要。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import extract as extract_mod
from . import journal, persona, util

SIM_THRESHOLD = 0.55   # 词元覆盖率≥此值 → 交 LLM 仲裁；仲裁不可用时一律新增（评审 M2：宁可重复，不可静默错并）


# ---------------- inbox 台账 ----------------

def _inbox_dir() -> Path:
    d = util.memory_dir() / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_jsonl(p: Path) -> list:
    out = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
    return out


def _append_jsonl(p: Path, obj: dict) -> None:
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_index() -> list:
    return _read_jsonl(_inbox_dir() / "index.jsonl")


def load_processed() -> dict:
    return {e.get("path"): e for e in _read_jsonl(_inbox_dir() / "processed.jsonl")}


# ---------------- 单条落库 ----------------

def apply_candidate(store, cand: dict, backend: str = "ollama", model: str = "fast") -> str:
    """查重 → 合并/覆盖/新增。返回 'inserted' / 'merged' / 'superseded'。
    纪律（评审 M2）：仲裁不可用或判不出来时，绝不按相似度静默合并——宁可重复，不可错并。"""
    pairs = store.search(cand["text"], k=3)
    for old, rel in pairs:
        if rel >= SIM_THRESHOLD:
            v = ""
            if backend != "rules":
                v = extract_mod.verdict_llm(cand["text"], old["text"], model=model)
            if v in ("same", "update"):
                store.merge(old["id"], cand)
                return "merged"
            if v == "conflict":
                store.supersede(old["id"], cand)
                return "superseded"
    # 精确/包含查重 + 新增（store.add 内部处理；覆盖率口径已修，见评审 M1）
    res = store.add(cand)
    return res["action"]


# ---------------- 摘要 ----------------

def _append_digest(date: str, scope: str, source: str, added: list, merged: list, supers: list) -> None:
    d = util.memory_dir() / "digests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{date}.md"
    lines = []
    if not p.exists():
        lines.append(f"# {date} 我记住的事\n")
    lines.append(f"\n## 来源：{source}（{scope}）")
    if added:
        lines.append(f"- 新增 {len(added)} 条：")
        for c in added:
            lines.append(f"  - （{c['kind']}）{c['title'] or c['text'][:24]}")
    if merged:
        lines.append(f"- 并入旧记忆 {len(merged)} 条：")
        for c in merged:
            lines.append(f"  - {c['title'] or c['text'][:24]}")
    if supers:
        lines.append(f"- 更正 {len(supers)} 条：")
        for c in supers:
            lines.append(f"  - 改为：{c['title'] or c['text'][:24]}")
    if not (added or merged or supers):
        lines.append("- （本轮无值得长期保留的内容）")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------- 主流程 ----------------

def consolidate(store, backend: str = "ollama", model: str = "fast", limit: int | None = None,
                dry_run: bool = False, progress=print) -> dict:
    """处理 inbox 中未固结的文件。单份失败跳过不中断。"""
    processed = load_processed()
    todo = [e for e in load_index() if e.get("path") not in processed]
    if limit:
        todo = todo[:limit]
    stats = {"files": 0, "new": 0, "merged": 0, "superseded": 0, "skipped": 0, "failed": 0}

    for e in todo:
        rel_path = e.get("path", "")
        p = _inbox_dir() / rel_path
        if not p.exists():
            stats["skipped"] += 1
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            stats["failed"] += 1
            _append_jsonl(_inbox_dir() / "failed.jsonl", {**e, "why": "read-error"})
            continue

        scope = util.norm_scope(e.get("project"))
        date = e.get("date") or util.now_str()[:10]
        context = {"scope": scope, "date": date, "source": rel_path}
        try:
            cands = extract_mod.extract_candidates(text, context, backend=backend, model=model)
        except Exception as ex:
            stats["failed"] += 1
            _append_jsonl(_inbox_dir() / "failed.jsonl", {**e, "why": f"extract:{ex}"[:200]})
            continue

        if dry_run:
            stats["files"] += 1
            stats["new"] += len(cands)
            progress(f"[dry] {rel_path} → 候选 {len(cands)} 条")
            continue

        added, merged, supers = [], [], []
        for c in cands:
            c.setdefault("scope", scope)
            c.setdefault("source", {"inbox": rel_path, "session_id": e.get("session_id")})
            if re.match(r"^\d{4}-\d{2}-\d{2}$", str(date)):
                c.setdefault("ts", f"{date} 12:00:00")  # 保留事件时间，新近度维度不失效（评审 M9）
            try:
                action = apply_candidate(store, c, backend=backend, model=model)
            except Exception:
                stats["failed"] += 1
                continue
            if action == "inserted":
                added.append(c)
                stats["new"] += 1
            elif action == "merged":
                merged.append(c)
                stats["merged"] += 1
            else:
                supers.append(c)
                stats["superseded"] += 1

        summary = "；".join((c["title"] or c["text"][:20]) for c in (added + supers)[:4]) or "无新增"
        journal.journal_append({
            "type": "session", "scope": scope, "summary": summary,
            "source": {"inbox": rel_path, "session_id": e.get("session_id"), "date": date},
        })
        _append_digest(date, scope, rel_path, added, merged, supers)
        _append_jsonl(_inbox_dir() / "processed.jsonl", {
            "path": rel_path, "ts": util.now_str(),
            "new": len(added), "merged": len(merged), "superseded": len(supers),
        })
        stats["files"] += 1
        progress(f"[固结] {rel_path} → +{len(added)} 并{len(merged)} 覆盖{len(supers)}")

    if not dry_run and stats["files"]:
        try:
            review_promises(store, backend=backend, model=model, progress=progress)
        except Exception:
            pass
        persona.refresh_persona(store)
    return stats


# ---------------- 承诺复核（评审 M4 遗留项，2026-10-15） ----------------

PROMISE_PROMPT = """你是承诺追踪器。下面是一个尚未兑现的承诺，和之后的一条记录。
判断这条记录是否表明承诺已经完成。只回答两个词之一：已兑现 / 未兑现。
承诺：{p}
后续记录：{c}"""


def review_promises(store, backend="ollama", model="fast", progress=print) -> int:
    """对每个未兑现承诺，看其后新记忆是否已表明兑现；LLM 确认后才归档销账。
    无 LLM（backend=rules）时不动手——宁可积压，不误销。"""
    if backend == "rules":
        return 0
    n = 0
    rows = store.conn.execute(
        "SELECT id, text, ts FROM memories WHERE status='active' AND kind='promise' ORDER BY ts"
    ).fetchall()
    for p in rows:
        try:
            cands = store.conn.execute(
                "SELECT text, ts FROM memories WHERE ts > ? AND status='active' ORDER BY ts LIMIT 50",
                (p["ts"],)).fetchall()
            ptoks = set(util.seg_text(p["text"]).split())
            if not ptoks:
                continue
            hit = None
            for c in cands:
                ctoks = set(util.seg_text(c["text"]).split())
                if len(ptoks & ctoks) / len(ptoks) >= 0.5:
                    hit = c["text"]
                    break
            if not hit:
                continue
            user = PROMISE_PROMPT.format(p=p["text"][:200], c=hit[:200])
            cfg = store.cfg
            model_name = (cfg.get("ollama_models") or {}).get(model, "qwen2.5:3b")
            resp = extract_mod._post_ollama(cfg, model_name, user,
                                            system="只回答：已兑现 或 未兑现", timeout=120)
            r = (resp or "").strip()
            if "未兑现" not in r and "兑现" in r:
                store.archive(p["id"], "auto-fulfilled")
                n += 1
                progress(f"[承诺] 已兑现并销账：{p['text'][:50]}")
        except Exception:
            continue
    return n
