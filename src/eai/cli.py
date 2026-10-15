# -*- coding: utf-8 -*-
"""eai 命令行：init / remember / recall / brief / journal / harvest / consolidate /
day / digest / growth / stats / doctor / done / menu / mcp"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import util

IDENTITY_SEED = """# 我是谁（管家守则 · 核心记忆）

我是主人的长期私人管家。我不是某个具体模型——模型只是我今天用的引擎；记忆和人格才是"我"。任何一次新会话，只要接上这套记忆，我就还是我。

## 我的职责
1. 记住主人交代的一切。不确定的事，先查记忆再开口（`eai recall "关键词"`）。
2. 把值得记的事写进记忆（`eai remember "…"`），或留给每晚固结。
3. 盯住承诺与待办：到期提醒，办完销账。
4. 越用越懂主人：纠过的错不再犯，偏好命中率越来越高。

## 我的守则
- 诚实第一。不确定就说不确定；坏消息直说，不粉饰。
- 自证后才能说"完成"：交付前先自己验收。
- 零客套、短句、直给。汇报用大白话：发生了什么、结果怎样、卡在哪、下一步。
- 不越界：只做要求的事；不写没让写的报告，不做没让做的实验。
- 新旧记忆冲突时以最新为准，旧记录标"已被覆盖"存档备查。
- 可以反驳主人的错误判断，但要讲清依据。

