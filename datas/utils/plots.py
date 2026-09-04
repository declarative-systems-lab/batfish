"""Plot helpers for evaluation.ipynb (user study figures)."""

from __future__ import annotations

import base64
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.transforms import blended_transform_factory

matplotlib.rcParams.update({
    "font.sans-serif": ["DejaVu Sans", "Arial", "SimHei"],
    "axes.unicode_minus": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

COLOR_WO = "#3A7AB8"
COLOR_WI = "#F2994A"
COLOR_SUS_POS = "#40B8A2"
COLOR_SUS_NEG = "#E74C3C"

COHORTS = ("combined", "academia", "industry")
TASKS = [f"Task {i}" for i in range(1, 5)]
DIFFICULTY = ["easy", "easy", "hard", "hard"]
SUS_POSITIVE = {1, 3, 5, 7, 9}
BOX_WIDTH = 0.10


def _task_labels(ax, x, *, compact=False):
    tf, df = (10, 9) if compact else (22, 20)
    ax.set_xticks(x)
    ax.set_xticklabels([""] * len(x))
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    for i, xi in enumerate(x):
        ax.text(xi, -0.03, f"Task {i + 1}", transform=trans, ha="center", va="top",
                fontsize=tf, fontweight="500", fontname="Times New Roman")
        ax.text(xi, -0.10, f"({DIFFICULTY[i]})", transform=trans, ha="center", va="top",
                fontsize=df, fontweight="500", fontname="Times New Roman")


def _draw_box(ax, series, positions, color, alpha, hatch=None, flier_alpha=1.0):
    bp = ax.boxplot(
        series, positions=positions, widths=BOX_WIDTH * 0.6,
        patch_artist=True, showmeans=True, meanline=True,
        boxprops=dict(facecolor=color, alpha=alpha, edgecolor=color, linewidth=1.0),
        medianprops=dict(color="black", linewidth=1.5),
        meanprops=dict(color="red", linestyle="--", linewidth=1.5),
        whiskerprops=dict(color=color), capprops=dict(color=color),
        flierprops=dict(marker="o", markerfacecolor=color, markeredgecolor=color,
                        markersize=5, alpha=flier_alpha),
    )
    if hatch:
        old = matplotlib.rcParams.get("hatch.linewidth", 1.0)
        matplotlib.rcParams["hatch.linewidth"] = 3.0
        for patch in bp["boxes"]:
            patch.set_hatch(hatch)
            patch.set_edgecolor("white")
        matplotlib.rcParams["hatch.linewidth"] = old


def _style_y(ax, *, compact=False):
    fs = 9 if compact else 24
    ax.tick_params(axis="y", labelsize=fs)
    for lb in ax.get_yticklabels():
        lb.set_fontweight("500")
        lb.set_fontname("Times New Roman")


def _save(fig, stem: Path):
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def _show_saved_figures(stems: list[Path], titles: list[str]):
    """Preview saved figures in the notebook (PNG; PDF embed is blocked in VS Code/Cursor)."""
    from IPython.display import HTML, display

    parts = ['<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;">']
    for stem, title in zip(stems, titles):
        png = stem.with_suffix(".png")
        pdf = stem.with_suffix(".pdf")
        if not png.exists():
            continue
        b64 = base64.b64encode(png.read_bytes()).decode()
        pdf_note = f' <span style="color:#666;font-size:0.85em;">({pdf.name})</span>' if pdf.exists() else ""
        parts.append(
            f'<div style="flex:1;min-width:280px;">'
            f'<p style="margin:0 0 4px;font-weight:600;text-transform:capitalize;">'
            f"{title}{pdf_note}</p>"
            f'<img src="data:image/png;base64,{b64}" style="width:100%;height:auto;" '
            f'alt="{title}"/>'
            f"</div>"
        )
    parts.append("</div>")
    if len(parts) > 2:
        display(HTML("".join(parts)))


def _draw_accuracy_ax(ax, wo, wi, *, compact=False, ylabel=True):
    x = np.arange(4) * 0.30
    w = BOX_WIDTH
    _draw_box(ax, wo, [xi - w / 2 for xi in x], COLOR_WO, 0.7)
    _draw_box(ax, wi, [xi + w / 2 for xi in x], COLOR_WI, 1.0, hatch="/")
    if ylabel:
        ax.set_ylabel("Accuracy (points)", fontsize=11 if compact else 26,
                      fontweight="500", fontname="Times New Roman")
    ax.set_ylim(-0.2, 3.5)
    ax.set_yticks([0, 1, 2, 3])
    _task_labels(ax, x, compact=compact)
    _style_y(ax, compact=compact)
    ax.set_xlim(x[0] - w - 0.05, x[-1] + w + 0.05)
    ax.grid(axis="y", alpha=0.3)
    legend = ax.get_legend()
    if legend is not None:
        legend.remove()


def _draw_time_ax(ax, wo_min, wi_min, *, compact=False, ylabel=True):
    x = np.arange(4) * 0.30
    w = BOX_WIDTH
    _draw_box(ax, wo_min, [xi - w / 2 for xi in x], COLOR_WO, 0.7)
    _draw_box(ax, wi_min, [xi + w / 2 for xi in x], COLOR_WI, 1.0, hatch="/")
    if ylabel:
        ax.set_ylabel("Time (minutes)", fontsize=11 if compact else 26,
                      fontweight="500", fontname="Times New Roman")
    ax.set_yticks([0, 5, 10, 15, 20, 25])
    ax.set_ylim(-1, 26)
    _task_labels(ax, x, compact=compact)
    _style_y(ax, compact=compact)
    ax.set_xlim(x[0] - w - 0.05, x[-1] + w + 0.05)
    ax.grid(axis="y", alpha=0.3)
    legend = ax.get_legend()
    if legend is not None:
        legend.remove()


def _draw_sus_ax(ax, sus_plot_df, *, compact=False, ylabel=True):
    x = np.arange(len(sus_plot_df)) * 0.15
    w = 0.08
    old = matplotlib.rcParams.get("hatch.linewidth", 1.0)
    matplotlib.rcParams["hatch.linewidth"] = 3.0
    for i, row in enumerate(sus_plot_df.itertuples()):
        pos = row.polarity == "positive"
        color = COLOR_SUS_POS if pos else COLOR_SUS_NEG
        alpha = 1.0 if pos else 0.7
        bp = ax.boxplot(
            [row.values], positions=[x[i]], widths=w,
            patch_artist=True, showmeans=True, meanline=True,
            boxprops=dict(facecolor=color, alpha=alpha, edgecolor=color, linewidth=1.0),
            medianprops=dict(color="black", linewidth=1.5),
            meanprops=dict(color="red", linestyle="--", linewidth=1.5),
            whiskerprops=dict(color=color), capprops=dict(color=color),
            flierprops=dict(marker="o", markerfacecolor=color, markeredgecolor=color,
                            markersize=5, alpha=0.5),
        )
        if pos:
            for patch in bp["boxes"]:
                patch.set_hatch("/")
                patch.set_edgecolor("white")
    matplotlib.rcParams["hatch.linewidth"] = old
    if ylabel:
        ax.set_ylabel("Score(s)", fontsize=11 if compact else 26,
                      fontweight="500", fontname="Times New Roman")
    xfs = 9 if compact else 22
    ax.set_xticks(x)
    ax.set_xticklabels(sus_plot_df["question"], rotation=45, ha="center",
                       fontsize=xfs, fontweight="500", fontname="Times New Roman")
    _style_y(ax, compact=compact)
    ax.set_ylim(0.5, 5.5)
    ax.set_xlim(x[0] - w - 0.1, x[-1] + w + 0.1)
    ax.grid(axis="y", alpha=0.3)
    legend = ax.get_legend()
    if legend is not None:
        legend.remove()


def _sus_df(d):
    rows = []
    for q in range(1, 11):
        if q not in d["sus_scores"]:
            continue
        rows.append({
            "question": f"Q{q}",
            "polarity": "positive" if q in SUS_POSITIVE else "negative",
            "values": d["sus_scores"][q],
        })
    return pd.DataFrame(rows)


def plot_all_accuracy(data_by_cohort, fig_dir: Path, cohorts=COHORTS, *, preview=True):
    stems = []
    for cohort in cohorts:
        d = data_by_cohort[cohort]
        wo = [d["control_scores"][i] for i in range(1, 5)]
        wi = [d["experimental_scores"][i] for i in range(1, 5)]
        fig, ax = plt.subplots(figsize=(8, 6))
        _draw_accuracy_ax(ax, wo, wi)
        fig.subplots_adjust(bottom=0.22)
        plt.tight_layout()
        stem = fig_dir / f"fig-userstudy-accuracy-{cohort}"
        _save(fig, stem)
        stems.append(stem)
    if preview:
        _show_saved_figures(stems, list(cohorts))
    return stems


def plot_all_time(data_by_cohort, fig_dir: Path, cohorts=COHORTS, *, preview=True):
    stems = []
    for cohort in cohorts:
        d = data_by_cohort[cohort]
        wo = [[t / 60.0 for t in d["control_times"][i]] for i in range(1, 5)]
        wi = [[t / 60.0 for t in d["experimental_times"][i]] for i in range(1, 5)]
        fig, ax = plt.subplots(figsize=(8, 6))
        _draw_time_ax(ax, wo, wi)
        fig.subplots_adjust(bottom=0.22)
        plt.tight_layout()
        stem = fig_dir / f"fig-userstudy-time-{cohort}"
        _save(fig, stem)
        stems.append(stem)
    if preview:
        _show_saved_figures(stems, list(cohorts))
    return stems


def plot_all_sus(data_by_cohort, fig_dir: Path, cohorts=COHORTS, *, preview=True):
    stems = []
    for cohort in cohorts:
        sdf = _sus_df(data_by_cohort[cohort])
        fig, ax = plt.subplots(figsize=(8, 6))
        _draw_sus_ax(ax, sdf)
        plt.tight_layout()
        stem = fig_dir / f"fig-userstudy-sus-{cohort}"
        _save(fig, stem)
        stems.append(stem)
    if preview:
        _show_saved_figures(stems, list(cohorts))
    return stems


def plot_efficiency_benchmarks(
    x_values,
    series,
    case_bar_heights,
    fig_dir: Path,
    *,
    stem: str = "fig-efficiency-benchmarks",
    preview=True,
):
    from .efficiency import plot_stacked_bars

    if not x_values:
        raise ValueError("No benchmark data to plot")
    out = fig_dir / stem
    plot_stacked_bars(x_values, series, "", out, case_bar_heights=case_bar_heights)
    if preview:
        _show_saved_figures([out], ["benchmarks"])
    return [out]


def plot_all_scalability(scal_line_payloads: dict, fig_dir: Path, *, preview=True):
    """Plot scalability line charts. payloads: id -> {x_values, series, xlabel, stem}."""
    from .scalability import plot_line_chart

    stems, titles = [], []
    for ds_id, p in scal_line_payloads.items():
        out = fig_dir / p["stem"]
        plot_line_chart(p["x_values"], p["series"], p["xlabel"], out)
        stems.append(out)
        titles.append(ds_id)
    if preview:
        _show_saved_figures(stems, titles)
    return stems
