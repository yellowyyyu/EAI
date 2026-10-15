# -*- coding: utf-8 -*-
"""提炼质量与速度探针：对样例文本跑 3b(快档) / 27b(质量档)，看候选质量与耗时。

用法：python demo/probe_extract.py [--model fast|quality] [--file demo/sample_real.md]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE = """[2026-09-30 14:02] 继续，把配置改回默认的，我说过多少次了不要动这部分。
[2026-09-30 14:20] 不对，文档结构和引用格式先改，数字对不上先不管。
[2026-10-01 09:12] 以后跑这个项目的脚本都要加 -s 参数。
[2026-10-02 11:40] 跑测试实验，比吞吐和延迟，不要再做训练环境里的那套评估。
[2026-10-02 19:31] 结果图放到项目文件夹里，不要丢桌面。图要矢量图，做完自己检查留白。
[2026-10-03 10:05] 好了，环境调通了，继续训练。这次要跑到误差达标为止，别中途停。
[2026-10-03 22:14] 今天先到这里，明天把新旧版本的对比表做出来，参照上次那个左右对照的样式。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="fast", choices=["fast", "quality"])
    ap.add_argument("--file", default=None)
    a = ap.parse_args()
    text = Path(a.file).read_text(encoding="utf-8") if a.file else SAMPLE
    t0 = time.time()
    from eai import extract
    cands = extract.extract_candidates(
        text, {"scope": "探针", "date": "2026-10-14", "source": "probe"},
        backend="ollama", model=a.model)
    dt = time.time() - t0
    print(f"model={a.model} 用时 {dt:.1f}s 候选 {len(cands)} 条")
    print(json.dumps(cands, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
