# -*- coding: utf-8 -*-
"""A4 验收演示：注入简报长度与记忆总量无关（1k 条 vs 10k 条）。

在临时 EAI_HOME 里造数（不动真库）。
用法：python demo/a4_check.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fill(store, n):
    kinds = ["fact", "project", "preference", "episode", "skill"]
    for i in range(n):
        store.add({
            "kind": kinds[i % len(kinds)],
            "scope": f"项目{i % 20}",
            "title": f"条目{i}",
            "text": f"这是第 {i} 条测试记忆，用于验证简报长度恒定。包含中文关键词 训练 记忆 项目 偏好。",
        }, dedupe=False)


def main():
    tmp = tempfile.mkdtemp(prefix="eai_a4_")
    os.environ["EAI_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "src"))
    from eai import util
    util.ensure_dirs()
    from eai.store import MemoryStore
    from eai.session_brief import build_brief

    store = MemoryStore(Path(tmp) / "memory" / "memory.db")
    (Path(tmp) / "memory" / "core" / "identity.md").write_text(
        "我是主人的管家。守则：诚实、自证、不打扰。", encoding="utf-8")

    sizes = {}
    for n in (1000, 10000):
        need = n - store.counts()["active"]
        if need > 0:
            fill(store, need)
        b = build_brief(project="项目1", store=store)
        sizes[n] = len(b)
        print(f"记忆 {store.counts()['active']} 条 → 简报 {len(b)} 字符")

    ok = (sizes[1000] <= 3500 and sizes[10000] <= 3500
          and abs(sizes[1000] - sizes[10000]) <= 400)
    print("A4 验收：", "通过（两档均 ≤3500 且长度近似恒定）" if ok else "不达标")
    store.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
