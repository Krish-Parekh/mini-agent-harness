import math
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

out_dir = sys.argv[1]

n, passed = 89, 62
ours = 100 * passed / n
ours_ci = 100 * 1.96 * math.sqrt((passed / n) * (1 - passed / n) / n)

rows = [
    ("MiniAgent", "Sonnet 5.5", ours, ours_ci, True),
    ("Simplai Agent", "Sonnet 4.6", 53.4, 2.8, False),
    ("CAMEL-AI", "Sonnet 4.5", 46.5, 2.4, False),
    ("Goose", "Sonnet 4.5", 43.1, 2.6, False),
    ("Terminus 2", "Sonnet 4.5", 42.8, 2.8, False),
    ("MAYA-V2", "Sonnet 4.5", 42.7, None, False),
    ("OpenHands", "Sonnet 4.5", 42.6, 2.8, False),
    ("Mini-SWE-Agent", "Sonnet 4.5", 42.5, 2.8, False),
    ("Claude Code", "Sonnet 4.5", 40.1, 2.9, False),
]

themes = {
    "light": dict(
        primary="#0b0b0b", secondary="#52514e", muted="#898781", grid="#e1e0d9",
        axis="#c3c2b7", accent="#2a78d6", other="#a9a8a1", whisker="#52514e",
    ),
    "dark": dict(
        primary="#f0efec", secondary="#c3c2b7", muted="#898781", grid="#2c2c2a",
        axis="#383835", accent="#3987e5", other="#6f6e69", whisker="#c3c2b7",
    ),
}

plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "sans-serif"]


def bar(ax, y, value, height, color):
    rx, ry = 0.6, 0.09
    top, bottom = y + height / 2, y - height / 2
    points = [(0, bottom), (value - rx, bottom)]
    for a in range(-90, 1, 10):
        t = math.radians(a)
        points.append((value - rx + rx * math.cos(t), bottom + ry + ry * math.sin(t)))
    for a in range(0, 91, 10):
        t = math.radians(a)
        points.append((value - rx + rx * math.cos(t), top - ry + ry * math.sin(t)))
    points.append((0, top))
    ax.add_patch(Polygon(points, closed=True, linewidth=0, facecolor=color))


for name, t in themes.items():
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    height = 0.56
    for i, (harness, model, value, ci, mine) in enumerate(rows):
        y = len(rows) - 1 - i
        bar(ax, y, value, height, t["accent"] if mine else t["other"])
        if ci:
            ax.plot([value - ci, value + ci], [y, y], color=t["whisker"], linewidth=1.2, solid_capstyle="butt", zorder=3)
            for x in (value - ci, value + ci):
                ax.plot([x, x], [y - 0.12, y + 0.12], color=t["whisker"], linewidth=1.2, zorder=3)
        end = value + (ci or 0)
        ax.text(end + 1.2, y, f"{value:.1f}%", va="center", ha="left",
                fontsize=10.5, color=t["primary"], fontweight="bold" if mine else "normal")
        ax.text(-1.5, y + 0.13, harness, va="center", ha="right", fontsize=10.5,
                color=t["primary"], fontweight="bold" if mine else "normal")
        ax.text(-1.5, y - 0.2, model, va="center", ha="right", fontsize=8.5, color=t["secondary"])

    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_yticks([])
    ax.set_xticks(range(0, 101, 20))
    ax.set_xticklabels([f"{x}%" for x in range(0, 101, 20)], fontsize=9, color=t["muted"])
    ax.tick_params(axis="x", length=0, pad=6)
    ax.grid(axis="x", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])

    fig.text(0.015, 0.965, "Terminal-Bench 2.0 · Claude Sonnet harnesses", fontsize=13.5,
             fontweight="bold", color=t["primary"], ha="left", va="top")
    fig.text(0.015, 0.905,
             "Resolution rate with 95% interval. MiniAgent: one run (k=1), Oct 2026. "
             "Others: tbench.ai leaderboard (k=5).",
             fontsize=9, color=t["secondary"], ha="left", va="top")

    fig.subplots_adjust(left=0.2, right=0.97, top=0.83, bottom=0.08)
    suffix = "" if name == "light" else "-dark"
    fig.savefig(f"{out_dir}/terminal-bench{suffix}.png", transparent=True)
    plt.close(fig)
