# -*- coding: utf-8 -*-
"""eai chat：跟管家直接对话（本机大模型 + 记忆）。
对话内容自动存成 inbox 原料 → 等夜间固结进永久记忆。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import persona, util
from .extract import _post_ollama
from .recall import recall as recall_fn
from .store import MemoryStore


def _sys_prompt() -> str:
    ident = persona.identity_excerpt(12)
    master = ""
    mp = persona.core_dir() / "master.md"
    if mp.exists():
        master = mp.read_text(encoding="utf-8")[:1800]
    return (f"你是主人的私人管家（本地长期记忆系统 EAI）。\n\n【你的守则】\n{ident}\n\n"
            f"【你已经知道的主人画像】\n{master}\n\n"
            "要求：零客套、短句、直白；不确定时以【相关记忆】为准；坏消息也直说。")


def _dump_convo(convo: list, scope: str | None) -> str:
    d = util.memory_dir() / "inbox" / "chat"
    d.mkdir(parents=True, exist_ok=True)
    stamp = util.now_str().replace("-", "").replace(" ", "_").replace(":", "")[:15]
    p = d / f"chat-{stamp}.md"
    body = "\n\n".join(f"**{r}**：{t[:600]}" for r, t in convo)
    p.write_text(f"# 管家对话 · {util.now_str()}\n- 项目：{scope or 'general'}\n\n## 对话\n\n{body}\n",
                 encoding="utf-8")
    sha = hashlib.sha1(p.read_bytes()).hexdigest()
    idx = util.memory_dir() / "inbox" / "index.jsonl"
    with open(idx, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "path": f"chat/{p.name}", "source": "chat", "session_id": p.stem,
            "project": scope or "general", "cwd": "", "date": util.now_str()[:10],
            "sha1": sha, "n_user": sum(1 for r, _ in convo if r == "主人"),
            "ts": util.now_str(),
        }, ensure_ascii=False) + "\n")
    return p.name


def main(scope: str | None = None, model: str = "quality") -> int:
    store = MemoryStore()
    cfg = store.cfg
    model_name = (cfg.get("ollama_models") or {}).get(model, "qwen2.5:3b")
    print(f"管家在（模型 {model_name}，记忆已接）。")
    print("提示：/记住 xxx 直接入记忆；/查 xxx 查记忆；/退出 结束（对话会存档，夜间自动固结）")
    sys_p = _sys_prompt()
    convo = []

    while True:
        try:
            q = input("\n我: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q in ("/退出", "/quit", "/exit", "exit"):
            break
        if q.startswith("/记住"):
            t = q[len("/记住"):].strip(" ：:")
            if t:
                rec = store.add({"kind": "fact", "text": t, "scope": scope or "general",
                                 "source": {"how": "chat"}})
                print(f"管家: 记住了（{rec['action']}）。")
                convo.append(("主人", f"（直接记住）{t}"))
            continue
        if q.startswith("/查"):
            t = q[len("/查"):].strip(" ：:")
            hits = recall_fn(store, t, k=5, scope=scope)
            if not hits:
                print("管家: （没有相关记忆）")
            for i, h in enumerate(hits, 1):
                print(f"  {i}. [{h['kind']}·{h['ts'][:10]}] {h['text'][:100]}")
            continue

        hits = recall_fn(store, q, k=5, scope=scope)
        mem_block = "\n".join(f"- [{h['kind']}] {h['text']}" for h in hits) or "（无）"
        user_msg = f"【相关记忆】\n{mem_block}\n\n【主人说】\n{q}"
        try:
            reply = _post_ollama(cfg, model_name, user_msg, system=sys_p, timeout=300)
        except Exception as ex:
            print(f"管家: （模型不可用：{ex}；可先 /记住 或 /查）")
            continue
        print(f"管家: {reply.strip()}")
        convo.append(("主人", q))
        convo.append(("管家", reply.strip()))

    if convo:
        name = _dump_convo(convo, scope)
        print(f"（对话已存档 {name}，夜间自动固结进永久记忆）")
    store.close()
    return 0
