#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EAI 采集器 · Claude Code 转录 → memory/inbox/

数据源（只读，绝不改动原件、不外传）：
    ~/.claude/projects/<项目slug>/<会话id>.jsonl

实测字段（2026-10-14 抽样核实，91 份转录）：
    每行一条 JSON。type=="user" 的行：message.content 为字符串，
    或块数组（块类型 text / tool_result / image…）；timestamp 为
    ISO-8601 UTC；cwd、sessionId、isMeta 在行顶层。
    type=="assistant" 的行：message.content 为块数组（text / thinking / tool_use）。

只收"人打的字"，以下一律跳过（宁缺毋滥）：
    - isMeta / isSidechain 行
    - 含 tool_result、image 等非纯 text 块的消息
    - 以 "<" 开头的系统包装（<command-name> 斜杠命令、<local-command-*>、
      <task-notification>、<environment_context> 等）
    - "[Request interrupted by user…]" 中断标记
    - "This session is being continued from a previous conversation…" 压缩续写摘要

输出：
    memory/inbox/claude/<项目名>/<会话id>.md    （Human 可读，单条发言截断 400 字）
    memory/inbox/index.jsonl                    （追加一行；sha1 幂等）

用法（Windows 中文环境务必带 PYTHONUTF8=1）：
    python tools/harvest_claude.py --dry-run
    python tools/harvest_claude.py --limit 5 --since 2026-09-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SOURCE = "claude"
DEFAULT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_INBOX = Path(__file__).resolve().parent.parent / "memory" / "inbox"

USER_TRUNC = 400      # 单条发言截断字数
TAIL_TRUNC = 600      # 会话收尾截断字数
ELLIPSIS = "…"

# 系统包装文本前缀（拿不准就跳过）
_WRAPPER_PREFIXES = ("<",)
_WRAPPER_EXACT = (
    "[Request interrupted by user",
    "This session is being continued from a previous conversation",
)
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")


# ---------------------------------------------------------------- 小工具

def _norm_text(text: str) -> str:
    """把多行压成单行（列表项要一行一条）。"""
    return _WS.sub(" ", text.replace("　", " ")).strip()


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + ELLIPSIS


def _is_wrapper(text: str) -> bool:
    if text.startswith(_WRAPPER_PREFIXES):
        return True
    if text.startswith("/loop"):
        return True  # 自唤醒心跳提示词，不是人类发言（2026-10-15 加）
    return any(text.startswith(p) for p in _WRAPPER_EXACT)


def _parse_iso(ts) -> "dt.datetime | None":
    """ISO-8601（通常带 Z）→ 本地时区的 aware datetime；解析不了返回 None。"""
    if not isinstance(ts, str) or not ts.strip():
        return None
    raw = ts.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone()


def _safe_name(name: str) -> str:
    """项目名可安全当文件夹名用。"""
    cleaned = _INVALID_NAME.sub("_", name or "").strip().rstrip(". ")
    return cleaned or "unknown"


def _project_from_cwd(cwd: str) -> str:
    if not cwd:
        return "unknown"
    try:
        base = Path(cwd).name
    except (OSError, ValueError):
        base = ""
    return _safe_name(base)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------- 解析

def _user_text(obj: dict) -> "str | None":
    """从一条 type=="user" 的转录行里提取"人打的字"；不是人打的就返回 None。"""
    if obj.get("isMeta") or obj.get("isSidechain"):
        return None
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "text"):
                return None  # tool_result / image / 未知块：整条跳过
            text = block.get("text")
            if not isinstance(text, str):
                return None
            parts.append(text)
        raw = "\n".join(parts)
    else:
        return None
    text = _norm_text(raw)
    if not text or _is_wrapper(text):
        return None
    return _clip(text, USER_TRUNC)


def _assistant_text(obj: dict) -> "str | None":
    """助手回复的纯文本内容（保留换行），用于"会话收尾"。"""
    if obj.get("isSidechain"):
        return None
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        raw = "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
            and isinstance(b.get("text"), str)
        )
    else:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def parse_session(path: Path) -> "dict | None":
    """解析一份转录 → 会话记录；没有一句人话返回 None。"""
    session_id = None
    cwd = ""
    messages = []   # [{"ts": datetime|None, "text": str}]
    tail = None     # 最后一条有内容的助手回复

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # 坏行跳过，不报错
            if not isinstance(obj, dict):
                continue
            if session_id is None and obj.get("sessionId"):
                session_id = str(obj["sessionId"])
            if not cwd and obj.get("cwd"):
                cwd = str(obj["cwd"])
            kind = obj.get("type")
            if kind == "user":
                text = _user_text(obj)
                if text is not None:
                    messages.append({"ts": _parse_iso(obj.get("timestamp")), "text": text})
            elif kind == "assistant":
                text = _assistant_text(obj)
                if text:
                    tail = text

    if not messages:
        return None

    sid = session_id or path.stem
    if tail:
        tail = _clip(tail, TAIL_TRUNC)
    date = _date_of(messages, path)
    return {
        "source": SOURCE,
        "session_id": sid,
        "cwd": cwd,
        "project": _project_from_cwd(cwd),
        "date": date,
        "messages": messages,
        "tail": tail,
    }


def _date_of(messages, path: Path) -> str:
    for msg in messages:
        if msg["ts"] is not None:
            return msg["ts"].date().isoformat()
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return dt.date.today().isoformat()


# ---------------------------------------------------------------- 渲染 / 落盘

