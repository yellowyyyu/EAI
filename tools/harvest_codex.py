#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EAI 采集器 · Codex 转录 → memory/inbox/

数据源（只读，绝不改动原件、不外传）：
    ~/.codex/sessions/<年>/<月>/<日>/rollout-*.jsonl   （主数据源）
    ~/.codex/history.jsonl                             （兜底：sessions/ 不可用时）

实测字段（2026-10-14 抽样核实，28 份 rollout）：
    每行一条 JSON：{"timestamp": ISO-8601 UTC, "ordinal": n, "type": ..., "payload": {...}}
    - type=="session_meta"：payload.session_id / payload.cwd（会话被续开时同一文件
      会出现多条 session_meta，session_id 相同）
    - type=="response_item" 且 payload.type=="message"：
        role=="user"      → content 为 [{type:"input_text", text:…}]，
                            含人打的字，也含 <environment_context> 等包装
        role=="assistant" → content 为 [{type:"output_text", text:…}]
    - type=="event_msg" / "turn_context" / "world_state" 等：无人类发言，跳过
    - 续开的会话会写出新的 rollout 文件（同一 session_id）→ 按 session_id 归并，
      用 (时间戳, 文本) 去重。

history.jsonl 每行：{"session_id": …, "ts": epoch 秒, "text": …}，只有用户发言、
没有 cwd 和助手回复，仅作兜底（项目名记 unknown）。

过滤规则与 Claude 侧一致：只收"人打的字"，跳过 "<" 开头包装、
"[Request interrupted…]"、压缩续写摘要；拿不准就跳过，宁缺毋滥。

输出：
    memory/inbox/codex/<项目名>/<会话id>.md
    memory/inbox/index.jsonl（追加一行；sha1 幂等）

用法（Windows 中文环境务必带 PYTHONUTF8=1）：
    python tools/harvest_codex.py --dry-run
    python tools/harvest_codex.py --limit 5 --since 2026-09-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

SOURCE = "codex"
DEFAULT_ROOT = Path.home() / ".codex"
DEFAULT_INBOX = Path(__file__).resolve().parent.parent / "memory" / "inbox"

USER_TRUNC = 400
TAIL_TRUNC = 600
ELLIPSIS = "…"

_TEXT_BLOCK_TYPES = ("input_text", "text", "output_text")
_WRAPPER_PREFIXES = ("<",)
_WRAPPER_EXACT = (
    "[Request interrupted by user",
    "This session is being continued from a previous conversation",
)
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")


# ---------------------------------------------------------------- 小工具

def _norm_text(text: str) -> str:
    return _WS.sub(" ", text.replace("　", " ")).strip()


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + ELLIPSIS


def _is_wrapper(text: str) -> bool:
    if text.startswith(_WRAPPER_PREFIXES):
        return True
    return any(text.startswith(p) for p in _WRAPPER_EXACT)


def _parse_iso(ts) -> "dt.datetime | None":
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

def _payload_text(payload: dict) -> "str | None":
    """response_item/message 的 content 文本拼接；没有文本块返回 None。"""
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in _TEXT_BLOCK_TYPES \
                and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts) if parts else None


def _human_text(payload: dict) -> "str | None":
    """role=="user" 的 message → "人打的字"，否则 None。"""
    raw = _payload_text(payload)
    if raw is None:
        return None
    text = _norm_text(raw)
    if not text or _is_wrapper(text):
        return None
    return _clip(text, USER_TRUNC)


def _assistant_text(payload: dict) -> "str | None":
    raw = _payload_text(payload)
    if raw is None:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def parse_rollout(path: Path) -> "dict | None":
    """解析一份 rollout 文件 → {session_id, cwd, users, tail}；无 session_meta 返回 None。"""
    session_id = None
    cwd = ""
    users = []   # [{"ts": datetime|None, "text": str}]
    tail = None
    prev_ts = None

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
            kind = obj.get("type")
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            ts = _parse_iso(obj.get("timestamp"))
            if kind == "session_meta":
                if session_id is None and payload.get("session_id"):
                    session_id = str(payload["session_id"])
                if not cwd and payload.get("cwd"):
                    cwd = str(payload["cwd"])
            elif kind == "turn_context":
                if not cwd and payload.get("cwd"):
                    cwd = str(payload["cwd"])
                if ts is not None:
                    prev_ts = ts
            elif kind == "response_item" and payload.get("type") == "message":
                role = payload.get("role")
                if role == "user":
                    text = _human_text(payload)
                    if text is not None:
                        users.append({"ts": ts or prev_ts, "text": text})
                elif role == "assistant":
                    text = _assistant_text(payload)
                    if text:
                        tail = text
                if ts is not None:
                    prev_ts = ts

    if session_id is None:
        return None
    return {"session_id": session_id, "cwd": cwd, "users": users, "tail": tail}


def parse_history(path: Path) -> "dict | None":
    """兜底：history.jsonl → 按 session_id 归并的会话记录（无 cwd、无收尾）。"""
    groups = {}
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            sid = obj.get("session_id")
            raw = obj.get("text")
            if not sid or not isinstance(raw, str):
                continue
            text = _norm_text(raw)
            if not text or _is_wrapper(text):
                continue
            ts = None
            if isinstance(obj.get("ts"), (int, float)):
                try:
                    ts = dt.datetime.fromtimestamp(float(obj["ts"]), tz=dt.timezone.utc).astimezone()
                except (OverflowError, OSError, ValueError):
                    ts = None
            groups.setdefault(str(sid), []).append({"ts": ts, "text": _clip(text, USER_TRUNC)})
    return groups or None


