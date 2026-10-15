# -*- coding: utf-8 -*-
"""
图 4「普通会话 vs EAI 管家」对照图（矢量框图）
生成：fig4_compare.pdf / fig4_compare.png（与本脚本同目录）

版式：画布宽 14 cm，坐标 1 单位 = 1 cm（物理尺寸精确控制），沿用 fig1/fig2 的字体/线宽/留白标准
左侧：三只相互隔离的会话盒（各注"从零开始"，盒间不连线）；右侧：纵向贯穿的"记忆柱"，
      浅填充 + 描边，柱身竖排标签"永久记忆 EAI\\memory\\"；三条连线由会话盒接入柱身
字体：中文 = 宋体（simsun.ttc），西文 = Times New Roman；宋体无粗体，标题用描边模拟加粗
自检：文字不出框 / 文字两两不重叠 / 不越界
运行：python fig4_compare.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyArrowPatch, Rectangle

# ---------- 字体 ----------
fm.fontManager.addfont(r"C:\Windows\Fonts\simsun.ttc")
fm.fontManager.addfont(r"C:\Windows\Fonts\times.ttf")
plt.rcParams.update({
    "font.family": ["Times New Roman", "SimSun"],
    "pdf.fonttype": 42,
})

# ---------- 常量 ----------
W, H = 14.0, 8.0             # 画布（cm）
M = 0.6                      # 四周留白（cm）
INK = "#111111"              # 近黑：线框与文字
NOTE = "#333333"             # 深灰：小字注
FILL = "#E9EEF4"             # 唯一浅色填充（记忆柱，与 fig1 三层记忆同色）
LW = 0.9                     # 框线（pt）
STROKE = [pe.withStroke(linewidth=0.45, foreground=INK)]   # 宋体无粗体：描边模拟加粗

fig = plt.figure(figsize=(W / 2.54, H / 2.54))
fig.patch.set_facecolor("white")
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")

boxed = []   # [(文字, 所属外框)]，供“文字不出框”自检


def box(x, y, w, h, fill="white", lw=LW):
    r = Rectangle((x, y), w, h, facecolor=fill, edgecolor=INK, linewidth=lw, zorder=2)
    ax.add_patch(r)
    return r


def txt(x, y, s, size=9.0, color=INK, bold=False, rotation=0):
    t = ax.text(x, y, s, fontsize=size, color=color, ha="center", va="center",
                rotation=rotation, zorder=3)
    if bold:
        t.set_path_effects(STROKE)
    return t


def arrow(p, q, ms=15.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>,head_length=0.5,head_width=0.18",
                                 mutation_scale=ms, lw=LW, color=INK,
                                 shrinkA=0, shrinkB=0, zorder=1))


# ================= 排版（自顶向下） =================
y = H

# ---- 标题 ----
y -= M + 0.20
txt(W / 2, y, "普通会话 vs EAI 管家", size=10.5, bold=True)
y -= 0.21 + 0.55
TOP = y                                   # 内容顶：会话 1 盒顶 = 记忆柱顶

# ---- 左侧：三只相互隔离的会话盒（盒间不连线） ----
XL, BW, BH, BG = 0.6, 4.4, 1.25, 0.65
mids = []
for i in range(3):
    r = box(XL, y - BH, BW, BH)
    t1 = txt(XL + BW / 2, y - BH / 2 + 0.29, "会话 %d" % (i + 1), size=9.5)
    t2 = txt(XL + BW / 2, y - BH / 2 - 0.30, "从零开始", size=8.5, color=NOTE)
    boxed += [(t1, r), (t2, r)]
    mids.append(y - BH / 2)
    y -= BH + (BG if i < 2 else 0)
BLOCK_BOTTOM = y                          # 三盒块底

# ---- 底部两行小字（同一基线） ----
note_cy = BLOCK_BOTTOM - 0.39 - 0.20      # 小字中心（距画布底 0.6）
txt(XL + BW / 2, note_cy, "每次归零，互不相识", size=8.5, color=NOTE)

# ---- 右侧：记忆柱（纵向贯穿，浅填充+描边，柱身竖排标签） ----
PL, PW = 9.4, 4.0
PBOT = BLOCK_BOTTOM                       # 柱底 = 会话盒块底（左右两栏底边对齐）
rp = box(PL, PBOT, PW, TOP - PBOT, fill=FILL)
tp = txt(PL + PW / 2, (PBOT + TOP) / 2, "永久记忆 EAI\\memory\\", size=9, rotation=90)
boxed.append((tp, rp))
txt(PL + PW / 2, note_cy, "换引擎，不换灵魂", size=8.5, color=NOTE)

# ---- 三条连线：会话盒 → 记忆柱 ----
for ym in mids:
    arrow((XL + BW, ym), (PL, ym))

# ================= 自检 =================
fig.canvas.draw()
rend = fig.canvas.get_renderer()
problems = []

# 1) 文字不出框（文字与所属外框的四边间距 ≥ 1.5 px）
for t, r in boxed:
    tb, rb = t.get_window_extent(rend), r.get_window_extent(rend)
    for name, d in (("左", tb.x0 - rb.x0), ("右", rb.x1 - tb.x1),
                    ("下", tb.y0 - rb.y0), ("上", rb.y1 - tb.y1)):
        if d < 1.5:
            problems.append(f"出框风险：{t.get_text()!r} 距框{name}边仅 {d:.1f}px")

# 2) 文字两两不重叠
texts = list(ax.texts)
for i in range(len(texts)):
    for j in range(i + 1, len(texts)):
        a = texts[i].get_window_extent(rend)
        b = texts[j].get_window_extent(rend)
        ox = min(a.x1, b.x1) - max(a.x0, b.x0)
        oy = min(a.y1, b.y1) - max(a.y0, b.y0)
        if ox > 1.0 and oy > 1.0:
            problems.append(f"文字重叠：{texts[i].get_text()!r} × {texts[j].get_text()!r}")

# 3) 不越界（距画布边缘 ≥ 7 px ≈ 0.18 cm）
fw, fh = fig.get_size_inches() * fig.dpi
for t in texts:
    b = t.get_window_extent(rend)
    if b.x0 < 7 or b.x1 > fw - 7 or b.y0 < 7 or b.y1 > fh - 7:
        problems.append(f"越界：{t.get_text()!r}")

print("图4 自检：", "通过（文字不出框 / 无重叠 / 不越界）" if not problems else "发现问题 ——")
for p in problems:
    print("  -", p)

# ================= 输出 =================
out = Path(__file__).resolve().parent
fig.savefig(out / "fig4_compare.pdf")
fig.savefig(out / "fig4_compare.png", dpi=300)
print("已生成：", out / "fig4_compare.pdf")
print("已生成：", out / "fig4_compare.png")
