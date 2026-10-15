#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_harvest.py · 采集器单元测试（标准库 unittest）

全部用临时目录 + 自造小 JSONL 样本，不依赖真实转录文件。

跑法（在 EAI 根目录）：
    PYTHONUTF8=1 python -m unittest discover -s tests -v
    PYTHONUTF8=1 python tests/test_harvest.py
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import harvest_claude  # noqa: E402
import harvest_codex   # noqa: E402


# ---------------------------------------------------------------- 造样本小工具

def claude_line(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def user_line(sid, cwd, ts, content, **extra) -> str:
    obj = {
        "parentUuid": None, "isSidechain": False, "type": "user",
        "message": {"role": "user", "content": content},
        "uuid": "u-" + ts, "timestamp": ts, "userType": "external",
        "entrypoint": "cli", "cwd": cwd, "sessionId": sid, "version": "2.1.116",
    }
    obj.update(extra)
    return claude_line(**obj)


def assistant_line(sid, cwd, ts, blocks) -> str:
    return claude_line(
        parentUuid=None, isSidechain=False, type="assistant",
        message={"role": "assistant", "content": blocks},
        uuid="a-" + ts, timestamp=ts, cwd=cwd, sessionId=sid, version="2.1.116",
    )


def local_date(iso_utc: str) -> str:
    """把样本里的 UTC 时间换算成本机时区日期（测试不绑定时区）。"""
    return dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone().date().isoformat()


def local_hhmm(iso_utc: str) -> str:
    return dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone().strftime("%H:%M")


def write_lines(path: Path, lines) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line + "\n")


CLAUDE_SID = "aaaa1111-2222-3333-4444-555566667777"
CLAUDE_CWD = r"C:\work\demo-project"


def make_claude_sample(slug_dir: Path) -> Path:
    """一份含各种该收/不该收形态的 Claude 转录。"""
    path = slug_dir / f"{CLAUDE_SID}.jsonl"
    lines = [
        # 非对话行：应被忽略
        claude_line(type="permission-mode", permissionMode="bypassPermissions", sessionId=CLAUDE_SID),
        claude_line(type="file-history-snapshot", messageId="m1", snapshot={}),
        # 人打的字（字符串）
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:00.000Z", "你好，看下这个文件"),
        # isMeta 系统包装
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:01.000Z",
                  "<local-command-caveat>Caveat: ...</local-command-caveat>", isMeta=True),
        # tool_result：跳过
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:02.000Z",
                  [{"type": "tool_result", "content": "result"}], toolUseResult={}),
        # 斜杠命令包装：跳过
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:03.000Z",
                  "<command-name>/clear</command-name>\n<command-message>clear</command-message>"),
        # 纯 text 块数组：收，多块拼一条
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:04.000Z",
                  [{"type": "text", "text": "第一行"}, {"type": "text", "text": "第二行"}]),
        # 中断标记：跳过
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:05.000Z",
                  [{"type": "text", "text": "[Request interrupted by user]"}]),
        # 压缩续写摘要：跳过
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:06.000Z",
                  "This session is being continued from a previous conversation that ran out of context. 摘要…"),
        # 空白：跳过
        user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:02:07.000Z", "   \n  "),
        # 助手：只有 text 的才算收尾；tool_use 的忽略
        assistant_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:03:00.000Z",
                       [{"type": "text", "text": "好的，我先看。"}]),
        assistant_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:04:00.000Z",
                       [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]),
        assistant_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T01:05:00.000Z",
                       [{"type": "text", "text": "最后一条回复。\n第二行。"}]),
    ]
    write_lines(path, lines)
    return path


class ClaudeParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "projects"
        self.slug = self.root / "C--work-demo-project"
        self.sample = make_claude_sample(self.slug)

    def test_parse_filters_and_extracts(self):
        rec = harvest_claude.parse_session(self.sample)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["session_id"], CLAUDE_SID)
        self.assertEqual(rec["cwd"], CLAUDE_CWD)
        self.assertEqual(rec["project"], "demo-project")
        self.assertEqual(rec["date"], local_date("2026-10-01T01:02:00.000Z"))
        texts = [m["text"] for m in rec["messages"]]
        self.assertEqual(texts, ["你好，看下这个文件", "第一行 第二行"])
        # 收尾 = 最后一条有内容的助手文本（保留换行）
        self.assertEqual(rec["tail"], "最后一条回复。\n第二行。")

    def test_render_md_format(self):
        md = harvest_claude.render_md(harvest_claude.parse_session(self.sample))
        first = md.splitlines()[0]
        self.assertEqual(first, f"# demo-project · {local_date('2026-10-01T01:02:00.000Z')} · {CLAUDE_SID[:8]}")
        self.assertIn(f"- 工作目录：{CLAUDE_CWD}", md)
        self.assertIn("用户发言 2 条", md)
        self.assertIn(f"- ({local_hhmm('2026-10-01T01:02:00.000Z')}) 你好，看下这个文件", md)
        self.assertIn("## 用户发言", md)
        self.assertIn("## 会话收尾", md)
        self.assertTrue(md.endswith("\n"))

    def test_single_message_truncated_to_400(self):
        long_text = "长" * 500
        path = self.slug / "bbbb1111-2222-3333-4444-555566667777.jsonl"
        write_lines(path, [user_line("bbbb1111-2222-3333-4444-555566667777",
                                     CLAUDE_CWD, "2026-10-01T01:00:00.000Z", long_text)])
        rec = harvest_claude.parse_session(path)
        stored = rec["messages"][0]["text"]
        self.assertEqual(len(stored), 401)  # 400 字 + 省略号
        self.assertTrue(stored.endswith("…"))

    def test_session_without_human_text_returns_none(self):
        path = self.slug / "cccc1111-2222-3333-4444-555566667777.jsonl"
        write_lines(path, [
            user_line("cccc1111-2222-3333-4444-555566667777", CLAUDE_CWD,
                      "2026-10-01T01:00:00.000Z", "<command-name>/exit</command-name>"),
        ])
        self.assertIsNone(harvest_claude.parse_session(path))

    def test_harvest_writes_and_is_idempotent(self):
        inbox = Path(self.tmp.name) / "inbox"
        stats = harvest_claude.harvest(self.root, inbox, dry_run=False,
                                       log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats["harvested"], 1)
        md_files = list((inbox / "claude" / "demo-project").glob(f"{CLAUDE_SID}.*.md"))
        self.assertEqual(len(md_files), 1)  # 文件名带内容指纹（评审 M8）
        md_path = md_files[0]
        index = inbox / "index.jsonl"
        entries = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertRegex(entry["path"], rf"claude/demo-project/{CLAUDE_SID}\.[0-9a-f]{{8}}\.md")
        self.assertEqual(entry["source"], "claude")
        self.assertEqual(entry["session_id"], CLAUDE_SID)
        self.assertEqual(entry["project"], "demo-project")
        self.assertEqual(entry["n_user"], 2)
        self.assertEqual(entry["sha1"], harvest_claude._sha1(
            md_path.read_text(encoding="utf-8")))
        # 再跑一遍：幂等，跳过
        stats2 = harvest_claude.harvest(self.root, inbox, dry_run=False,
                                        log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats2["harvested"], 0)
        self.assertEqual(stats2["skipped_dup"], 1)
        self.assertEqual(len(index.read_text(encoding="utf-8").splitlines()), 1)
        # 续写（评审 M8）：转录追加后重收 → 新版文件，不覆盖旧版、可再固结
        self.sample.write_text(
            self.sample.read_text(encoding="utf-8")
            + user_line(CLAUDE_SID, CLAUDE_CWD, "2026-10-01T02:00:00.000Z", "补充：加一条") + "\n",
            encoding="utf-8")
        harvest_claude.harvest(self.root, inbox, dry_run=False,
                               log=lambda *_: None, err=lambda *_: None)
        md_files2 = list((inbox / "claude" / "demo-project").glob(f"{CLAUDE_SID}.*.md"))
        self.assertEqual(len(md_files2), 2)
        # dry-run：不写任何东西
        inbox2 = Path(self.tmp.name) / "inbox2"
        stats3 = harvest_claude.harvest(self.root, inbox2, dry_run=True,
                                        log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats3["harvested"], 1)
        self.assertFalse(inbox2.exists())

    def test_since_and_limit(self):
        # 再造一份更早的会话
        old_sid = "dddd1111-2222-3333-4444-555566667777"
        write_lines(self.slug / f"{old_sid}.jsonl",
                    [user_line(old_sid, CLAUDE_CWD, "2026-09-01T01:00:00.000Z", "旧会话")])
        inbox = Path(self.tmp.name) / "inbox"
        stats = harvest_claude.harvest(self.root, inbox, dry_run=True,
                                       since="2026-09-15",
                                       log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats["harvested"], 1)          # 只剩 10-01 那份
        self.assertEqual(stats["skipped_since"], 1)
        stats2 = harvest_claude.harvest(self.root, inbox, dry_run=True, limit=1,
                                        log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats2["harvested"], 1)
        self.assertTrue(stats2["limit_hit"])

    def test_missing_root_is_reported_not_crash(self):
        stats = harvest_claude.harvest(Path(self.tmp.name) / "nope",
                                       Path(self.tmp.name) / "inbox",
                                       log=lambda *_: None, err=lambda *_: None)
        self.assertTrue(stats["root_missing"])
        self.assertEqual(stats["harvested"], 0)


