# -*- coding: utf-8 -*-
"""
图 2「一天怎么运转」矢量框图
生成：fig2_daily_loop.pdf / fig2_daily_loop.png（与本脚本同目录）

版式：画布宽 14 cm，坐标 1 单位 = 1 cm（物理尺寸精确控制）
     三阶段自上而下（白天 → 夜里 → 清晨），右侧一条回流箭头回到"白天"（次日循环）
字体：中文 = 宋体（simsun.ttc），西文 = Times New Roman；宋体无粗体，标题用描边模拟加粗
配色：黑/深灰线框白底（不用填充色，浅色填充留给图 1）
自检：文字不出框 / 文字两两不重叠 / 不越界；链条盒宽按实测文字宽度自动排版
运行：python fig2_daily_loop.py
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
W, H = 14.0, 8.6             # 画布（cm）
M = 0.6                      # 四周留白（cm）
INK = "#111111"              # 近黑：线框与文字
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


def boxed_txt(x, y, w, h, s, size=9.0, color=INK, bold=False):
    r = box(x, y, w, h)
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


def width_cm(s, size=9.0):
    """在真实画布上实测字符串宽度（cm），只用于排版计算"""
    t = ax.text(0.5, 0.5, s, fontsize=size, alpha=0)
    fig.canvas.draw()
    w = t.get_window_extent(fig.canvas.get_renderer()).width / fig.dpi * 2.54
    t.remove()
    return w


# ================= 先实测文字宽度，定链条与盒子尺寸 =================
CHAIN = ["本机大模型提炼", "查重", "合并/覆盖", "刷新主人画像", "git 留痕"]
w_chain = [width_cm(s) for s in CHAIN]
w_sess = width_cm("会话转录自动进 inbox")
w_rem = width_cm("随手记住（eai remember）")
w_brief = width_cm("我是谁 / 我了解的主人 / 当前项目 / 未兑现承诺 / 相关记忆")

PAD_CHAIN, GAP_CHAIN = 0.20, 0.50
bw = [w + 2 * PAD_CHAIN for w in w_chain]      # 链条各盒宽
COLW = sum(bw) + GAP_CHAIN * (len(bw) - 1)     # 内容栏总宽
X0 = M
COL_CX = X0 + COLW / 2                          # 阶段内容中轴

SPAN = w_brief + 1.10                           # 阶段一/三盒子跨度（左右边缘严格对齐）
GAP_R1 = 0.60                                   # 阶段一两盒之间的间距（中缝对准内容中轴）
r1a = r1b = (SPAN - GAP_R1) / 2                 # 两盒等宽、左右对称（中缝即内容中轴）

# ================= 排版（自顶向下） =================
y = H

# ---- 标题（居中于整幅） ----
y -= M + 0.20
txt(W / 2, y, "一天怎么运转", size=10.5, bold=True)
y -= 0.21 + 0.55

# ---- 阶段一：白天 · 干活 ----
y -= 0.20
txt(COL_CX, y, "白天 · 干活", size=9.5, bold=True)
y -= 0.20 + 0.12
r1h = 0.85
xa = COL_CX - SPAN / 2
boxed_txt(xa, y - r1h, r1a, r1h, "会话转录自动进 inbox")
boxed_txt(xa + r1a + GAP_R1, y - r1h, r1b, r1h, "随手记住（eai remember）")
y1m = y - r1h / 2                               # 阶段一中线（回流入口基准，入口在 +LIFT 处）
y -= r1h

# ---- 阶段二：夜里 21:30 · 固结 ----
arrow((COL_CX, y - 0.07), (COL_CX, y - 0.87))
y -= 0.95
y -= 0.20
txt(COL_CX, y, "夜里 21:30 · 固结", size=9.5, bold=True)
y -= 0.20 + 0.12
xcur = X0
for i, s in enumerate(CHAIN):
    boxed_txt(xcur, y - 0.85, bw[i], 0.85, s)
    if i != len(CHAIN) - 1:
        arrow((xcur + bw[i], y - 0.425), (xcur + bw[i] + GAP_CHAIN, y - 0.425), ms=13)
    xcur += bw[i] + GAP_CHAIN
y -= 0.85

# ---- 阶段三：清晨 · 开场 ----
arrow((COL_CX, y - 0.07), (COL_CX, y - 0.87))
y -= 0.95
y -= 0.20
txt(COL_CX, y, "清晨 · 开场", size=9.5, bold=True)
y -= 0.20 + 0.12
b3 = box(COL_CX - SPAN / 2, y - 1.25, SPAN, 1.25)
t3a = txt(COL_CX, y - 1.25 / 2 + 0.28, "新会话自动加载简报", size=9)
t3b = txt(COL_CX, y - 1.25 / 2 - 0.28,
          "我是谁 / 我了解的主人 / 当前项目 / 未兑现承诺 / 相关记忆", size=9)
boxed += [(t3a, b3), (t3b, b3)]
y3m = y - 1.25 / 2                              # 阶段三中线（回流出口基准，出口在 -LIFT 处）

# ---- 右侧回流箭头：清晨 → 白天（次日再来） ----
LX = W - M                                      # 回流竖线（右侧，与左留白对称）
rx = COL_CX + SPAN / 2                          # 右边缘（阶段一/三盒子的右边）
LIFT = 0.15                                     # 顶/底横线相对盒中线外移，给竖排标签两端留 ≥2mm
polyarrow([(rx, y3m - LIFT), (LX, y3m - LIFT), (LX, y1m + LIFT), (rx, y1m + LIFT)])
lab_x = (max(X0 + COLW, rx) + LX) / 2
txt(lab_x, (y1m + y3m) / 2, "记忆越攒越多，管家越磨越像", size=9, rotation=90)

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

print("图2 自检：", "通过（文字不出框 / 无重叠 / 不越界）" if not problems else "发现问题 ——")
for p in problems:
    print("  -", p)

# ================= 输出 =================
out = Path(__file__).resolve().parent
fig.savefig(out / "fig2_daily_loop.pdf")
fig.savefig(out / "fig2_daily_loop.png", dpi=300)
print("已生成：", out / "fig2_daily_loop.pdf")
print("已生成：", out / "fig2_daily_loop.png")