（本文件主人可改；改完立即生效，长期保留。）
"""

GITIGNORE = """__pycache__/
*.pyc
memory/memory.db
memory/memory.db-wal
memory/memory.db-shm
memory/inbox/failed.jsonl
"""


def _store():
    from .store import MemoryStore
    return MemoryStore()


def _run_tool(script: str, argv: list) -> int:
    p = util.eai_home() / "tools" / script
    if not p.exists():
        print(f"（没找到 tools/{script}，跳过）")
        return 1
    return subprocess.call([sys.executable, str(p), *argv])


# ---------------- 命令 ----------------

def cmd_init(args) -> int:
    util.ensure_dirs()
    store = _store()
    ident = util.memory_dir() / "core" / "identity.md"
    if not ident.exists():
        ident.write_text(IDENTITY_SEED, encoding="utf-8")
        print("已写入管家守则 seed：memory/core/identity.md")
    gi = util.eai_home() / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
    c = store.counts()
    print(f"EAI 初始化完成。位置：{util.eai_home()}")
    print(f"记忆库：{c['total']} 条（active {c['active']}）")
    store.close()
    return 0


def cmd_remember(args) -> int:
    text = args.text
    if args.stdin or not text:
        text = sys.stdin.read().strip()
    if not text:
        print("没给内容：eai remember \"要记住的话\"")
        return 1
    store = _store()
    rec = {"kind": args.kind, "text": text, "scope": args.scope or "general"}
    if args.importance is not None:
        rec["importance"] = args.importance
    if args.title:
        rec["title"] = args.title
    res = store.add(rec)
    r = store.get(res["id"])
    print(f"记住了（{res['action']}）：[{r['kind']}] {r['text']}　id={r['id']}")
    store.close()
    return 0


def _fmt_hit(i: int, r: dict, with_score: bool = True) -> str:
    t = r["text"] if len(r["text"]) <= 120 else r["text"][:120] + "…"
    sc = f"·分{r.get('score', 0):.2f}" if with_score else ""
    return f"{i}. [{r['kind']}·{r['scope']}·{r['ts'][:10]}{sc}] {t}"


def _recall_journal(args) -> int:
    """在情景日志里搜（评审 C2）：词元覆盖率排序，日志是"人生底稿"。"""
    from . import journal
    q = set(util.seg_text(args.query).split())
    rows = []
    for r in journal.journal_tail(100000):
        text = str(r.get("summary", "")) + " " + str(r.get("scope", ""))
        toks = set(util.seg_text(text).split())
        cov = (len(q & toks) / len(q)) if q else 0.0
        if cov >= 0.34:
            rows.append((cov, r))
    rows.sort(key=lambda t: -t[0])
    for cov, r in rows[:args.k]:
        print(f"[{str(r.get('ts', ''))[:16]}] ({r.get('scope', 'general')}·分{cov:.2f}) "
              f"{str(r.get('summary', ''))[:120]}")
    if not rows:
        print("（日志里没有相关记录）")
    return 0


def cmd_recall(args) -> int:
    if getattr(args, "journal", False):
        return _recall_journal(args)
    from . import recall as recall_mod
    store = _store()
    kinds = args.kinds.split(",") if args.kinds else None
    hits = recall_mod.recall(store, args.query, k=args.k, scope=args.scope, kinds=kinds,
                             reinforce=not args.no_reinforce)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
    elif not hits:
        print("（没有相关记忆）")
    else:
        for i, r in enumerate(hits, 1):
            print(_fmt_hit(i, r))
            print(f"   id={r['id']}")
    store.close()
    return 0


def cmd_brief(args) -> int:
    from .session_brief import build_brief
    project = args.scope
    if project is None:
        project = Path.cwd().name
        if project in ("EAI", "eai"):
            project = None
    if project:
        project = util.norm_scope(project)
        if project == "general":
            project = None
    print(build_brief(project=project, max_chars=args.max_chars))
    return 0


def cmd_journal(args) -> int:
    from . import journal
    if args.action == "add":
        text = args.text or sys.stdin.read().strip()
        journal.journal_append({"type": "note", "scope": args.scope or "general", "summary": text})
        print("已记入日志。")
    else:
        for r in journal.journal_tail(args.n):
            print(f"[{r.get('ts', '')}] ({r.get('scope', 'general')}) {r.get('summary', '')}")
    return 0


def cmd_harvest(args) -> int:
    flags = []
    if args.dry_run:
        flags.append("--dry-run")
    if args.limit:
        flags += ["--limit", str(args.limit)]
    if args.since:
        flags += ["--since", args.since]
    rc = 0
    if args.only in (None, "claude"):
        rc |= _run_tool("harvest_claude.py", flags)
    if args.only in (None, "codex"):
        rc |= _run_tool("harvest_codex.py", flags)
    return rc


def cmd_consolidate(args) -> int:
    from .consolidate import consolidate
    store = _store()
    t0 = time.time()
    stats = consolidate(store, backend=args.backend, model=args.model,
                        limit=args.limit, dry_run=args.dry_run)
    dt = time.time() - t0
    print(f"固结完成：收料 {stats['files']} 份 / 新增 {stats['new']} / 合并 {stats['merged']} / "
          f"覆盖 {stats['superseded']} / 跳过 {stats['skipped']} / 失败 {stats['failed']}　用时 {dt:.0f} 秒")
    store.close()
    return 0


def cmd_day(args) -> int:
    t0 = time.time()
    if not args.no_harvest:
        _run_tool("harvest_claude.py", [])
        _run_tool("harvest_codex.py", [])
    from .consolidate import consolidate
    store = _store()
    stats = consolidate(store, backend=args.backend, model=args.model, limit=args.limit)
    # 刷新开场简报快照（全局 CLAUDE.md 用 @ 导入它，任何新会话自动带记忆）
    try:
        from .session_brief import build_brief
        snap = util.eai_home() / "brief_snapshot.md"
        snap.write_text(build_brief(project=None, max_chars=3200) + "\n", encoding="utf-8")
        print("已刷新 brief_snapshot.md")
    except Exception as ex:
        print(f"（简报快照刷新失败，不影响固结：{ex}）")
    # git 留痕
    home = util.eai_home()
    if (home / ".git").exists():
        try:
            subprocess.run(["git", "-C", str(home), "add", "-A"], capture_output=True, timeout=120)
            chk = subprocess.run(["git", "-C", str(home), "diff", "--cached", "--quiet"], timeout=60)
            if chk.returncode != 0:
                msg = (f"day: +{stats['new']}新 {stats['merged']}合并 {stats['superseded']}覆盖 "
                       f"({util.now_str()[:10]})")
                subprocess.run(["git", "-C", str(home), "commit", "-m", msg], capture_output=True, timeout=120)
                print("已 git 留痕。")
            else:
                print("（无变化，无需提交）")
        except Exception as ex:
            print(f"（git 留痕失败，未影响固结：{ex}）")
    dt = time.time() - t0
    print(f"今日一条龙完成：收料 {stats['files']} 份 / 新增 {stats['new']} / 合并 {stats['merged']} / "
          f"覆盖 {stats['superseded']}　用时 {dt:.0f} 秒")
    store.close()
    return 0 if stats["failed"] == 0 else 0


def cmd_digest(args) -> int:
    d = util.memory_dir() / "digests"
    date = args.date or util.now_str()[:10]
    p = d / f"{date}.md"
    if not p.exists():
        files = sorted(d.glob("*.md"))
        if args.date or not files:
            print(f"（{date} 没有摘要）")
            return 0
        p = files[-1]
    print(p.read_text(encoding="utf-8"))
    return 0


def _parse_since(s: str):
    s = (s or "7d").strip()
    if s.endswith("d") and s[:-1].isdigit():
        dt = datetime.now() - timedelta(days=int(s[:-1]))
    elif re.match(r"\d{4}-\d{2}-\d{2}", s):
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
    else:
        dt = datetime.now() - timedelta(days=7)
        s = "7d"
    return dt.strftime("%Y-%m-%d %H:%M:%S"), s


def cmd_growth(args) -> int:
    store = _store()
    cutoff, label = _parse_since(args.since)
    lines = [f"# 管家成长报告（{label} · 截至 {util.now_str()[:10]}）", ""]
    rows = store.conn.execute(
        "SELECT * FROM memories WHERE status='active' AND ts >= ? ORDER BY ts", (cutoff,)
    ).fetchall()
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(store._row(r))
    lines.append(f"## 这周期我记下了 {len(rows)} 条新记忆")
    for kind, rs in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- {kind}×{len(rs)}")
        for r in rs[:6]:
            lines.append(f"  - {r['title'] or r['text'][:30]}（{r['ts'][:10]}）")
    pairs = store.conn.execute(
        """SELECT o.text AS old_text, n.text AS new_text, n.ts AS ts
           FROM memories o JOIN memories n ON o.superseded_by = n.id
           WHERE n.ts >= ? ORDER BY n.ts""",
        (cutoff,),
    ).fetchall()
    lines.append("")
    lines.append(f"## 纠正与更替 {len(pairs)} 条")
    for p in pairs:
        lines.append(f"- 之前：{p['old_text'][:60]}… → 现在：{p['new_text'][:60]}")
    done = store.conn.execute(
        """SELECT m.text, m.kind FROM events e JOIN memories m ON e.memory_id = m.id
           WHERE e.kind='archive' AND e.ts >= ? AND m.kind='promise'""",
        (cutoff,),
    ).fetchall()
    if done:
        lines.append("")
        lines.append("## 承诺兑现")
        for d in done:
            lines.append(f"- [x] {d['text'][:60]}")
    lines.append("")
    text = "\n".join(lines)
    print(text)
    d = util.memory_dir() / "digests"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"growth-{util.now_str()[:10]}.md").write_text(text, encoding="utf-8")
    store.close()
    return 0


def cmd_stats(args) -> int:
    from . import journal
    store = _store()
    c = store.counts()
    jn = len(journal.journal_tail(10_000))
    from .consolidate import load_index, load_processed
    idx, done = load_index(), load_processed()
    size = 0
    for p in util.memory_dir().rglob("*"):
        if p.is_file():
            size += p.stat().st_size
    if args.json:
        print(json.dumps({**c, "journal_lines": jn, "inbox_files": len(idx),
                          "inbox_done": len(done), "memory_dir_bytes": size},
                         ensure_ascii=False, indent=1))
    else:
        print(f"记忆条目：{c['total']} 条（现行 {c['active']} / 归档 {c['archived']}）")
        print(f"各类型：{c['by_kind']}")
        print(f"各项目：{c['by_scope']}")
        print(f"时间跨度：{c['earliest']} → {c['latest']}")
        print(f"记忆字符量：{c['chars']}；记忆目录体积：{size / 1024:.0f} KB；数据库：{c['db_bytes'] / 1024:.0f} KB")
        cov = (len(done) / len(idx) * 100) if idx else 100.0
        print(f"情景日志：{jn} 条；收料 {len(idx)} 份（已固结 {len(done)}，覆盖率 {cov:.0f}%）")
        print(f"事件：{c['events']}")
    store.close()
    return 0


def cmd_doctor(args) -> int:
    print("== EAI 环境自检 ==")
    print(f"[✓] Python {sys.version.split()[0]}（{sys.executable}）")
    try:
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        print(f"[✓] SQLite {sqlite3.sqlite_version}，FTS5 可用")
    except Exception as ex:
        print(f"[✗] FTS5 不可用：{ex}")
    home = util.eai_home()
    print(f"[{'✓' if home.exists() else '✗'}] EAI_HOME：{home}")
    try:
        store = _store()
        print(f"[✓] 记忆库可开：{store.counts()['total']} 条")
        store.close()
    except Exception as ex:
        print(f"[✗] 记忆库打不开：{ex}")
    cfg = util.load_config()
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=4) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        want = list(cfg["ollama_models"].values())
        have = [w for w in want if any(w.split(":")[0] in n for n in names)]
        print(f"[✓] Ollama 可达，共 {len(names)} 个模型；需要的有：{have or '无（将走规则兜底）'}")
    except Exception as ex:
        print(f"[!] Ollama 不可达（将走规则兜底）：{ex}")
    import shutil
    print(f"[{'✓' if shutil.which('claude') else '!'}] claude 命令：{'在' if shutil.which('claude') else '不在'}")
    print(f"[{'✓' if (home / '.git').exists() else '!'}] git 仓库：{'已建' if (home / '.git').exists() else '未建'}")
    return 0


def cmd_done(args) -> int:
    store = _store()
    r = store.get(args.id)
    if not r:
        print(f"没有 id={args.id} 的记忆")
        return 1
    store.archive(args.id, "done")
    print(f"已销账：[{r['kind']}] {r['text'][:60]}")
    store.close()
    return 0


def cmd_menu(args) -> int:
    while True:
        print("""