class ClaudeCliTests(unittest.TestCase):
    def test_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            make_claude_sample(root / "slug")
            inbox = Path(tmp) / "inbox"
            env = dict(os.environ, PYTHONUTF8="1")
            proc = subprocess.run(
                [sys.executable, str(TOOLS / "harvest_claude.py"),
                 "--dry-run", "--root", str(root), "--inbox", str(inbox)],
                capture_output=True, text=True, encoding="utf-8", env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("成功 1", proc.stdout)
            self.assertFalse(inbox.exists())


# ---------------------------------------------------------------- Codex 样本

CODEX_SID = "01a05861-a0d8-7da1-a35c-3b5e14a95a0b"
CODEX_CWD = r"C:\work\demo-flash"


def codex_line(ts, type_, payload) -> str:
    return json.dumps({"timestamp": ts, "ordinal": 0, "type": type_, "payload": payload},
                      ensure_ascii=False)


def codex_msg(ts, role, text) -> str:
    return codex_line(ts, "response_item",
                      {"type": "message", "id": "m", "role": role,
                       "content": [{"type": "input_text" if role != "assistant" else "output_text",
                                    "text": text}]})


def make_codex_session(sessions_dir: Path, sid: str, cwd: str, day="2026-10-01") -> Path:
    """一个正常会话：包装文本 + 两条人话 + 助手收尾。"""
    path = sessions_dir / "2026" / "10" / day / f"rollout-{day}T00-00-00-{sid}.jsonl"
    lines = [
        codex_line(f"{day}T00:00:00.000Z", "session_meta",
                   {"session_id": sid, "cwd": cwd, "originator": "codex-tui"}),
        codex_msg(f"{day}T00:00:01.000Z", "developer", "You are Codex…"),
        codex_msg(f"{day}T00:00:02.000Z", "user", "<environment_context>\n  <cwd>x</cwd>\n</environment_context>"),
        codex_msg(f"{day}T02:00:00.000Z", "user", "开始训练"),
        codex_msg(f"{day}T02:00:10.000Z", "assistant", "好的，正在起任务。"),
        # event_msg 回显：不是 response_item，应被忽略
        codex_line(f"{day}T02:00:11.000Z", "event_msg",
                   {"type": "item_completed",
                    "item": {"type": "UserMessage", "content": [{"type": "text", "text": "开始训练"}]}}),
        codex_msg(f"{day}T02:05:00.000Z", "user", "y"),
        codex_msg(f"{day}T02:06:00.000Z", "assistant", "已开始。"),
    ]
    write_lines(path, lines)
    return path


class CodexParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "codex"
        self.sessions = self.root / "sessions"
        self.sample = make_codex_session(self.sessions, CODEX_SID, CODEX_CWD)

    def test_parse_rollout(self):
        rec = harvest_codex.parse_rollout(self.sample)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["session_id"], CODEX_SID)
        self.assertEqual(rec["cwd"], CODEX_CWD)
        self.assertEqual([m["text"] for m in rec["users"]], ["开始训练", "y"])
        self.assertEqual(rec["tail"], "已开始。")

    def test_merge_resumed_session(self):
        # 续开：同一 session_id 的另一份 rollout 文件
        resumed = self.sessions / "2026" / "10" / "02" / f"rollout-2026-10-02T00-00-00-{CODEX_SID}.jsonl"
        write_lines(resumed, [
            codex_line("2026-10-02T03:00:00.000Z", "session_meta", {"session_id": CODEX_SID, "cwd": CODEX_CWD}),
            codex_msg("2026-10-02T03:00:05.000Z", "user", "继续"),
            codex_msg("2026-10-02T03:01:00.000Z", "assistant", "继续跑起来了。"),
        ])
        records = [harvest_codex.parse_rollout(self.sample), harvest_codex.parse_rollout(resumed)]
        merged = harvest_codex.merge_groups(records)
        self.assertEqual(len(merged), 1)
        rec = merged[0]
        self.assertEqual([m["text"] for m in rec["messages"]], ["开始训练", "y", "继续"])
        self.assertEqual(rec["tail"], "继续跑起来了。")
        self.assertEqual(rec["date"], local_date("2026-10-01T02:00:00.000Z"))

    def test_harvest_writes_md_and_index(self):
        inbox = Path(self.tmp.name) / "inbox"
        stats = harvest_codex.harvest(self.root, inbox, dry_run=False,
                                      log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats["harvested"], 1)
        md_files = list((inbox / "codex" / "demo-flash").glob(f"{CODEX_SID}.*.md"))
        self.assertEqual(len(md_files), 1)
        md_path = md_files[0]
        body = md_path.read_text(encoding="utf-8")
        self.assertIn(f"# demo-flash · {local_date('2026-10-01T02:00:00.000Z')} · {CODEX_SID[:8]}", body)
        self.assertIn("- (02:00) 开始训练".replace("02:00", local_hhmm("2026-10-01T02:00:00.000Z")), body)
        self.assertIn("## 会话收尾", body)
        entries = [json.loads(l) for l in (inbox / "index.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "codex")
        self.assertRegex(entries[0]["path"], rf"codex/demo-flash/{CODEX_SID}\.[0-9a-f]{{8}}\.md")
        self.assertEqual(entries[0]["n_user"], 2)
        # 幂等
        stats2 = harvest_codex.harvest(self.root, inbox, dry_run=False,
                                       log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats2["harvested"], 0)
        self.assertEqual(stats2["skipped_dup"], 1)

    def test_session_without_human_counts_as_empty(self):
        other = "01a99999-0000-0000-0000-000000000000"
        write_lines(self.sessions / "2026" / "10" / "03" / "rollout-empty.jsonl", [
            codex_line("2026-10-03T00:00:00.000Z", "session_meta", {"session_id": other, "cwd": CODEX_CWD}),
            codex_msg("2026-10-03T00:00:01.000Z", "user", "<environment_context></environment_context>"),
        ])
        inbox = Path(self.tmp.name) / "inbox"
        stats = harvest_codex.harvest(self.root, inbox, dry_run=True,
                                      log=lambda *_: None, err=lambda *_: None)
        self.assertEqual(stats["harvested"], 1)
        self.assertEqual(stats["skipped_empty"], 1)
        self.assertEqual(list((inbox / "codex" / "demo-flash").glob(f"{other}.*.md")), [])

    def test_history_fallback(self):
        root = Path(self.tmp.name) / "codex_history_only"
        root.mkdir()
        write_lines(root / "history.jsonl", [
            json.dumps({"session_id": CODEX_SID, "ts": 1788200000, "text": "开始训练"},
                       ensure_ascii=False),
            json.dumps({"session_id": CODEX_SID, "ts": 1788200100, "text": "<environment_context>包装</environment_context>"},
                       ensure_ascii=False),
            json.dumps({"session_id": CODEX_SID, "ts": 1788200200, "text": "继续"},
                       ensure_ascii=False),
        ])
        inbox = Path(self.tmp.name) / "inbox"
        stats = harvest_codex.harvest(root, inbox, dry_run=False,
                                      log=lambda *_: None, err=lambda *_: None)
        self.assertTrue(stats["fallback"])
        self.assertEqual(stats["harvested"], 1)
        md_path = next((inbox / "codex" / "unknown").glob(f"{CODEX_SID}.*.md"))
        body = md_path.read_text(encoding="utf-8")
        self.assertIn("开始训练", body)
        self.assertIn("继续", body)
        self.assertNotIn("<environment_context>", body)

    def test_missing_data_dir_is_reported_not_crash(self):
        stats = harvest_codex.harvest(Path(self.tmp.name) / "nope",
                                      Path(self.tmp.name) / "inbox",
                                      log=lambda *_: None, err=lambda *_: None)
        self.assertTrue(stats["root_missing"])
        self.assertEqual(stats["harvested"], 0)


class SharedHelperTests(unittest.TestCase):
    def test_wrapper_filter(self):
        for h in (harvest_claude._is_wrapper, harvest_codex._is_wrapper):
            self.assertTrue(h("<command-name>/x</command-name>"))
            self.assertTrue(h("[Request interrupted by user for tool use]"))
            self.assertTrue(h("This session is being continued from a previous conversation that ran out"))
            self.assertFalse(h("你好，继续"))
            self.assertFalse(h("继续"))

    def test_safe_name(self):
        self.assertEqual(harvest_codex._safe_name("demo-project"), "demo-project")
        self.assertEqual(harvest_codex._safe_name('a/b:c*?"<>|'), "a_b_c______")
        self.assertEqual(harvest_codex._safe_name(""), "unknown")
        self.assertEqual(harvest_codex._safe_name("   "), "unknown")

    def test_project_from_cwd(self):
        self.assertEqual(harvest_claude._project_from_cwd(r"C:\work\demo-project"), "demo-project")
        self.assertEqual(harvest_claude._project_from_cwd(""), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
