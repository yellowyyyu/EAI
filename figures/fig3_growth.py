# -*- coding: utf-8 -*-
"""fig3 记忆增长曲线：按"事件时间"累计条数（真实历史回放后跑）。

规范（用户偏好）：图内不配 title；除横纵坐标外无冗余文字；中文宋体、英文 TNR；
矢量 PDF + 300dpi PNG；四周留白均匀。右侧/上侧不画边框。
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "eai"))

SIMSUN = r"C:\Windows\Fonts\simsun.ttc"
if Path(SIMSUN).exists():
    font_manager.fontManager.addfont(SIMSUN)
plt.rcParams["font.family"] = ["SimSun"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 9


def main():
    from eai.store import MemoryStore
    store = MemoryStore()
    rows = store.conn.execute(
        """SELECT substr(ts,1,10) d, COUNT(*) n FROM memories
           WHERE status='active' GROUP BY d ORDER BY d"""
    ).fetchall()
    store.close()
    if not rows:
        print("库里没有记忆，先跑固结。")
        return 1

    dates, counts = [], []
    cum = 0
    for r in rows:
        cum += r["n"]
        dates.append(r["d"])
        counts.append(cum)

    fig, ax = plt.subplots(figsize=(5.6, 3.1), dpi=300)
    ax.plot(range(len(dates)), counts, color="#3B6EA5", linewidth=1.4)
    ax.fill_between(range(len(dates)), counts, color="#3B6EA5", alpha=0.10)
    step = max(1, len(dates) // 6)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[i][5:] for i in range(0, len(dates), step)])
    ax.set_xlabel("日期（月-日，会话发生时间）")
    ax.set_ylabel("累计记忆条数")
    ax.annotate(f"{counts[-1]} 条", xy=(len(dates) - 1, counts[-1]),
                xytext=(-6, 8), textcoords="offset points", ha="right", fontsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(ROOT / "figures" / f"fig3_growth.{ext}", bbox_inches="tight")
    print(f"已出图：figures/fig3_growth.pdf / .png（{len(dates)} 个日期点，终值 {counts[-1]} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
