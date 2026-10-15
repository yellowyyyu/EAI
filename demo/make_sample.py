# -*- coding: utf-8 -*-
"""从一份真实转录抽用户发言，产出提炼探针用样例文件。

用法：python demo/make_sample.py <transcript.jsonl> [--out demo/sample_real.md] [--max 60]
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--out", default=str(Path(__file__).parent / "sample_real.md"))
    ap.add_argument("--max", type=int, default=60)
    a = ap.parse_args()

    msgs = []
    for line in Path(a.transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "user" or d.get("isMeta"):
            continue
        m = d.get("message") or {}
        c = m.get("content")
        text = ""
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            text = "\n".join(b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text")
        text = text.strip()
        if not text or text.startswith("<"):
            continue
        msgs.append(f"[{str(d.get('timestamp', ''))[:16]}] {text[:500]}")
        if len(msgs) >= a.max:
            break

    Path(a.out).write_text("# 样例：真实转录用户发言\n\n" + "\n\n".join(msgs) + "\n",
                           encoding="utf-8")
    print(f"{a.transcript} → {a.out}，用户发言 {len(msgs)} 条")


if __name__ == "__main__":
    main()
