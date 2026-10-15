#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EAI 管家 · MCP 服务（stdio，换行分隔 JSON-RPC 2.0）。

图纸：specs/30_surfaces.md §5。只用 Python 标准库，零第三方依赖。

行为契约
- 传输：stdin 逐行读、stdout 逐行写（每行一条完整 JSON，写完立即 flush）；
  stdout 只许出现 JSON，所有日志一律走 stderr。
- 方法：initialize / notifications/initialized / tools/list / tools/call（另支持标准 ping）。
- 工具：recall(query, k=6) / remember(text, kind="fact", scope="general", importance=0.6)
        / memory_stats()。
- 畸形行、畸形请求、未知方法：回标准 JSON-RPC 错误或不响应，绝不崩溃。
- 记忆组件（eai.store / eai.recall / eai.util）缺失或运行时报错：只让相应工具调用
  回 isError=true，协议本体（initialize / tools/list）照常工作。

两种启动方式
    python -m eai.mcp_server           # PYTHONPATH 含 src（或 cwd 在 src 下）
    python src/eai/mcp_server.py       # 脚本直跑：自行修 sys.path
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback

# --------------------------------------------------------------------------
# 启动引导：脚本方式直跑时，把 src/ 修进 sys.path；-m / 已配 PYTHONPATH 时不动
# --------------------------------------------------------------------------

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))       # …/src/eai
_SRC_DIR = os.path.dirname(_PKG_DIR)                        # …/src
_EAI_ROOT = os.path.dirname(_SRC_DIR)                       # EAI 根目录


def _bootstrap_sys_path() -> None:
    """eai 包已可导入就不动；否则把 src/ 插到最前面（覆盖脚本直跑的默认路径）。"""
    try:
        import eai.store  # noqa: F401  仅探测
        import eai.util  # noqa: F401
        return
    except Exception:
        pass
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)


_bootstrap_sys_path()

# --------------------------------------------------------------------------
# 依赖导入（守卫式：任何模块缺失都不阻止服务启动，只影响对应工具）
# --------------------------------------------------------------------------

try:
    from eai.util import eai_home, new_id
    _UTIL_ERROR = None
except Exception as _exc:                                   # 组件缺失：退化为本地最小实现
    _UTIL_ERROR = _exc

    def eai_home() -> str:
        env = os.environ.get("EAI_HOME")
        return os.path.abspath(env) if env else _EAI_ROOT

    def new_id() -> str:
        return "m" + time.strftime("%Y%m%d%H%M%S") + "-%04x" % random.randrange(0x10000)

try:
    from eai.store import MemoryStore
    _STORE_ERROR = None
except Exception as _exc:
    MemoryStore = None
    _STORE_ERROR = _exc

try:
    from eai.recall import recall as _recall_impl
    _RECALL_ERROR = None
except Exception as _exc:
    _recall_impl = None
    _RECALL_ERROR = _exc

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

SERVER_NAME = "eai-memory"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

KINDS = ("fact", "preference", "correction", "decision",
         "promise", "project", "skill", "episode")
DEFAULT_K = 6
K_MIN, K_MAX = 1, 50
DEFAULT_KIND = "fact"
DEFAULT_SCOPE = "general"
DEFAULT_IMPORTANCE = 0.6
MAX_TEXT_CHARS = 4000

_NO_REPLY = object()        # 内部哨兵：这条消息不回

# --------------------------------------------------------------------------
# 日志 / JSON 助手
# --------------------------------------------------------------------------


