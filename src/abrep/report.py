"""Charts for the README, read from results/results.json.

Usage:  python -m abrep.report
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
CONTROL, TREAT, INK, MUTE, GRID = "#2f6fd0", "#b07a1c", "#1f2328", "#59636e", "#e6e8eb"

plt.rcParams.update({
    "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": MUTE, "xtick.color": MUTE,
    "ytick.color": MUTE, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlesize": 12,
})


def fill_distribution(r, out):
    p = r["primary_fill_rate"]
    edges = p["hist_edges"]
    # Few SKUs fall below 50%: pool them in one bin, keep 5-point bins above.
    i0 = 10
    labels = ["<50%"] + [f"{int(round(edges[i]*100))}–{int(round(edges[i+1]*100))}%" for i in range(i0, len(edges) - 1)]
    c = [sum(p["hist_control"][:i0])] + p["hist_control"][i0:]
    t = [sum(p["hist_treatment"][:i0])] + p["hist_treatment"][i0:]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    w = 0.38
    ax.bar([i - w / 2 - 0.01 for i in x], c, w, color=CONTROL, label="A · min-max rule")
    ax.bar([i + w / 2 + 0.01 for i in x], t, w, color=TREAT, label="B · forecast-based")
    ax.set_xticks(list(x), labels, rotation=0, fontsize=8)
    ax.set_ylabel("SKUs")
    ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    ax.set_title("Fill rate per SKU: B removes most of the badly served tail", loc="left")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def by_abc(r, out):
    ab = r["by_abc"]
    classes = ["A", "B", "C"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.4, 3.2), dpi=160, sharey=True)
    for i, k in enumerate(classes):
        d = ab[k]
        lo, hi = d["ci"]
        a1.plot([lo * 100, hi * 100], [i, i], color=TREAT, lw=2)
        a1.plot(d["diff"] * 100, i, "o", color=TREAT, ms=8, mec="white", mew=2)
        a1.annotate(f'{d["diff"]*100:+.1f} pp', (hi * 100, i), xytext=(6, 0), textcoords="offset points", va="center", color=INK, fontsize=9)
        ch = (d["capital_ratio"] - 1) * 100
        a2.barh(i, ch, 0.42, color=TREAT if ch > 0 else CONTROL)
        a2.annotate(f"{ch:+.0f}%", (ch, i), xytext=(6 if ch > 0 else -6, 0), textcoords="offset points",
                    va="center", ha="left" if ch > 0 else "right", color=INK, fontsize=9)
    for a in (a1, a2):
        a.axvline(0, color=MUTE, lw=1)
        a.xaxis.grid(True, color=GRID); a.set_axisbelow(True)
    a1.set_yticks(range(3), [f"Class {k}" for k in classes]); a1.invert_yaxis()
    a1.set_title("Fill-rate change (95% CI)", loc="left"); a1.set_xlabel("percentage points")
    a2.set_title("Capital change", loc="left"); a2.set_xlabel("% vs control")
    a2.set_xlim(-40, 40)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def main():
    r = json.loads((ROOT / "results" / "results.json").read_text())
    (ROOT / "figures").mkdir(exist_ok=True)
    fill_distribution(r, ROOT / "figures" / "fill_rate_distribution.png")
    by_abc(r, ROOT / "figures" / "effect_by_abc.png")


if __name__ == "__main__":
    main()