# ---------------------------------------------------------------- 归并

def merge_groups(rollouts):
    """把多份 rollout 记录按 session_id 归并（续开会话散在多个文件里）。"""
    groups = {}
    for rec in rollouts:
        g = groups.setdefault(rec["session_id"], {
            "session_id": rec["session_id"], "cwd": "", "users": [], "tails": [],
        })
        if not g["cwd"] and rec["cwd"]:
            g["cwd"] = rec["cwd"]
        for msg in rec["users"]:
            g["users"].append(msg)
        if rec["tail"]:
            g["tails"].append(rec["tail"])

    merged = []
    for g in groups.values():
        users = g["users"]
        # 稳定排序：有时间的按本地时间，无时间的保持原有相对位置
        users = sorted(users, key=lambda m: m["ts"].timestamp() if m["ts"] else 0.0)
        deduped, seen = [], set()
        for msg in users:
            key = (msg["ts"].isoformat() if msg["ts"] else "", msg["text"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(msg)
        if not deduped:
            continue
        merged.append({
            "source": SOURCE,
            "session_id": g["session_id"],
            "cwd": g["cwd"],
            "project": _project_from_cwd(g["cwd"]),
            "date": deduped[0]["ts"].date().isoformat() if deduped[0]["ts"] else dt.date.today().isoformat(),
            "messages": deduped,
            "tail": _clip(g["tails"][-1], TAIL_TRUNC) if g["tails"] else None,
        })
    return merged


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
        "rollout_files": 0, "scanned": 0, "harvested": 0,
        "skipped_dup": 0, "skipped_empty": 0, "skipped_since": 0,
        "failed": 0, "limit_hit": False, "root_missing": False, "fallback": False,
    }
    if not root.is_dir():
        stats["root_missing"] = True
        err(f"[{SOURCE}] 找不到数据目录：{root}")
        return stats

    index_path = inbox / "index.jsonl"
    seen = load_index_sha1(index_path)

    # 主数据源：sessions/ 下的 rollout 文件
    sessions_dir = root / "sessions"
    rollout_files = sorted(sessions_dir.rglob("*.jsonl")) if sessions_dir.is_dir() else []
    stats["rollout_files"] = len(rollout_files)

    records = []
    for path in rollout_files:
        try:
            rec = parse_rollout(path)
        except OSError as exc:
            stats["failed"] += 1
            err(f"[{SOURCE}] 读取失败 {path}：{exc}")
            continue
        except Exception as exc:  # noqa: BLE001 —— 单份失败不影响整批
            stats["failed"] += 1
            err(f"[{SOURCE}] 解析失败 {path}：{exc!r}")
            continue
        if rec is not None:
            records.append(rec)

    sessions = merge_groups(records)
    # 有 rollout 但一句人话都没有的会话，计入"无有效发言"
    stats["skipped_empty"] = len({r["session_id"] for r in records}
                                 - {s["session_id"] for s in sessions})
    if not sessions:
        # 兜底：history.jsonl（只有用户发言，项目名 unknown）
        stats["fallback"] = True
        history = parse_history(root / "history.jsonl")
        if not history:
            err(f"[{SOURCE}] 未找到可用的会话数据（{sessions_dir} 与 history.jsonl 均不可用），跳过")
            return stats
        log(f"[{SOURCE}] sessions/ 不可用，改用 history.jsonl 兜底（无 cwd 与助手收尾）")
        for sid, users in history.items():
            users = sorted(users, key=lambda m: m["ts"].timestamp() if m["ts"] else 0.0)
            sessions.append({
                "source": SOURCE,
                "session_id": sid,
                "cwd": "",
                "project": "unknown",
                "date": users[0]["ts"].date().isoformat() if users[0]["ts"] else dt.date.today().isoformat(),
                "messages": users,
                "tail": None,
            })

    stats["scanned"] = len(sessions)
    for rec in sessions:
        if limit is not None and stats["harvested"] >= limit:
            stats["limit_hit"] = True
            break
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
                err(f"[{SOURCE}] 写入失败 {rec['session_id']}：{exc}")
                continue
        stats["harvested"] += 1

    if stats["fallback"]:
        origin = f"history.jsonl 兜底 → 会话 {stats['scanned']} 个"
    else:
        origin = f"sessions/ {stats['rollout_files']} 个文件 → 会话 {stats['scanned']} 个（续开已归并）"
    mode = "dry-run，未写入任何文件" if dry_run else "已写入"
    log(
        f"[{SOURCE}] 采集完成：{origin}；"
        f"成功 {stats['harvested']}，跳过 {stats['skipped_dup'] + stats['skipped_empty'] + stats['skipped_since']}"
        f"（重复 {stats['skipped_dup']} / 无有效发言 {stats['skipped_empty']} / 早于 --since {stats['skipped_since']}），"
        f"失败 {stats['failed']}；{mode}"
    )
    if stats["limit_hit"]:
        log(f"[{SOURCE}] 已达 --limit {limit}，提前停止")
    if not dry_run:
        log(f"[{SOURCE}] 输出目录：{inbox}")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EAI · Codex 转录采集器")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--limit", type=int, default=None, help="本次最多采集 N 个会话")
    parser.add_argument("--since", default=None, help="只收该日期（YYYY-MM-DD）及以后的会话")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="数据目录（默认 ~/.codex）")
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
