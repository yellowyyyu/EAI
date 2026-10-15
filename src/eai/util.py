# -*- coding: utf-8 -*-
"""EAI 通用工具：路径 / 配置 / 时间 / ID / 中文二元分词。仅标准库。"""
from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime
from itertools import count as _count
from pathlib import Path

# ---------------- 路径 ----------------

def eai_home() -> Path:
    """EAI 根目录：环境变量 EAI_HOME 优先；否则按 util.py 位置上溯三级（src/eai/util.py → EAI/）。"""
    env = os.environ.get("EAI_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def memory_dir() -> Path:
    return eai_home() / "memory"


def ensure_dirs() -> None:
    m = memory_dir()
    for sub in ("journal", "inbox", "core", "core/versions", "digests"):
        (m / sub).mkdir(parents=True, exist_ok=True)


# ---------------- 配置 ----------------

KINDS = ("fact", "preference", "correction", "decision", "promise", "project", "skill", "episode")

_DEFAULTS = {
    "backend": "ollama",
    "ollama_models": {"fast": "qwen2.5:3b-instruct", "quality": "qwen3.8:27b"},
    "extract_model": "fast",
    "weights": {"rel": 0.55, "imp": 0.30, "rec": 0.15, "scope_bonus": 0.08},
    "halflife_days": {
        "identity": 3650, "preference": 3650, "correction": 3650, "promise": 900,
        "decision": 720, "skill": 720, "fact": 540, "project": 240, "episode": 60,
    },
    "importance_defaults": {
        "identity": 1.0, "correction": 0.9, "preference": 0.8, "decision": 0.8,
        "promise": 0.8, "skill": 0.7, "fact": 0.6, "project": 0.6, "episode": 0.4,
    },
    "brief_max_chars": 3500,
    "reinforce_bump": 0.02,
    "ollama_url": "http://127.0.0.1:11434",
}


def load_config() -> dict:
    """默认值 + config.json 覆盖（深合并一层）。任何异常都回默认值。"""
    cfg = json.loads(json.dumps(_DEFAULTS))
    try:
        p = eai_home() / "config.json"
        if p.exists():
            user = json.loads(p.read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


# ---------------- 时间 / ID ----------------

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_ID_SEQ = _count(1)


def new_id() -> str:
    """时间戳 + 随机16位 + 进程内单调计数16位 —— 批量入库不撞 id（评审发现：原 4 位随机在
    千条级批量插入时重复，命中 UNIQUE 约束的候选会被静默跳过）。"""
    return ("m" + datetime.now().strftime("%Y%m%d%H%M%S")
            + "-%04x%04x" % (random.randint(0, 0xFFFF), next(_ID_SEQ) & 0xFFFF))


def age_days(ts: str, now: datetime | None = None) -> float:
    try:
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0.0
    return max(0.0, ((now or datetime.now()) - t).total_seconds() / 86400.0)


# ---------------- JSON ----------------

def jload(s, default=None):
    if s is None:
        return default
    if isinstance(s, (list, dict)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------- 中文二元分词（bigram） ----------------

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_ASCII_TOKEN = re.compile(r"[a-z0-9]+")


def seg_text(s: str) -> str:
    """把文本切成可检索词元：汉字段按相邻二元词展开；其余按字母数字词。空格连接。

    例：'记忆系统 TurboTrain-训练' → '记忆 忆系 系统 turbotrain 训练'
    """
    if not s:
        return ""
    s = str(s).lower()
    out = []
    i, n = 0, len(s)
    while i < n:
        if _CJK.match(s[i]):
            j = i
            while j < n and _CJK.match(s[j]):
                j += 1
            run = s[i:j]
            if len(run) == 1:
                out.append(run)
            else:
                for k in range(len(run) - 1):
                    out.append(run[k:k + 2])
            i = j
        else:
            m = _ASCII_TOKEN.match(s, i)
            if m:
                out.append(m.group(0))
                i = m.end()
            else:
                i += 1
    return " ".join(out)


def build_match_phrase(q: str):
    """FTS5 短语匹配串（全词相邻，精度高）。词元为空返回 None。"""
    toks = seg_text(q).split()
    if not toks:
        return None
    return '"' + " ".join(toks) + '"'


def build_match_and(q: str):
    """FTS5 全词与匹配串（召回高，有假阳性可能）。词元为空返回 None。"""
    toks = seg_text(q).split()
    if not toks:
        return None
    return " AND ".join('"%s"' % t for t in toks)


def build_match_or(q: str):
    """FTS5 任一词匹配串（最后的召回兜底）。词元为空返回 None。"""
    toks = seg_text(q).split()
    if not toks:
        return None
    return " OR ".join('"%s"' % t for t in toks)


_PUNCT = re.compile(
    r"""[\s,，。.!！?？:：;；'"“”‘’()（）\[\]【】{}<>《》·\-—_/\\|@#$%^&*+=~`、]+"""
)


def normalize_text(s: str) -> str:
    """去空白标点 + 小写，用于查重比对。"""
    return _PUNCT.sub("", (s or "").lower())


# ---------------- scope 归一（采集 / 提炼 / 钩子共用口径，评审 M10） ----------------

_SCOPE_JUNK = {"新建文件夹", "new-chat", "new-chat-2", "new-folder", "new folder",
               "administrator", "_downloads", "codex", "claude", "tmp", "temp",
               "desktop", "下载"}


def norm_scope(s) -> str:
    """项目名归一：垃圾目录名/空 → 'general'。"""
    s = (s or "").strip()
    if not s or s.lower() in _SCOPE_JUNK:
        return "general"
    return s
