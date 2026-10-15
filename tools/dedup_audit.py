# -*- coding: utf-8 -*-
"""近重复审计与安全并合（拼接式合并无损，评审后 2026-10-15 加）。

用法：
  python tools/dedup_audit.py                # 只报告：同 kind 条目的高覆盖率配对
  python tools/dedup_audit.py --apply        # 把 ≥阈值 的重复对并合（并入旧条，重复者归档）
说明：覆盖率 = 共同词元 / 较短一方词元数；只对同 kind、词元数 ≥8 的条目配对；
      --apply 默认阈值 0.85，保守执行；被并入者走 archive（不物理删除，可考古）。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--min-tokens", type=int, default=8)
    a = ap.parse_args()

    from eai import util
    from eai.store import MemoryStore

    store = MemoryStore()
    rows = store.conn.execute(
        "SELECT id, kind, scope, title, text, importance, use_count, ts "
        "FROM memories WHERE status='active'").fetchall()
    recs = [dict(r) for r in rows]
    for r in recs:
        r["toset"] = set(util.seg_text((r["title"] or "") + " " + r["text"]).split())

    pairs = []
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            A, B = recs[i], recs[j]
            if A["kind"] != B["kind"]:
                continue
            if min(len(A["toset"]), len(B["toset"])) < a.min_tokens:
                continue
            inter = len(A["toset"] & B["toset"])
            cover = inter / min(len(A["toset"]), len(B["toset"]))
            if cover >= 0.70:
                pairs.append((cover, A, B))
    pairs.sort(key=lambda t: -t[0])

    print(f"活跃条目 {len(recs)} 条；覆盖率 ≥0.70 的同 kind 配对 {len(pairs)} 对")
    for cover, A, B in pairs[:40]:
        flag = "→并" if (a.apply and cover >= a.threshold) else "  "
        print(f"[{cover:.2f}]{flag} {A['id']}({A['ts'][:10]}) ≈ {B['id']}({B['ts'][:10]})")
        print(f"    A: {A['text'][:70]}")
        print(f"    B: {B['text'][:70]}")

    if a.apply:
        n = 0
        done = set()
        for cover, A, B in pairs:
            if cover < a.threshold:
                continue
            keep, drop = (A, B) if (A["ts"], A["id"]) <= (B["ts"], B["id"]) else (B, A)
            if drop["id"] in done or keep["id"] in done:
                continue
            store.merge(keep["id"], {"kind": keep["kind"], "text": drop["text"],
                                     "title": drop["title"], "scope": keep["scope"],
                                     "importance": max(keep["importance"], drop["importance"]),
                                     "entities": []})
            store.archive(drop["id"], f"merged-dup->{keep['id']} (cover {cover:.2f})")
            done.add(drop["id"])
            n += 1
        if n:
            from eai import persona
            persona.refresh_persona(store)
        print(f"已并合 {n} 条（并入旧条 + 归档重复者）")
    store.close()


if __name__ == "__main__":
    main()