def _log(fmt: str, *args) -> None:
    """日志一律 stderr；日志自身出任何问题都不许影响服务。"""
    try:
        msg = (fmt % args) if args else str(fmt)
        sys.stderr.write("[eai-mcp %s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        sys.stderr.flush()
    except Exception:
        pass


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _short(obj, limit: int = 200) -> str:
    try:
        s = _dumps(obj)
    except Exception:
        s = repr(obj)
    return s if len(s) <= limit else s[:limit] + "…"


def _ok(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _fail(rid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


class _RpcError(Exception):
    """协议层错误（-32602 等），由分发层转成 JSON-RPC error 响应。"""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _tool_text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# --------------------------------------------------------------------------
# 记忆组件（懒连接；失败不缓存，下次调用重试）
# --------------------------------------------------------------------------

_STORE = None


def _get_store():
    global _STORE
    if _STORE is None:
        if MemoryStore is None:
            raise RuntimeError("记忆组件不可用（eai.store 导入失败：%s）" % (_STORE_ERROR,))
        _STORE = MemoryStore()
    return _STORE


# --------------------------------------------------------------------------
# 工具参数校验（类型不对 → -32602；超界 → 夹到边界）
# --------------------------------------------------------------------------


def _arg_int(args: dict, name: str, default: int, lo: int, hi: int) -> int:
    v = args.get(name)
    if v is None:
        return default
    if isinstance(v, bool):
        raise _RpcError(-32602, "Invalid params", "参数 %s 必须是整数" % name)
    if isinstance(v, int):
        iv = v
    elif isinstance(v, float) and v.is_integer():
        iv = int(v)
    elif isinstance(v, str) and v.strip().lstrip("+-").isdigit():
        iv = int(v.strip())
    else:
        raise _RpcError(-32602, "Invalid params", "参数 %s 必须是整数，收到：%s" % (name, _short(v, 60)))
    return max(lo, min(hi, iv))


def _arg_float(args: dict, name: str, default: float, lo: float, hi: float) -> float:
    v = args.get(name)
    if v is None:
        return default
    if isinstance(v, bool):
        raise _RpcError(-32602, "Invalid params", "参数 %s 必须是数字" % name)
    if isinstance(v, (int, float)):
        fv = float(v)
    elif isinstance(v, str):
        try:
            fv = float(v.strip())
        except ValueError:
            raise _RpcError(-32602, "Invalid params", "参数 %s 必须是数字，收到：%s" % (name, _short(v, 60)))
    else:
        raise _RpcError(-32602, "Invalid params", "参数 %s 必须是数字" % name)
    return max(lo, min(hi, fv))


# --------------------------------------------------------------------------
# 三个工具
# --------------------------------------------------------------------------


def _item_view(rec) -> dict:
    """把记忆记录裁成对外统一的 7 个字段。"""
    rec = rec if isinstance(rec, dict) else {}
    ts = rec.get("ts") or rec.get("updated_ts") or ""
    try:
        score = round(float(rec.get("score")), 4)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "id": str(rec.get("id") or ""),
        "kind": str(rec.get("kind") or ""),
        "scope": str(rec.get("scope") or DEFAULT_SCOPE),
        "date": str(ts)[:10],
        "title": str(rec.get("title") or ""),
        "text": str(rec.get("text") or ""),
        "score": score,
    }


def _tool_recall(args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise _RpcError(-32602, "Invalid params", "recall 需要非空字符串参数 query")
    query = query.strip()
    k = _arg_int(args, "k", DEFAULT_K, K_MIN, K_MAX)
    try:
        store = _get_store()
        if _recall_impl is not None:
            hits = _recall_impl(store, query, k)
        else:                                   # eai.recall 缺失时的降级：直接问库
            hits = [dict(rec, score=rel) for rec, rel in store.search(query, k)]
        items = [_item_view(rec) for rec in (hits or [])]
    except _RpcError:
        raise
    except Exception as exc:
        _log("recall 失败：%r", exc)
        return _tool_error("回忆失败：%s" % exc)
    return _tool_text(_dumps(items))


def _tool_remember(args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _RpcError(-32602, "Invalid params", "remember 需要非空字符串参数 text")
    text = text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise _RpcError(-32602, "Invalid params",
                        "text 过长（%d 字 > %d），请精简后再记" % (len(text), MAX_TEXT_CHARS))

    kind = args.get("kind")
    if kind is None:
        kind = DEFAULT_KIND
    if not isinstance(kind, str) or kind.strip().lower() not in KINDS:
        raise _RpcError(-32602, "Invalid params",
                        "kind 必须是以下之一：%s" % " / ".join(KINDS))
    kind = kind.strip().lower()

    scope = args.get("scope")
    if scope is None:
        scope = DEFAULT_SCOPE
    if not isinstance(scope, str):
        raise _RpcError(-32602, "Invalid params", "scope 必须是字符串")
    scope = scope.strip() or DEFAULT_SCOPE

    importance = _arg_float(args, "importance", DEFAULT_IMPORTANCE, 0.0, 1.0)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    rec = {
        "id": new_id(),
        "ts": ts,
        "updated_ts": ts,
        "kind": kind,
        "scope": scope,
        "title": " ".join(text.split())[:20],
        "text": text,
        "entities": [],
        "importance": importance,
        "confidence": 0.8,
        "source": {"via": "mcp"},
        "status": "active",
    }
    try:
        store = _get_store()
        res = store.add(rec)
    except Exception as exc:
        _log("remember 失败：%r", exc)
        return _tool_error("写入失败：%s" % exc)
    if not isinstance(res, dict):
        res = {}
    return _tool_text(_dumps({
        "action": str(res.get("action") or "inserted"),
        "id": str(res.get("id") or rec["id"]),
    }))


def _tool_memory_stats(args: dict) -> dict:
    try:
        store = _get_store()
        counts = store.counts()
    except Exception as exc:
        _log("memory_stats 失败：%r", exc)
        return _tool_error("统计失败：%s" % exc)
    if not isinstance(counts, dict):
        counts = {"counts": counts}
    return _tool_text(_dumps(counts))


# --------------------------------------------------------------------------
# 工具清单（tools/list）
# --------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "recall",
        "description": ("回忆：按关键词检索长期记忆，返回最相关条目"
                        "（含 id/kind/scope/date/title/text/score）。"
                        "不确定的事，先回忆再开口；query 可用中文、英文或项目简称。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词或一句话"},
                "k": {"type": "integer", "description": "返回条数上限，默认 6",
                      "default": DEFAULT_K, "minimum": K_MIN, "maximum": K_MAX},
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": ("记住：把一条信息写入长期记忆。kind 取 "
                        "fact/preference/correction/decision/promise/project/skill/episode；"
                        "scope 填项目名或 general。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "记忆正文，一两句话写清事实本身"},
                "kind": {"type": "string", "description": "记忆类型，默认 fact",
                         "enum": list(KINDS), "default": DEFAULT_KIND},
                "scope": {"type": "string", "description": "作用域（项目名或 general），默认 general",
                          "default": DEFAULT_SCOPE},
                "importance": {"type": "number", "description": "重要度 0–1，默认 0.6",
                               "default": DEFAULT_IMPORTANCE, "minimum": 0, "maximum": 1},
            },
            "required": ["text"],
        },
    },
    {
        "name": "memory_stats",
        "description": "记忆库统计：总数、各 kind/scope 计数、字符总量、最近增长。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# --------------------------------------------------------------------------
# 方法处理
# --------------------------------------------------------------------------


def _rpc_initialize(params) -> dict:
    pv = None
    client = ""
    if isinstance(params, dict):
        pv = params.get("protocolVersion")
        ci = params.get("clientInfo")
        if isinstance(ci, dict):
            client = str(ci.get("name") or "")
    if not isinstance(pv, str) or not pv.strip():
        pv = DEFAULT_PROTOCOL_VERSION
    _log("initialize：client=%s protocolVersion=%s", client or "-", pv)
    return {
        "protocolVersion": pv.strip(),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _rpc_tools_list(params) -> dict:
    return {"tools": _TOOLS}


def _rpc_tools_call(params) -> dict:
    if not isinstance(params, dict):
        raise _RpcError(-32602, "Invalid params", "tools/call 的 params 必须是对象")
    name = params.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _RpcError(-32602, "Invalid params", "tools/call 缺少工具名 name")
    name = name.strip()
    args = params.get("arguments")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise _RpcError(-32602, "Invalid params", "arguments 必须是对象")

    if name == "recall":
        return _tool_recall(args)
    if name == "remember":
        return _tool_remember(args)
    if name == "memory_stats":
        return _tool_memory_stats(args)
    raise _RpcError(-32602, "Invalid params", "未知工具：%s" % name)


def _process_message(msg):
    """处理一条已解析的 JSON-RPC 消息；返回响应对象 / 响应列表 / None（不回复）。"""
    if isinstance(msg, list):                                   # JSON-RPC 批处理
        if not msg:                                             # 空批处理 → Invalid Request
            return _fail(None, -32600, "Invalid Request", "空批处理")
        outs = []
        for item in msg:
            resp = _process_message(item)
            if resp is None:
                continue
            outs.extend(resp if isinstance(resp, list) else [resp])
        if not outs:                                            # 全是通知 → 不回复
            return None
        return outs if len(outs) > 1 else outs[0]
    if not isinstance(msg, dict):
        return _fail(None, -32600, "Invalid Request")

    has_id = "id" in msg
    rid = msg.get("id")
    if has_id and not (rid is None or (isinstance(rid, (str, int, float)) and not isinstance(rid, bool))):
        _log("id 类型非法：%s", _short(rid, 60))
        return _fail(None, -32600, "Invalid Request", "id 必须是字符串、数字或 null")
    if not has_id:
        rid = None

    method = msg.get("method")
    if msg.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method:
        if not has_id:                                          # 畸形通知：静默丢弃
            _log("忽略畸形通知：%s", _short(msg))
            return None
        return _fail(rid, -32600, "Invalid Request")

    if method.startswith("notifications/"):
        _log("收到通知：%s", method)
        return None if not has_id else _ok(rid, {})

    if not has_id:                                              # 通知：不执行、不回复
        _log("收到无 id 的 %s，按通知处理（不执行）", method)
        return None

    params = msg.get("params")
    if params is None:
        params = {}

    try:
        if method == "initialize":
            return _ok(rid, _rpc_initialize(params))
        if method == "ping":
            return _ok(rid, {})
        if method == "tools/list":
            return _ok(rid, _rpc_tools_list(params))
        if method == "tools/call":
            return _ok(rid, _rpc_tools_call(params))
        return _fail(rid, -32601, "Method not found", method)
    except _RpcError as exc:
        return _fail(rid, exc.code, exc.message, exc.data)
    except Exception as exc:                                    # 兜底：任何异常都不许掀桌
        _log("内部错误：%r\n%s", exc, traceback.format_exc())
        return _fail(rid, -32603, "Internal error", str(exc))


def _process_line(line: str) -> list:
    """处理一行输入；返回要写出去的响应列表（可能为空）。"""
    raw = line.strip().lstrip("\ufeff").strip()   # 容忍行首 BOM
    if not raw:                                                 # 空行：不响应
        return []
    try:
        msg = json.loads(raw)
    except Exception as exc:
        _log("畸形行（JSON 解析失败）：%s", _short(raw, 120))
        return [_fail(None, -32700, "Parse error", str(exc))]
    resp = _process_message(msg)
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    return [resp]


# --------------------------------------------------------------------------
# stdio 主循环
# --------------------------------------------------------------------------


def _configure_io() -> None:
    """stdin/stderr 按 UTF-8 宽容解码，避免坏字节把循环打断。"""
    for stream in (sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _write_message(obj, outstream=None) -> bool:
    """一条消息一行，UTF-8，写完 flush；失败返回 False。"""
    try:
        data = (_dumps(obj) + "\n").encode("utf-8")
    except Exception as exc:                                    # 理论上到不了
        _log("序列化响应失败：%r", exc)
        data = b'{"jsonrpc":"2.0","id":null,"error":{"code":-32603,"message":"Internal error"}}\n'
    stream = outstream if outstream is not None else getattr(sys.stdout, "buffer", None)
    if outstream is None and stream is None:
        stream = sys.stdout
    try:
        if stream is None:
            return False
        try:
            stream.write(data)
        except TypeError:                                       # 文本流：退化为字符串
            stream.write(data.decode("utf-8"))
        stream.flush()
        return True
    except (BrokenPipeError, ValueError, OSError) as exc:
        _log("写 stdout 失败：%r（客户端可能已关闭）", exc)
        return False


def serve(instream=None, outstream=None) -> int:
    """stdin 逐行读 JSON-RPC，处理到 EOF；返回进程退出码。"""
    _configure_io()
    instream = instream if instream is not None else sys.stdin
    try:
        home = eai_home()
    except Exception:
        home = "?"
    _log("服务启动：home=%s；store=%s；recall=%s",
         home, "就绪" if MemoryStore is not None else "缺失",
         "就绪" if _recall_impl is not None else "缺失")
    while True:
        try:
            line = instream.readline()
        except KeyboardInterrupt:
            _log("收到中断，退出")
            return 0
        except Exception as exc:
            _log("读取输入失败：%r", exc)
            return 1
        if line == "":                                          # EOF
            _log("stdin 关闭，退出")
            return 0
        for resp in _process_line(line):
            if not _write_message(resp, outstream):
                return 1
    return 0


def main() -> int:
    try:
        return serve()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        _log("服务异常退出：%r\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