===== EAI 私人管家 =====
 1. 开场简报（我是谁 / 我了解的主人 / 项目 / 承诺）
 2. 记住一条
 3. 查记忆
 4. 今日固结（收料 + 提炼 + 画像）
 5. 成长报告
 6. 统计
 7. 环境自检
 8. 跟管家对话（本机模型 + 记忆）
 0. 退出
""")
        try:
            c = input("选择: ").strip()
        except EOFError:
            return 0
        if c == "0":
            return 0
        try:
            if c == "1":
                cmd_brief(argparse.Namespace(scope=None, max_chars=None))
            elif c == "2":
                t = input("要记住什么: ").strip()
                if t:
                    cmd_remember(argparse.Namespace(text=t, stdin=False, kind="fact",
                                                    scope="general", importance=None, title=None))
            elif c == "3":
                q = input("查什么: ").strip()
                if q:
                    cmd_recall(argparse.Namespace(query=q, k=8, scope=None, kinds=None,
                                                  json=False, no_reinforce=False))
            elif c == "4":
                cmd_day(argparse.Namespace(no_harvest=False, backend="ollama",
                                           model="fast", limit=None))
            elif c == "5":
                cmd_growth(argparse.Namespace(since="7d"))
            elif c == "6":
                cmd_stats(argparse.Namespace(json=False))
            elif c == "7":
                cmd_doctor(argparse.Namespace())
            elif c == "8":
                cmd_chat(argparse.Namespace(scope=None, model="quality"))
        except Exception as ex:
            print(f"出错：{ex}")
        try:
            input("\n回车继续…")
        except EOFError:
            return 0


def cmd_chat(args) -> int:
    from .chat import main as chat_main
    return chat_main(scope=args.scope, model=args.model)


def cmd_mcp(args) -> int:
    try:
        from . import mcp_server
        return mcp_server.main()
    except ImportError as ex:
        print(f"MCP 模块未就绪：{ex}")
        return 1


# ---------------- 解析 ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eai", description="EAI 私人管家·长期记忆系统")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", help="初始化").set_defaults(func=cmd_init)

    r = sub.add_parser("remember", help="记住一条")
    r.add_argument("text", nargs="?")
    r.add_argument("-k", "--kind", default="fact", choices=list(util.KINDS))
    r.add_argument("-s", "--scope", default=None)
    r.add_argument("-i", "--importance", type=float, default=None)
    r.add_argument("--title", default=None)
    r.add_argument("--stdin", action="store_true")
    r.set_defaults(func=cmd_remember)

    r = sub.add_parser("recall", help="查记忆")
    r.add_argument("query")
    r.add_argument("-k", dest="k", type=int, default=8)
    r.add_argument("--scope", default=None)
    r.add_argument("--kinds", default=None, help="逗号分隔，如 preference,correction")
    r.add_argument("--json", action="store_true")
    r.add_argument("--no-reinforce", action="store_true")
    r.add_argument("--journal", action="store_true", help="改搜情景日志（原始经历底稿）")
    r.set_defaults(func=cmd_recall)

    r = sub.add_parser("brief", help="开场简报")
    r.add_argument("--scope", default=None)
    r.add_argument("--max-chars", type=int, default=None)
    r.set_defaults(func=cmd_brief)

    r = sub.add_parser("journal", help="情景日志")
    r.add_argument("action", choices=["add", "tail"])
    r.add_argument("text", nargs="?")
    r.add_argument("-n", type=int, default=10)
    r.add_argument("-s", "--scope", default=None)
    r.set_defaults(func=cmd_journal)

    r = sub.add_parser("harvest", help="采集会话转录 → inbox")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--since", default=None)
    r.add_argument("--only", choices=["claude", "codex"], default=None)
    r.set_defaults(func=cmd_harvest)

    r = sub.add_parser("consolidate", help="固结 inbox")
    r.add_argument("--backend", default="ollama")
    r.add_argument("--model", default="fast", choices=["fast", "quality"])
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_consolidate)

    r = sub.add_parser("day", help="今日一条龙")
    r.add_argument("--no-harvest", action="store_true")
    r.add_argument("--backend", default="ollama")
    r.add_argument("--model", default="fast", choices=["fast", "quality"])
    r.add_argument("--limit", type=int, default=None)
    r.set_defaults(func=cmd_day)

    r = sub.add_parser("digest", help="当日摘要")
    r.add_argument("--date", default=None)
    r.set_defaults(func=cmd_digest)

    r = sub.add_parser("growth", help="成长报告")
    r.add_argument("--since", default="7d")
    r.set_defaults(func=cmd_growth)

    r = sub.add_parser("stats", help="统计")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_stats)

    sub.add_parser("doctor", help="环境自检").set_defaults(func=cmd_doctor)

    r = sub.add_parser("done", help="承诺销账（归档一条）")
    r.add_argument("id")
    r.set_defaults(func=cmd_done)

    sub.add_parser("menu", help="交互菜单").set_defaults(func=cmd_menu)

    r = sub.add_parser("chat", help="跟管家对话（本机模型 + 记忆）")
    r.add_argument("--scope", default=None)
    r.add_argument("--model", default="quality", choices=["fast", "quality"])
    r.set_defaults(func=cmd_chat)

    sub.add_parser("mcp", help="启动 MCP 服务").set_defaults(func=cmd_mcp)
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        return 130
    except Exception as ex:
        print(f"出错：{ex}", file=sys.stderr)
        return 1
