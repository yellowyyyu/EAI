# -*- coding: utf-8 -*-
"""
图 1「EAI 三层记忆架构」矢量框图
生成：fig1_architecture.pdf / fig1_architecture.png（与本脚本同目录）

版式：画布宽 14 cm，坐标 1 单位 = 1 cm（物理尺寸精确控制）
字体：中文 = 宋体（simsun.ttc），西文 = Times New Roman；宋体无粗体，标题用描边模拟加粗
配色：黑/深灰线框白底，唯一浅色填充 #E9EEF4（仅用于三层记忆）
自检：文字不出框 / 文字两两不重叠 / 不越界，任何一项不过会在输出里报告
运行：python fig1_architecture.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.path import Path as MPath

# ---------- 字体 ----------
fm.fontManager.addfont(r"C:\Windows\Fonts\simsun.ttc")
fm.fontManager.addfont(r"C:\Windows\Fonts\times.ttf")
plt.rcParams.update({
    "font.family": ["Times New Roman", "SimSun"],
    "pdf.fonttype": 42,
})

# ---------- 常量 ----------
W, H = 14.0, 12.9            # 画布（cm）
M = 0.6                      # 四周留白（cm）
CW = W - 2 * M               # 内容宽
CX = W / 2                   # 中轴
INK = "#111111"              # 近黑：线框与文字
NOTE = "#333333"             # 深灰：小字注
FILL = "#E9EEF4"             # 唯一浅色填充（三层记忆）
LW = 0.9                     # 常规框线（pt）
LW_BIG = 1.2                 # 引擎大盒框线
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


def boxed_txt(x, y, w, h, s, size=9.0, color=INK, bold=False, fill="white", lw=LW):
    r = box(x, y, w, h, fill=fill, lw=lw)
    t = txt(x + w / 2, y + h / 2, s, size=size, color=color, bold=bold)
    boxed.append((t, r))
    return t


def arrow(p, q, ms=15.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>,head_length=0.5,head_width=0.18",
                                 mutation_scale=ms, lw=LW, color=INK,
                                 shrinkA=0, shrinkB=0, zorder=1))


def polyarrow(pts, ms=15.0):
    ax.add_patch(FancyArrowPatch(path=MPath(pts),
                                 arrowstyle="-|>,head_length=0.5,head_width=0.18",
                                 mutation_scale=ms, lw=LW, color=INK, zorder=1))


# ================= 排版（自顶向下） =================
y = H

# ---- 标题 ----
y -= M + 0.20
txt(CX, y, "EAI 三层记忆架构", size=10.5, bold=True)
y -= 0.21 + 0.50

# ---- L1 引擎（随时可换） ----
l1w, l1h = 8.2, 1.32
r1 = box(CX - l1w / 2, y - l1h, l1w, l1h, lw=LW_BIG)
t1a = txt(CX, y - l1h / 2 + 0.30, "引擎（随时可换）：Claude · Codex · 本地模型", size=9.5)
t1b = txt(CX, y - l1h / 2 - 0.32, "换引擎，不换灵魂", size=8.5, color=NOTE)
boxed += [(t1a, r1), (t1b, r1)]
y -= l1h + 1.05

# ---- L2 五个接入面（薄壳） ----
y -= 0.20
txt(CX, y, "五个接入面（薄壳）", size=9.5, bold=True)
y -= 0.20 + 0.12
l2h, l2g = 0.85, 0.25
l2w = (CW - 4 * l2g) / 5
for i, s in enumerate(["开场简报", "按需回忆", "MCP 工具", "命令行", "每日固结"]):
    boxed_txt(M + i * (l2w + l2g), y - l2h, l2w, l2h, s)
y -= l2h + 1.15

# ---- L3 三循环（记录 → 固结 → 回忆，带回流线） ----
l3h, l3g = 0.90, 0.90
l3w = (CW - 2 * l3g) / 3
l3x = [M + i * (l3w + l3g) for i in range(3)]
ym = y - l3h / 2
for x0, s in zip(l3x, ["记录 · 白天", "固结 · 夜里", "回忆 · 随问随取"]):
    boxed_txt(x0, y - l3h, l3w, l3h, s)
arrow((l3x[0] + l3w, ym), (l3x[1], ym))
arrow((l3x[1] + l3w, ym), (l3x[2], ym))
# 回流线：回忆 → 记录（构成回路）
cx_rec = l3x[0] + l3w / 2
cx_mem = l3x[2] + l3w / 2
y_dip = y - l3h - 0.50
polyarrow([(cx_mem, y - l3h), (cx_mem, y_dip), (cx_rec, y_dip), (cx_rec, y - l3h)])
y -= l3h + 0.50 + 0.55

# ---- L4 三层记忆（上窄下宽） ----
l4h, l4g = 0.85, 0.16
for s, w in [("核心 core/（身份 · 主人画像 · 承诺）", 6.8),
             ("语义 memory.db（事实 · 偏好 · 纠错 · 决定 · 承诺 · 项目）", 9.8),
             ("情景 journal/（原始经历 · 只增不改 · 永不删除）", 12.8)]:
    boxed_txt(CX - w / 2, y - l4h, w, l4h, s, fill=FILL)
    y -= l4h + l4g
y += l4g

# ---- 底部小字 ----
y -= 0.20 + 0.55
txt(CX, y, "全本地 · 永不物理删除 · 检索只用 top-k（注入量恒定）", size=8.5, color=NOTE)

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

print("图1 自检：", "通过（文字不出框 / 无重叠 / 不越界）" if not problems else "发现问题 ——")
for p in problems:
    print("  -", p)

# ================= 输出 =================
out = Path(__file__).resolve().parent
fig.savefig(out / "fig1_architecture.pdf")
fig.savefig(out / "fig1_architecture.png", dpi=300)
print("已生成：", out / "fig1_architecture.pdf")
print("已生成：", out / "fig1_architecture.png")
