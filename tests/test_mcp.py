#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mcp.py —— EAI MCP 服务（src/eai/mcp_server.py）黑盒测试。

跑法（EAI 根目录，Windows，务必带 PYTHONUTF8=1）：
    set PYTHONUTF8=1 && python tests/test_mcp.py
    PYTHONUTF8=1 python tests/test_mcp.py -v

被测对象 = 真实的 src/eai/mcp_server.py。它依赖的 eai.store / eai.recall / eai.util
此刻由 tests/stubs 下的最小桩包顶上（正式模块就绪后本测试仍走桩包，保证确定性）。
两种启动方式都测：
- 直接脚本方式：python src/eai/mcp_server.py     （PYTHONPATH=tests/stubs）
- 模块方式：    python -m eai.mcp_server          （脚手架包 __path__=[桩包, src]）

覆盖：initialize / notifications/initialized / tools/list / tools/call（recall、remember、
memory_stats）正常流；畸形 JSON 行与畸形请求不崩溃；stdout 每行都是合法 JSON；
记忆组件缺失时降级为 isError 而不是崩溃。
"""

from __future__ import annotations

import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]          # EAI 根目录
SRC = ROOT / "src"
STUBS = ROOT / "tests" / "stubs"
SERVER_PY = SRC / "eai" / "mcp_server.py"

TEXT1 = "EAI 管家联调：MCP 的 remember 工具写入的第一条测试记忆。"
TEXT_SEED = "EAI 私人管家项目的记忆系统在这一天开工。"


def jline(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def rpc(mid, method, params=None):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def tool_params(name, arguments=None):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return params


def child_env(pythonpath, home):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"                    # 不在 src/ 留 __pycache__
    if pythonpath is None:                                  # None = 不给 PYTHONPATH
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(pythonpath)                 # 覆盖继承值，保证确定性
    env["EAI_HOME"] = str(home)                             # 测试绝不碰真库
    return env


def read_stub_store(home) -> list:
    path = pathlib.Path(home) / "memory" / "stub_store.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


class ServerProc:
    """一个 MCP 服务子进程；行读取带超时，测试不会挂死。"""

    def __init__(self, argv, env, cwd):
        self.argv = argv
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, cwd=str(cwd))
        self.raw_lines = []
        self.stderr_text = []
        self._lines = queue.Queue()
        self._t_out = threading.Thread(target=self._pump_out, daemon=True)
        self._t_err = threading.Thread(target=self._pump_err, daemon=True)
        self._t_out.start()
        self._t_err.start()

    # ---------- 管道泵 ----------

    def _pump_out(self):
        try:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace")
                self.raw_lines.append(line)
                self._lines.put(line)
        except Exception:
            pass
        finally:
            self._lines.put(None)

    def _pump_err(self):
        try:
            for raw in self.proc.stderr:
                self.stderr_text.append(raw.decode("utf-8", "replace"))
        except Exception:
            pass

    # ---------- 交互 ----------

    def send_line(self, text: str) -> None:
        self.proc.stdin.write((text + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def send(self, obj) -> None:
        self.send_line(jline(obj))

    def read(self, timeout=20.0) -> dict:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("等待服务响应超时（%.0fs）；stderr：\n%s"
                                 % (timeout, self.stderr_now()))
        if line is None:
            raise AssertionError("服务已退出，没等到响应；stderr：\n%s" % self.stderr_now())
        return json.loads(line)

    def call(self, msg, timeout=20.0) -> dict:
        self.send(msg)
        return self.read(timeout)

    def expect_no_output(self, timeout=1.5) -> None:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return
        raise AssertionError("本不该有响应，却收到：%s" % (line,))

    def stderr_now(self) -> str:
        return "".join(self.stderr_text)[-2000:]

    # ---------- 收尾 ----------

    def close(self, timeout=20) -> int:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            rc = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
            raise AssertionError("stdin 关闭后服务没有退出")
        self._t_out.join(timeout=5)
        self._t_err.join(timeout=5)
        self._close_pipes()
        return rc

    def kill(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(timeout=10)
        except Exception:
            pass
        self._t_out.join(timeout=5)
        self._t_err.join(timeout=5)
        self._close_pipes()

    def _close_pipes(self) -> None:
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass


class McpTestBase(unittest.TestCase):

    def setUp(self):
        self._tmp = []
        self._servers = []

    def tearDown(self):
        for s in self._servers:
            s.kill()
        for d in self._tmp:
            shutil.rmtree(d, ignore_errors=True)

    # ---------- 脚手架 ----------

    def new_tmp(self, prefix="eai_mcp_test_") -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
        self._tmp.append(d)
        return d

    def start_direct(self, home) -> ServerProc:
        """直接跑真实文件：python <EAI>/src/eai/mcp_server.py（依赖走桩包）。"""
        argv = [sys.executable, str(SERVER_PY)]
        srv = ServerProc(argv, child_env(STUBS, home), self.new_tmp("eai_mcp_cwd_"))
        self._servers.append(srv)
        return srv

    def start_module_scaffold(self, home, with_deps=True) -> ServerProc:
        """python -m eai.mcp_server。

        with_deps=True ：脚手架 eai/__init__.py 把 __path__ 指向 [桩包, src]，
                         于是 mcp_server 取真实文件、依赖取桩包。
        with_deps=False：只拷一份 mcp_server.py，依赖故意缺失（测降级）。
        """
        root = self.new_tmp("eai_mcp_scaffold_")
        pkg = root / "eai"
        pkg.mkdir(parents=True, exist_ok=True)
        if with_deps:
            (pkg / "__init__.py").write_text(
                "# 测试脚手架：桩包在前、真实 src 在后（保证测试确定性）\n"
                "__path__ = %s\n" % repr([str(STUBS / "eai"), str(SRC / "eai")]),
                encoding="utf-8")
        else:
            (pkg / "__init__.py").write_text(
                "# 测试脚手架：只有 mcp_server 副本，依赖故意缺失\n", encoding="utf-8")
            shutil.copyfile(SERVER_PY, pkg / "mcp_server.py")
        argv = [sys.executable, "-m", "eai.mcp_server"]
        srv = ServerProc(argv, child_env(root, home), root)
        self._servers.append(srv)
        return srv

    # ---------- 断言助手 ----------

    def assert_result(self, resp, rid):
        self.assertEqual(resp.get("jsonrpc"), "2.0")
        self.assertEqual(resp.get("id"), rid)
        self.assertNotIn("error", resp, "不该出错：%s" % (resp,))
        self.assertIn("result", resp)
        return resp["result"]

    def assert_error(self, resp, rid, code):
        self.assertEqual(resp.get("jsonrpc"), "2.0")
        self.assertEqual(resp.get("id"), rid)
        self.assertIn("error", resp, "该报错却成功：%s" % (resp,))
        self.assertEqual(resp["error"].get("code"), code, resp["error"])
        self.assertTrue(str(resp["error"].get("message") or "").strip())

    def tool_payload(self, result):
        self.assertIn("content", result)
        content = result["content"]
        self.assertIsInstance(content, list)
        self.assertTrue(content)
        self.assertEqual(content[0].get("type"), "text")
        return json.loads(content[0]["text"])

    def assert_clean_stdout(self, srv: ServerProc):
        """stdout 每一行都必须是合法 JSON-RPC 消息（不许有日志、空行混进来）。"""
        self.assertTrue(srv.raw_lines, "stdout 一行都没有")
        for raw in srv.raw_lines:
            obj = json.loads(raw)                       # 解析失败 → 抛错即失败
            self.assertIsInstance(obj, dict, "stdout 出现非对象行：%r" % raw)
            self.assertEqual(obj.get("jsonrpc"), "2.0", "stdout 出现非 JSON-RPC 行：%r" % raw)

    def assert_clean_stderr(self, srv: ServerProc):
        joined = "".join(srv.stderr_text)
        self.assertIn("[eai-mcp", joined, "日志应该打在 stderr 上")


class TestMcpServer(McpTestBase):

    # ==================================================================
    # 1. 模块方式（python -m eai.mcp_server）+ initialize / tools/list
    # ==================================================================

    def test_module_mode_initialize_and_tools_list(self):
        home = self.new_tmp()
        srv = self.start_module_scaffold(home)

        r = srv.call(rpc(1, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "eai-test", "version": "0.1"},
        }))
        res = self.assert_result(r, 1)
        self.assertEqual(res["protocolVersion"], "2025-06-18")          # 回显请求值
        self.assertEqual(res["capabilities"], {"tools": {}})
        self.assertEqual(res["serverInfo"], {"name": "eai-memory", "version": "0.1.0"})

        # 通知（无 id）：不许回复；紧跟一个请求，若上一条被误回，这里 id 就对不上
        srv.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = srv.call(rpc(2, "tools/list"))
        res = self.assert_result(r, 2)

        tools = {t["name"]: t for t in res["tools"]}
        self.assertEqual(set(tools), {"recall", "remember", "memory_stats"})
        for t in tools.values():
            self.assertTrue(str(t.get("description") or "").strip())
            self.assertEqual(t["inputSchema"].get("type"), "object")
        self.assertEqual(tools["recall"]["inputSchema"]["required"], ["query"])
        self.assertEqual(tools["recall"]["inputSchema"]["properties"]["k"]["default"], 6)
        self.assertEqual(tools["remember"]["inputSchema"]["required"], ["text"])
        rp = tools["remember"]["inputSchema"]["properties"]
        self.assertEqual(rp["kind"]["default"], "fact")
        self.assertEqual(rp["scope"]["default"], "general")
        self.assertEqual(rp["importance"]["default"], 0.6)
        self.assertIn("fact", rp["kind"]["enum"])

        srv.expect_no_output()
        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)
        self.assert_clean_stderr(srv)

    # ==================================================================
    # 2. 直接脚本方式 + 三个工具的完整往返（含落盘与重启）
    # ==================================================================

    def test_tools_call_roundtrip_direct_run(self):
        home = self.new_tmp()
        srv = self.start_direct(home)
        self.assert_result(srv.call(rpc(1, "initialize", {"protocolVersion": "2024-11-05"})), 1)

        # 基线统计（桩库首访播种 3 条）
        stats = self.tool_payload(self.assert_result(
            srv.call(rpc(2, "tools/call", tool_params("memory_stats"))), 2))
        self.assertEqual(stats["total"], 3)
        self.assertIsInstance(stats["by_kind"], dict)

        # recall：命中种子记忆，7 个字段齐全、score 在 [0,1]
        items = self.tool_payload(self.assert_result(
            srv.call(rpc(3, "tools/call", tool_params("recall", {"query": "管家"}))), 3))
        self.assertIsInstance(items, list)
        self.assertTrue(items)
        self.assertEqual(set(items[0]),
                         {"id", "kind", "scope", "date", "title", "text", "score"})
        self.assertEqual(items[0]["text"], TEXT_SEED)
        self.assertEqual(items[0]["date"], "2026-10-10")
        self.assertGreaterEqual(items[0]["score"], 0.0)
        self.assertLessEqual(items[0]["score"], 1.0)

        # remember：默认值走 fact/general/0.6
        payload = self.tool_payload(self.assert_result(
            srv.call(rpc(4, "tools/call",
                         tool_params("remember", {"text": TEXT1, "scope": "EAI联调"}))), 4))
        self.assertEqual(payload["action"], "inserted")
        self.assertTrue(str(payload["id"]).startswith("m"))
        mid = payload["id"]

        # 同文重复写入 → merged、沿用同 id
        payload2 = self.tool_payload(self.assert_result(
            srv.call(rpc(5, "tools/call",
                         tool_params("remember", {"text": TEXT1, "scope": "EAI联调"}))), 5))
        self.assertEqual(payload2["action"], "merged")
        self.assertEqual(payload2["id"], mid)

        # recall 找回刚写的
        items6 = self.tool_payload(self.assert_result(
            srv.call(rpc(6, "tools/call", tool_params("recall", {"query": "联调"}))), 6))
        hit = [it for it in items6 if it["text"] == TEXT1]
        self.assertTrue(hit, "刚 remember 的内容应能被 recall 命中：%s" % (items6,))
        self.assertEqual(hit[0]["scope"], "EAI联调")

        # 统计增长：3 + 1（merged 不新增）
        stats7 = self.tool_payload(self.assert_result(
            srv.call(rpc(7, "tools/call", tool_params("memory_stats"))), 7))
        self.assertEqual(stats7["total"], 4)
        self.assertEqual(stats7["by_kind"].get("fact"), 2)
        self.assertEqual(stats7["by_scope"].get("EAI联调"), 1)

        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)
        self.assert_clean_stderr(srv)

        # 落盘检查：字段写对（kind/scope/importance/title/ts/id）
        recs = read_stub_store(home)
        got = [r for r in recs if r.get("text") == TEXT1]
        self.assertEqual(len(got), 1)
        rec = got[0]
        self.assertEqual(rec["kind"], "fact")
        self.assertEqual(rec["scope"], "EAI联调")
        self.assertEqual(rec["importance"], 0.6)
        self.assertEqual(rec["title"], TEXT1[:20])
        self.assertEqual(rec["id"], mid)
        self.assertRegex(str(rec["ts"]), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

        # 重启一个新服务：记忆还在（惰性重连，跨进程持久）
        srv2 = self.start_direct(home)
        self.assert_result(srv2.call(rpc(1, "initialize", {})), 1)
        items_a = self.tool_payload(self.assert_result(
            srv2.call(rpc(2, "tools/call", tool_params("recall", {"query": "联调"}))), 2))
        self.assertTrue([it for it in items_a if it["text"] == TEXT1])
        stats_b = self.tool_payload(self.assert_result(
            srv2.call(rpc(3, "tools/call", tool_params("memory_stats"))), 3))
        self.assertEqual(stats_b["total"], 4)
        self.assertEqual(srv2.close(), 0)
        self.assert_clean_stdout(srv2)

    # ==================================================================
    # 3. 畸形输入：回标准错误或不响应，必须不崩溃
    # ==================================================================

    def test_malformed_inputs_do_not_crash(self):
        home = self.new_tmp()
        srv = self.start_direct(home)
        self.assert_result(srv.call(rpc(1, "initialize", {})), 1)

        # (要发送的整行, 期望的响应序列 [(id, error_code 或 None=成功)]；空列表=不回复)
        cases = [
            ("", []),                                                    # 空行 → 不回复
            ("   ", []),                                                 # 空白行 → 不回复
            ("not json at all", [(None, -32700)]),                       # 解析错误
            ("{", [(None, -32700)]),
            ("[", [(None, -32700)]),
            ("123", [(None, -32600)]),                                   # JSON 合法但不是请求对象
            ("null", [(None, -32600)]),
            ('"hello"', [(None, -32600)]),
            ("[1, 2]", [(None, -32600), (None, -32600)]),                # 批处理：两个元素都不合法
            ("[]", [(None, -32600)]),                                    # 空批处理
            (jline(rpc(101, "no/such/method")), [(101, -32601)]),        # 未知方法
            (jline({"jsonrpc": "2.0", "method": "no/such/method"}), []), # 未知通知 → 不回复
            (jline({"jsonrpc": "2.0", "id": 102}), [(102, -32600)]),     # 没有 method
            (jline({"jsonrpc": "2.0", "id": 103, "method": 123}), [(103, -32600)]),
            (jline({"jsonrpc": "1.0", "id": 104, "method": "tools/list"}), [(104, -32600)]),
            (jline({"jsonrpc": "2.0", "id": 105, "method": "tools/call", "params": []}),
             [(105, -32602)]),                                           # params 不是对象
            (jline(rpc(106, "tools/call", {"name": "nope", "arguments": {}})),
             [(106, -32602)]),                                           # 未知工具
            (jline(rpc(107, "tools/call", {"name": "recall", "arguments": {}})),
             [(107, -32602)]),                                           # 缺 query
            (jline(rpc(108, "tools/call", {"name": "recall",
                                           "arguments": {"query": "管家", "k": "多"}})),
             [(108, -32602)]),                                           # k 类型不对
            (jline(rpc(109, "tools/call", {"name": "remember",
                                           "arguments": {"text": "   "}})),
             [(109, -32602)]),                                           # 空正文
            (jline(rpc(110, "tools/call", {"name": "remember",
                                           "arguments": {"text": "普通文本", "kind": "bogus"}})),
             [(110, -32602)]),                                           # kind 不在枚举
            (jline({"jsonrpc": "2.0", "id": 111, "method": "tools/call",
                    "params": {"name": "remember", "arguments": {
                        "text": "畸形测试：这条应该写入成功", "scope": "", "importance": 9}}}),
             [(111, None)]),                                             # scope 空→general、importance 夹到 1
            (jline(rpc(112, "tools/call", {"name": "recall",
                                           "arguments": {"query": "管家", "k": -5}})),
             [(112, None)]),                                             # k 超界 → 夹到 1，正常返回
            (jline(rpc(113, "initialize")), [(113, None)]),              # 缺 params 也能初始化
            ("\ufeff" + jline(rpc(114, "tools/list")), [(114, None)]),    # 行首带 BOM 也要认
        ]

        for line, _ in cases:
            srv.send_line(line)

        expected = [exp for _, exps in cases for exp in exps]
        got = [srv.read() for _ in expected]
        for (resp, (rid, code)) in zip(got, expected):
            if code is None:
                self.assert_result(resp, rid)
            else:
                self.assert_error(resp, rid, code)

        # 不该多出任何响应（通知、空行必须静默）
        srv.expect_no_output()

        # 服务还活着
        res = self.assert_result(srv.call(rpc(500, "tools/list")), 500)
        self.assertEqual(len(res["tools"]), 3)
        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)

        recs = read_stub_store(home)
        got_rec = [r for r in recs if r.get("text") == "畸形测试：这条应该写入成功"]
        self.assertEqual(len(got_rec), 1)
        self.assertEqual(got_rec[0]["scope"], "general")                # 空 scope → general
        self.assertEqual(got_rec[0]["importance"], 1.0)                 # 9 → 夹到 1.0
        self.assertEqual(got_rec[0]["kind"], "fact")                    # 缺省 kind

    # ==================================================================
    # 4. 依赖缺失：协议本体照常，工具调用降级为 isError（不崩溃）
    # ==================================================================

    def test_missing_deps_serves_protocol_gracefully(self):
        home = self.new_tmp()
        srv = self.start_module_scaffold(home, with_deps=False)

        res = self.assert_result(srv.call(rpc(1, "initialize", {"protocolVersion": "2025-06-18"})), 1)
        self.assertEqual(res["protocolVersion"], "2025-06-18")
        res2 = self.assert_result(srv.call(rpc(2, "tools/list")), 2)
        self.assertEqual({t["name"] for t in res2["tools"]},
                         {"recall", "remember", "memory_stats"})

        for mid, params in ((3, tool_params("recall", {"query": "管家"})),
                            (4, tool_params("remember", {"text": "写不进去的"})),
                            (5, tool_params("memory_stats"))):
            result = self.assert_result(srv.call(rpc(mid, "tools/call", params)), mid)
            self.assertTrue(result.get("isError"), "依赖缺失时应回 isError：%s" % (result,))
            self.assertIn("content", result)

        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)
        self.assert_clean_stderr(srv)

    # ==================================================================
    # 5. 补充：无 id 的 tools/call（通知语义）不执行、不回复
    # ==================================================================

    def test_notification_style_tools_call_is_ignored(self):
        home = self.new_tmp()
        srv = self.start_direct(home)
        self.assert_result(srv.call(rpc(1, "initialize", {})), 1)

        srv.send({"jsonrpc": "2.0", "method": "tools/call",
                  "params": tool_params("remember", {"text": "不该被写进去的通知"})})
        srv.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": tool_params("memory_stats")})
        stats = self.tool_payload(self.assert_result(srv.read(), 2))
        self.assertEqual(stats["total"], 3, "无 id 的写入不该被执行")

        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)
        recs = read_stub_store(home)
        self.assertFalse([r for r in recs if r.get("text") == "不该被写进去的通知"])


    # ==================================================================
    # 6. 真实联调：正式模块（src/eai/*）已就绪时走真链路；未就绪自动跳过
    # ==================================================================

    def test_real_modules_integration_when_available(self):
        """直跑真实文件 + 真实 store/recall/util（EAI_HOME 指向临时目录，不碰真库）。"""
        home = self.new_tmp()
        srv = ServerProc([sys.executable, str(SERVER_PY)], child_env(None, home),
                         self.new_tmp("eai_mcp_cwd_"))
        self._servers.append(srv)

        self.assert_result(srv.call(rpc(1, "initialize", {"protocolVersion": "2025-06-18"})), 1)
        stats_res = self.assert_result(
            srv.call(rpc(2, "tools/call", tool_params("memory_stats"))), 2)
        if stats_res.get("isError"):
            self.assertEqual(srv.close(), 0)
            self.skipTest("正式模块（src/eai）尚未就绪：%s" % stats_res["content"][0]["text"])
        base = self.tool_payload(stats_res)
        self.assertIn("total", base)

        text = "MCP 联调：写给临时库，验证真实 store 链路。"
        payload = self.tool_payload(self.assert_result(
            srv.call(rpc(3, "tools/call", tool_params(
                "remember", {"text": text, "kind": "fact", "scope": "EAI联调"}))), 3))
        self.assertIn(payload["action"], ("inserted", "merged"))

        items = self.tool_payload(self.assert_result(
            srv.call(rpc(4, "tools/call", tool_params("recall", {"query": "联调 临时库"}))), 4))
        self.assertTrue(any(it.get("text") == text for it in items), items)

        stats2 = self.tool_payload(self.assert_result(
            srv.call(rpc(5, "tools/call", tool_params("memory_stats"))), 5))
        self.assertGreaterEqual(stats2["total"], base["total"])

        self.assertEqual(srv.close(), 0)
        self.assert_clean_stdout(srv)
        self.assert_clean_stderr(srv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