def render_md(rec: dict) -> str:
    def hhmm(ts) -> str:
        return ts.strftime("%H:%M") if ts is not None else "--:--"

    first = rec["messages"][0]["ts"]
    last = rec["messages"][-1]["ts"]
    lines = [
        f"# {rec['project']} · {rec['date']} · {rec['session_id'][:8]}",
        f"- 工作目录：{rec['cwd'] or '未知'}",
        f"- 时段：{hhmm(first)} → {hhmm(last)}；用户发言 {len(rec['messages'])} 条",
        "",
        "## 用户发言",
    ]
    for msg in rec["messages"]:
        lines.append(f"- ({hhmm(msg['ts'])}) {msg['text']}")
    if rec.get("tail"):
        lines += ["", "## 会话收尾", rec["tail"]]
    return "\n".join(lines) + "\n"


def load_index_sha1(index_path: Path) -> set:
    seen = set()
    if not index_path.is_file():
        return seen
    with open(index_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            sha = entry.get("sha1") if isinstance(entry, dict) else None
            if sha:
                seen.add(str(sha))
    return seen


def append_index(index_path: Path, entry: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_md(inbox: Path, rec: dict, md: str) -> str:
    sha8 = _sha1(md)[:8]  # 文件名带内容指纹：同一会话续写产生新版本文件，不覆盖旧版（评审 M8）
    rel = f"{SOURCE}/{rec['project']}/{rec['session_id']}.{sha8}.md"
    out = inbox / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    return rel


# ---------------------------------------------------------------- 主流程

def harvest(root, inbox, dry_run=False, limit=None, since=None, log=print, err=print) -> dict:
    root = Path(root)
    inbox = Path(inbox)
    stats = {
        "scanned": 0, "sessions": 0, "harvested": 0,
        "skipped_dup": 0, "skipped_empty": 0, "skipped_since": 0,
        "failed": 0, "limit_hit": False, "root_missing": False,
    }
    if not root.is_dir():
        stats["root_missing"] = True
        err(f"[{SOURCE}] 找不到转录目录：{root}")
        return stats

    index_path = inbox / "index.jsonl"
    seen = load_index_sha1(index_path)
    files = sorted(p for p in root.glob("*/*.jsonl") if p.is_file())
    stats["scanned"] = len(files)

    for path in files:
        if limit is not None and stats["harvested"] >= limit:
            stats["limit_hit"] = True
            break
        try:
            rec = parse_session(path)
        except OSError as exc:
            stats["failed"] += 1
            err(f"[{SOURCE}] 读取失败 {path}：{exc}")
            continue
        except Exception as exc:  # noqa: BLE001 —— 单份失败不影响整批
            stats["failed"] += 1
            err(f"[{SOURCE}] 解析失败 {path}：{exc!r}")
            continue
        if rec is None:
            stats["skipped_empty"] += 1
            continue
        stats["sessions"] += 1
        if since is not None and rec["date"] < since:
            stats["skipped_since"] += 1
            continue
        md = render_md(rec)
        sha = _sha1(md)
        if sha in seen:
            stats["skipped_dup"] += 1
            continue
        seen.add(sha)
        if not dry_run:
            try:
                rel = write_md(inbox, rec, md)
                append_index(index_path, {
                    "path": rel,
                    "source": SOURCE,
                    "session_id": rec["session_id"],
                    "project": rec["project"],
                    "cwd": rec["cwd"],
                    "date": rec["date"],
                    "sha1": sha,
                    "n_user": len(rec["messages"]),
                    "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                })
            except OSError as exc:
                stats["failed"] += 1
                err(f"[{SOURCE}] 写入失败 {path}：{exc}")
                continue
        stats["harvested"] += 1

    mode = "dry-run，未写入任何文件" if dry_run else "已写入"
    log(
        f"[{SOURCE}] 采集完成：扫描 {stats['scanned']} 份转录 → 成功 {stats['harvested']}，"
        f"跳过 {stats['skipped_dup'] + stats['skipped_empty'] + stats['skipped_since']}"
        f"（重复 {stats['skipped_dup']} / 无有效发言 {stats['skipped_empty']} / 早于 --since {stats['skipped_since']}），"
        f"失败 {stats['failed']}；{mode}"
    )
    if stats["limit_hit"]:
        log(f"[{SOURCE}] 已达 --limit {limit}，提前停止")
    if not dry_run:
        log(f"[{SOURCE}] 输出目录：{inbox}")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EAI · Claude 转录采集器")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--limit", type=int, default=None, help="本次最多采集 N 个会话")
    parser.add_argument("--since", default=None, help="只收该日期（YYYY-MM-DD）及以后的会话")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="转录目录（默认 ~/.claude/projects）")
    parser.add_argument("--inbox", default=str(DEFAULT_INBOX), help="输出目录（默认 memory/inbox）")
    args = parser.parse_args(argv)

    since = None
    if args.since:
        try:
            since = dt.date.fromisoformat(args.since).isoformat()
        except ValueError:
            print(f"[{SOURCE}] --since 日期格式不对：{args.since}（应为 YYYY-MM-DD）", file=sys.stderr)
            return 1
    if args.limit is not None and args.limit < 0:
        print(f"[{SOURCE}] --limit 不能为负数", file=sys.stderr)
        return 1

    stats = harvest(
        args.root, args.inbox,
        dry_run=args.dry_run, limit=args.limit, since=since,
        err=lambda msg: print(msg, file=sys.stderr),
    )
    return 1 if stats["root_missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
