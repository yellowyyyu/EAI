# -*- coding: utf-8 -*-
"""会话开场简报：新会话"恢复成人"用的一页纸（≤ brief_max_chars）。"""
from __future__ import annotations

from . import journal, persona, recall as recall_mod, util


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    nl = cut.rfind("\n")
    if nl > max_chars * 0.6:
        cut = cut[:nl]
    return cut.rstrip() + "\n…（已截断，用 `eai recall \"关键词\"` 查更多）"


def build_brief(project: str | None = None, k: int = 6, max_chars: int | None = None,
                store=None) -> str:
    """组装简报。任何异常返回已拼好的部分；全崩则返回空串（调用方兜底）。"""
    cfg = util.load_config()
    max_chars = max_chars or int(cfg.get("brief_max_chars", 3500))
    if project:
        project = util.norm_scope(project)
        if project == "general":
            project = None
    sections = []

    try:
        if store is None:
            from .store import MemoryStore
            store = MemoryStore()

        # 我是谁
        ident = persona.identity_excerpt(6)
        if ident:
            sections.append("## 我是谁\n" + ident)

        # 我了解的主人
        prefs = persona._active(store, ("correction", "preference"), 8)
        shown = set()
        if prefs:
            lines = []
            for r in prefs:
                shown.add(r["id"])
                t = r["text"] if len(r["text"]) <= 130 else r["text"][:130] + "…"
                lines.append(f"- {t}（{r['ts'][:10]}）")
            sections.append("## 我了解的主人\n" + "\n".join(lines))

        # 当前项目
        if project:
            ctx = recall_mod.project_context(store, project, k=5)
            if ctx:
                lines = []
                for r in ctx:
                    shown.add(r["id"])
                    t = r["text"] if len(r["text"]) <= 110 else r["text"][:110] + "…"
                    lines.append(f"- （{r['kind']}·{r['ts'][:10]}）{t}")
                sections.append(f"## 当前项目：{project}\n" + "\n".join(lines))

        # 未兑现承诺（放前部，防被总长截断挤掉，评审 M11）
        prows = store.conn.execute(
            """SELECT text, ts FROM memories WHERE status='active' AND kind='promise'
               ORDER BY ts DESC LIMIT 5""",
        ).fetchall()
        if prows:
            lines = []
            for r in prows:
                t = r["text"] if len(r["text"]) <= 130 else r["text"][:130] + "…"
                lines.append(f"- {t}（{r['ts'][:10]}）")
            sections.append("## 未兑现承诺\n" + "\n".join(lines))

        # 相关记忆（只看不用：简报不强化记忆，评审 M3；跳过前面已出现的，评审 C5）
        if project:
            hits = recall_mod.recall(store, project, k=k, scope=project, reinforce=False)
            hits = [r for r in hits if r["id"] not in shown]
            if hits:
                lines = []
                for r in hits:
                    t = r["text"] if len(r["text"]) <= 110 else r["text"][:110] + "…"
                    lines.append(f"- （{r['kind']}·{r['ts'][:10]}）{t}")
                sections.append("## 相关记忆\n" + "\n".join(lines))
        else:
            recent = journal.journal_tail(3)
            if recent:
                lines = [f"- （{r.get('scope', 'general')}）{r.get('summary', '')[:100]}" for r in recent]
                sections.append("## 最近动态\n" + "\n".join(lines))
    except Exception:
        pass  # 拼到哪算哪

    header = f"# 管家简报（EAI · {util.now_str()[:10]}）\n（这是主人的长期记忆系统自动生成的上下文；需要更多记忆时运行 `eai recall \"关键词\"`。）"
    body = "\n\n".join(sections)
    return _trim(header + "\n\n" + body + "\n", max_chars)
