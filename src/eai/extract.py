# -*- coding: utf-8 -*-
"""提炼器：经历文本 → 候选记忆条目。后端：本机 Ollama（默认）/ claude 头-less / 纯规则兜底。"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request

from . import util

SYSTEM_PROMPT = """你是"记忆固结器"，负责把一段经历记录提炼成值得长期保留的记忆条目。
输入：一段对话或工作记录（可能是主人与助手的交流、项目日志、随手记录）。
输出：只输出一个 JSON 数组，不要任何其他文字。
每个元素格式：
{"kind":"fact|preference|correction|decision|promise|project|skill|episode",
 "title":"一句话标题（20字内）",
 "text":"记忆正文，一两句话，说清楚就好",
 "importance":0.0到1.0之间,
 "scope":"项目名或 general",
 "entities":["涉及的人/项目/工具/文件名"]}
规则：
1. 主人明确提出要求、纠错、表态偏好的，kind 用 preference 或 correction，importance 至少 0.8。
2. 定下来的事用 decision；答应要做的事用 promise；项目进展用 project；workflow/命令技巧用 skill。
3. 普通寒暄、临时闲聊、没有长期价值的信息不要记；整段都不值得记就输出 []。宁少勿滥。
4. 一段里同类信息合并成一条。
5. 正文不要写"用户说""助手说"，直接写事实本身。用中文。
6. 助手自称"已完成/已修复/已跑通/测试全绿"的内容不要当事实；看不到验证证据就不记，或记为 project 并注明"待验证"。
7. 若这段只是对管家简报/记忆系统输出的复述（出现"管家简报""相关记忆"等系统字样），跳过不记。"""

VERDICT_PROMPT = """你是记忆管理员。下面是一条新记忆和一条已有记忆。判断两者关系，只输出一个词：
same（同一件事，只是说法不同）/ update（同一件事，新信息更新旧信息）/
conflict（相互矛盾，新的为准）/ different（不同的事）
新记忆：{new}
已有记忆：{old}"""

USER_TEMPLATE = "项目：{scope}\n日期：{date}\n来源：{source}\n----\n{text}"


# ---------------- 后端 ----------------

def _post_ollama(cfg: dict, model: str, user_text: str, system: str = SYSTEM_PROMPT,
                 timeout: int = 300) -> str:
    url = cfg["ollama_url"].rstrip("/") + "/api/chat"
    body = json.dumps({
        "model": model,
        "stream": False,
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕系统代理，本机直连
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("message") or {}).get("content", "")


def _parse_json_array(s: str) -> list:
    if not s:
        return []
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    a, b = s.find("["), s.rfind("]")
    if a < 0 or b <= a:
        return []
    try:
        arr = json.loads(s[a:b + 1])
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


def _clean(raw_list: list, cfg: dict | None = None) -> list:
    defaults = ((cfg or util.load_config()).get("importance_defaults") or {})
    out = []
    for c in raw_list:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        kind = str(c.get("kind") or "fact").strip()
        if kind not in util.KINDS:
            kind = "fact"
        try:
            imp = float(c.get("importance"))
        except (TypeError, ValueError):
            imp = float(defaults.get(kind, 0.5))  # 缺省按 kind 默认（评审 I3）
        ents = c.get("entities") or []
        if isinstance(ents, str):
            ents = [ents]
        ents = [str(e)[:40] for e in ents if str(e).strip()][:10]
        # 标题清洗：去 [时间戳] 前缀、去 "1." "2、" 之类编号
        title = str(c.get("title") or "").replace("\n", " ").strip()
        title = re.sub(r"^[\[\(（]\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[T\s][^\])）]*[\])）]\s*", "", title)
        title = re.sub(r"^[（(]?\d{1,2}\s*[\.、\)）:：]\s*(?!\d)", "", title)
        title = title.strip()
        if len(title) < 4:
            title = text[:24]
        out.append({
            "kind": kind,
            "title": title[:40],
            "text": text[:400],
            "importance": min(1.0, max(0.0, imp)),
            "scope": str(c.get("scope") or "general")[:40],
            "entities": ents,
        })
    return out


def _chunk(text: str, size: int = 4000, overlap: int = 200) -> list:
    if len(text) <= size:
        return [text]
    chunks, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):
            nl = text.rfind("\n", i + size // 2, end)
            if nl > i:
                end = nl
        chunks.append(text[i:end])
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return chunks


_RULES = [
    (re.compile(r"不要|别再|别用|以后|必须|记住|别忘了|不对|错了|改成|禁止|不能"), "correction", 0.9),
    (re.compile(r"我不喜欢|我喜欢|偏好|习惯|讨厌|最好"), "preference", 0.8),
    (re.compile(r"定了|就这个|拍板|批准|决定"), "decision", 0.8),
    (re.compile(r"答应|承诺|记得提醒|提醒我|别忘"), "promise", 0.8),
]


def rules_extract(text: str, context: dict | None = None) -> list:
    """纯规则兜底（离线可用）。宁缺毋滥：只在句子明显带指令/偏好信号时收录。"""
    context = context or {}
    out, seen = [], set()
    for sent in re.split(r"[。！？!?\n]+", text or ""):
        sent = sent.strip()
        if len(sent) < 6 or len(sent) > 200:
            continue
        for pat, kind, imp in _RULES:
            if pat.search(sent):
                key = util.normalize_text(sent)[:40]
                if key in seen:
                    break
                seen.add(key)
                out.append({
                    "kind": kind, "title": sent[:20], "text": sent[:160],
                    "importance": min(imp, 0.6),  # 规则条目重要度封顶，防噪声高优入库（评审 M7）
                    "scope": context.get("scope", "general"), "entities": [],
                })
                break
    return out


# ---------------- 对外 ----------------

def extract_candidates(text: str, context: dict | None = None, backend: str = "auto",
                       model: str = "fast", cfg: dict | None = None) -> list:
    """提炼候选记忆。任何失败都退到规则兜底，绝不抛异常。返回 list[dict]。"""
    cfg = cfg or util.load_config()
    context = context or {}
    backend = backend if backend and backend != "auto" else cfg.get("backend", "ollama") or "auto"
    scope = context.get("scope") or "general"
    date = context.get("date") or util.now_str()[:10]
    source = context.get("source") or ""

    chain = []
    if backend == "claude":
        chain = ["claude", "rules"]
    elif backend == "rules":
        chain = ["rules"]
    elif backend == "ollama":
        chain = ["ollama", "rules"]
    else:  # auto
        chain = ["ollama", "rules"]

    for b in chain:
        try:
            if b == "ollama":
                mkey = model if model in ("fast", "quality") else "fast"
                model_name = (cfg.get("ollama_models") or {}).get(mkey, "qwen2.5:3b")
                out = []
                for chunk in _chunk(text):
                    user = USER_TEMPLATE.format(scope=scope, date=date, source=source, text=chunk)
                    content = _post_ollama(cfg, model_name, user)
                    arr = _parse_json_array(content)
                    tries = 0
                    while not arr and content.strip() and tries < 2:
                        tries += 1
                        content = _post_ollama(cfg, model_name, user + "\n（提醒：只输出 JSON 数组）")
                        arr = _parse_json_array(content)
                    out.extend(arr)
                return _clean(out, cfg)
            if b == "claude":
                user = USER_TEMPLATE.format(scope=scope, date=date, source=source, text=text[:4000])
                r = subprocess.run(
                    ["claude", "-p", SYSTEM_PROMPT + "\n\n" + user],
                    capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="replace",
                )
                return _clean(_parse_json_array(r.stdout or ""), cfg)
            if b == "rules":
                return rules_extract(text, context)
        except Exception:
            continue
    return []


def verdict_llm(new_text: str, old_text: str, cfg: dict | None = None, model: str = "fast") -> str:
    """仲裁新旧两条记忆的关系。返回 same/update/conflict/different，失败返回 ''。"""
    cfg = cfg or util.load_config()
    try:
        mkey = model if model in ("fast", "quality") else "fast"
        model_name = (cfg.get("ollama_models") or {}).get(mkey, "qwen2.5:3b")
        user = VERDICT_PROMPT.format(new=new_text[:300], old=old_text[:300])
        content = _post_ollama(cfg, model_name, user, system="只回答一个词。", timeout=120)
        c = (content or "").strip().lower()
        m = re.search(r"\b(same|update|conflict|different)\b", c)
        if m:
            return m.group(1)
        zh = {"相同": "same", "同一": "same", "更新": "update",
              "矛盾": "conflict", "冲突": "conflict", "不同": "different"}
        for k, v in zh.items():
            if k in c:
                return v
    except Exception:
        pass
    return ""
