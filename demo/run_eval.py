# -*- coding: utf-8 -*-
"""评测：读 demo/eval_set.jsonl → recall(k=6) → 命中率报告 demo/eval_report.md。

用法：python demo/run_eval.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    from eai.store import MemoryStore
    from eai import recall as recall_mod

    store = MemoryStore()
    cases = [json.loads(l) for l in
             (ROOT / "demo" / "eval_set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    hits_n, total = 0, 0
    detail = []
    for c in cases:
        q = c["query"]
        try:
            res = recall_mod.recall(store, q, k=6, scope=c.get("scope"), reinforce=False)
        except Exception as ex:
            detail.append((q, "崩", f"EXC {ex}"))
            total += 1
            continue
        total += 1
        exp = c.get("expect_any") or []
        ok = bool(c.get("allow_empty"))
        if not ok:
            for r in res:
                blob = (r["title"] + " " + r["text"]).lower()
                if any(e.lower() in blob for e in exp):
                    ok = True
                    break
        hits_n += 1 if ok else 0
        top = res[0]["text"][:60] if res else "（空）"
        detail.append((q, "✓" if ok else "✗", top))

    out = [f"# 记忆检索评测报告（k=6）", "",
           f"命中率：{hits_n}/{total} = {hits_n / max(1, total) * 100:.0f}%", "",
           "| 查询 | 结果 | 第一条命中 |", "|---|---|---|"]
    for q, s, t in detail:
        out.append(f"| {q} | {s} | {t} |")
    text = "\n".join(out)
    print(text)
    (ROOT / "demo" / "eval_report.md").write_text(text, encoding="utf-8")
    store.close()


if __name__ == "__main__":
    main()
