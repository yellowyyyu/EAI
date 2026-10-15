# -*- coding: utf-8 -*-
"""人格与画像：core/master.md（主人画像）、core/promises.md（承诺台账），版本化留档。"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from . import util


def core_dir() -> Path:
    d = util.memory_dir() / "core"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _active(store, kinds, limit, order="importance"):
    ks = ",".join("'%s'" % k for k in kinds)
    rows = store.conn.execute(
        f"""SELECT * FROM memories WHERE status='active' AND kind IN ({ks})
            ORDER BY importance DESC, updated_ts DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [store._row(r) for r in rows]


def build_master_md(store) -> str:
    now = util.now_str()
    lines = [f"# 主人画像（自动生成 · 最后更新 {now}）", ""]

    prefs = _active(store, ("correction", "preference"), 15)
    lines.append("## 长期偏好与红线（按重要度）")
    if prefs:
        for r in prefs:
            tag = r["kind"]
            lines.append(f"- {r['text']}（{tag}，记于 {r['ts'][:10]}）")
    else:
        lines.append("- （暂无）")
    lines.append("")

    facts = _active(store, ("fact",), 10)
    lines.append("## 关键事实")
    if facts:
        for r in facts:
            lines.append(f"- {r['text']}（记于 {r['ts'][:10]}）")
    else:
        lines.append("- （暂无）")
    lines.append("")

    lines.append("## 在做的项目")
    proj_rows = store.conn.execute(
        """SELECT scope, MAX(updated_ts) mx FROM memories
           WHERE status='active' AND kind='project' AND scope != 'general'
           GROUP BY scope ORDER BY mx DESC LIMIT 8""",
    ).fetchall()
    if proj_rows:
        for pr in proj_rows:
            scope = pr["scope"]
            one = store.conn.execute(
                """SELECT title, text, ts FROM memories
                   WHERE kind='project' AND scope=? AND status='active'
                   ORDER BY updated_ts DESC LIMIT 1""",
                (scope,),
            ).fetchone()
            if one:
                lines.append(f"- {scope}：{one['text']}（记于 {one['ts'][:10]}）")
    else:
        lines.append("- （暂无）")
    lines.append("")

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    recents = store.conn.execute(
        """SELECT kind, title, text FROM memories
           WHERE status='active' AND ts >= ? ORDER BY ts DESC LIMIT 10""",
        (cutoff,),
    ).fetchall()
    lines.append("## 最近关注")
    if recents:
        for r in recents:
            lines.append(f"- （{r['kind']}）{r['title'] or r['text'][:24]}")
    else:
        lines.append("- （暂无）")
    lines.append("")
    return "\n".join(lines)


def build_promises_md(store) -> str:
    lines = [f"# 承诺台账（自动生成 · 最后更新 {util.now_str()}）", ""]
    rows = store.conn.execute(
        """SELECT * FROM memories WHERE status='active' AND kind='promise'
           ORDER BY ts DESC LIMIT 30""",
    ).fetchall()
    if rows:
        for r in rows:
            lines.append(f"- [ ] {r['text']}（{r['ts'][:10]}，id={r['id']}）")
    else:
        lines.append("- （台账为空）")
    lines.append("")
    lines.append("（办完一条：`eai done <id>` 销账；条目仍留档可查。）")
    return "\n".join(lines)


def _snapshot_versions(fname: str) -> None:
    src = core_dir() / fname
    if not src.exists():
        return
    vd = core_dir() / "versions"
    vd.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = vd / f"{fname.replace('.md', '')}-{stamp}.md"
    try:
        shutil.copy2(src, dst)
    except Exception:
        return
    olds = sorted(vd.glob(f"{fname.replace('.md', '')}-*.md"))
    for p in olds[:-30]:
        try:
            p.unlink()
        except Exception:
            pass


def refresh_persona(store) -> dict:
    _snapshot_versions("master.md")
    (core_dir() / "master.md").write_text(build_master_md(store), encoding="utf-8")
    (core_dir() / "promises.md").write_text(build_promises_md(store), encoding="utf-8")
    store.log_event("persona", None)
    return {"ok": True}


def identity_excerpt(max_lines: int = 12) -> str:
    """守则摘要：去掉大标题，保留小节标题与条目。"""
    p = core_dir() / "identity.md"
    if not p.exists():
        return ""
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("# ")]
    return "\n".join(lines[:max_lines])
