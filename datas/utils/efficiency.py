"""Efficiency data parsing and plotting used by evaluation.ipynb."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
    "axes.labelsize": 13,
    "axes.titlesize": 14,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 11,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "mathtext.default": "regular",
    "hatch.linewidth": 3.0,
})

TIMEOUT_SEC = 4 * 3600
TOP_Y_BOTTOM_MAX = 3600
TIMEOUT_DISPLAY = 4200
BOTTOM_Y_MAX_SEC = 30
WHISKER_LINEWIDTH = 1.3
WHISKER_CAP_WIDTH_RATIO = 0.8
WHISKER_COLOR = "#555555"

STEPS_FROM_TIMES = ["step4.1", "step4.2"]
STEPS_FROM_SUBSPECS = [
    "step1.0", "step1.1", "step1.2", "step1.3", "step1.4",
    "step2.1", "step2.2", "step3.1", "step3.2",
]
ALL_STEP_KEYS = STEPS_FROM_TIMES + STEPS_FROM_SUBSPECS


def save_figure_pdf_png(fig: Figure, out_base: Path, **savefig_kw) -> tuple[Path, Path]:
    """Save the same figure as PDF and PNG (same basename)."""
    stem = out_base.with_suffix("")
    pdf_path = stem.with_suffix(".pdf")
    png_path = stem.with_suffix(".png")
    fig.savefig(pdf_path, format="pdf", **savefig_kw)
    fig.savefig(png_path, format="png", **savefig_kw)
    return pdf_path, png_path


def parse_time(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s.upper() == "ERROR":
        return None
    if s == "待定":
        return 0.0
    if "4h" in s:
        return None
    m = re.search(r"(\d+)h", s)
    if m:
        total = int(m.group(1)) * 3600
    else:
        total = 0.0
    m = re.search(r"(\d+)m\s*(\d*\.?\d*)s?", s)
    if m:
        total += int(m.group(1)) * 60
        if m.group(2):
            total += float(m.group(2))
        return total
    m = re.search(r"(\d+\.?\d*)\s*s", s)
    if m:
        return float(m.group(1))
    return None


def _step_seconds(steps: dict[str, float], key: str) -> float:
    val = steps.get(key)
    if val is None:
        return float(TIMEOUT_SEC)
    return float(val)


def _workflow_seconds(
    steps: dict[str, float], first_step: str, second_step: str
) -> float:
    first = _step_seconds(steps, first_step)
    second = _step_seconds(steps, second_step)
    if first >= TIMEOUT_SEC or second >= TIMEOUT_SEC:
        return float(TIMEOUT_SEC)
    return first + second


def compute_three_bar_heights(steps: dict[str, float], include_step14: bool = False) -> tuple[float, float, float]:
    """Return (fullsym, subspecns, subspec) total seconds for one case."""
    prep = (
        _step_seconds(steps, "step1.0")
        + _step_seconds(steps, "step1.1")
        + _step_seconds(steps, "step1.2")
        + _step_seconds(steps, "step1.3")
    )
    if include_step14:
        prep += _step_seconds(steps, "step1.4")
    fullsym_workflow = _workflow_seconds(steps, "step4.1", "step4.2")
    subspecns_workflow = _workflow_seconds(steps, "step3.1", "step3.2")
    subspec_workflow = _workflow_seconds(steps, "step2.1", "step2.2")
    fullsym = fullsym_workflow
    subspecns = (
        TIMEOUT_SEC
        if subspecns_workflow >= TIMEOUT_SEC
        else prep + subspecns_workflow
    )
    subspec = (
        TIMEOUT_SEC
        if subspec_workflow >= TIMEOUT_SEC
        else prep + subspec_workflow
    )
    return fullsym, subspecns, subspec


def _steps_from_row(row: dict[str, str]) -> dict[str, float]:
    steps: dict[str, float] = {}
    for k in ALL_STEP_KEYS:
        val = (row.get(k) or "").strip()
        if not val:
            continue
        sec = parse_time(val)
        if sec is None and "4h" in val:
            sec = float(TIMEOUT_SEC)
        if sec is not None:
            steps[k] = sec
    return steps


def _to_arr(vals):
    return np.array([float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0 for v in vals], dtype=float)


def _display_y_for_panel(raw_h: float, is_bottom: bool) -> float | None:
    """Map raw seconds to y coordinate in the current panel, or None if out of panel range."""
    if is_bottom:
        # Bottom panel only shows cases strictly below 30s (no cap line at y=30).
        if raw_h >= TIMEOUT_SEC or raw_h >= BOTTOM_Y_MAX_SEC:
            return None
        return float(raw_h)
    if raw_h >= TIMEOUT_SEC:
        return float(TIMEOUT_DISPLAY)
    if raw_h < 30:
        return None
    return float(min(raw_h, TOP_Y_BOTTOM_MAX))


def _draw_range_whisker(
    ax,
    x_center: float,
    case_values: list[float],
    is_bottom: bool,
    cap_width: float,
    color: str = WHISKER_COLOR,
    zorder: int = 6,
) -> None:
    """Vertical line min–max across cases, with horizontal caps (distribution)."""
    if not case_values:
        return
    # 上图：全部 case 均 timeout 时，柱顶已在 TimeOut，分布线无信息
    if not is_bottom and all(v >= TIMEOUT_SEC for v in case_values):
        return

    ys = [_display_y_for_panel(v, is_bottom) for v in case_values]
    ys = [y for y in ys if y is not None]
    if not ys:
        return
    y_lo, y_hi = min(ys), max(ys)
    if y_hi - y_lo < 1e-6:
        if not is_bottom:
            return  # 上图退化分布（如全 timeout 压到同一点）不画
        expand = 0.06
        y_lo -= expand
        y_hi += expand
    hw = cap_width / 2
    ax.plot([x_center, x_center], [y_lo, y_hi], color=color, linewidth=WHISKER_LINEWIDTH, solid_capstyle="butt", zorder=zorder)
    ax.plot([x_center - hw, x_center + hw], [y_lo, y_lo], color=color, linewidth=WHISKER_LINEWIDTH, solid_capstyle="butt", zorder=zorder)
    ax.plot([x_center - hw, x_center + hw], [y_hi, y_hi], color=color, linewidth=WHISKER_LINEWIDTH, solid_capstyle="butt", zorder=zorder)


def _draw_three_bars(
    ax,
    n,
    series_slice,
    bar_width,
    gap,
    y_max_sec,
    is_bottom=False,
    show_timeout_only=False,
    x_values=None,
    case_bar_heights=None,
):
    """Draw three bars per benchmark (mean height) + min–max whisker per case distribution."""
    x = np.arange(n) * 1.3
    off1 = -bar_width - gap / 2
    off2 = 0.0
    off3 = bar_width + gap / 2

    hatch_offset = 0.0
    if x_values and len(x_values) > 0 and x_values[-1] == "USCarrier":
        hatch_offset = 0.05

    def heights_for_bar_type(bar_key: str, combine_fn) -> list[float]:
        if case_bar_heights is not None:
            return [float(np.mean(case_bar_heights[bar_key][i])) for i in range(n)]
        return combine_fn()

    def draw_single_bar(xx, heights, bar_color, hatch_pattern, zorder=1, hatch_offset=0.0, case_lists=None):
        h_arr = _to_arr(heights)
        timeout_bar = h_arr >= TIMEOUT_SEC

        if is_bottom:
            display_max = BOTTOM_Y_MAX_SEC
            timeout_display = BOTTOM_Y_MAX_SEC
            h_display = np.minimum(h_arr, display_max)
            h_draw = np.where(timeout_bar, 0.0, h_display)
            bottom_pos = np.zeros(n)
        elif show_timeout_only:
            timeout_display = TIMEOUT_DISPLAY
            h_draw = np.zeros(n)
            bottom_pos = np.zeros(n)
        else:
            display_min = 30.0
            timeout_display = TIMEOUT_DISPLAY
            h_display = np.minimum(np.maximum(h_arr, display_min), TOP_Y_BOTTOM_MAX)
            h_draw = np.where(timeout_bar, 0.0, h_display - display_min)
            bottom_pos = np.where(timeout_bar, 0.0, display_min)

        edge_color = "white" if hatch_pattern in ["/", "-"] else "#CCCCCC"
        xx_adjusted = xx.copy()
        if hatch_offset != 0.0 and len(xx) > 0:
            xx_adjusted[-1] = xx[-1] + hatch_offset

        ax.bar(
            xx_adjusted, h_draw, bar_width, bottom=bottom_pos, hatch=hatch_pattern,
            color=bar_color, edgecolor=edge_color, linewidth=0.2, zorder=zorder,
        )

        for i in range(n):
            if timeout_bar[i]:
                x_pos = xx[i] + (hatch_offset if i == len(xx) - 1 else 0.0)
                ax.bar(
                    x_pos, timeout_display, bar_width, bottom=0, facecolor=bar_color,
                    edgecolor=edge_color, hatch=hatch_pattern, linewidth=0.2, zorder=zorder + 0.5,
                )

        # Min–max whisker over 10 cases (vertical line + horizontal caps)
        if case_lists is not None:
            cap_w = bar_width * WHISKER_CAP_WIDTH_RATIO
            for i in range(n):
                x_pos = xx_adjusted[i]
                _draw_range_whisker(ax, x_pos, case_lists[i], is_bottom, cap_w, zorder=8)

    def legacy_combine_fullsym():
        return [
            _to_arr([series_slice["step4.1"][i] or 0])[0] + _to_arr([series_slice["step4.2"][i] or 0])[0]
            for i in range(n)
        ]

    def legacy_combine_subspecns():
        return [
            sum(_to_arr([series_slice[k][i] or 0])[0] for k in
                ["step1.0", "step1.1", "step1.2", "step1.3", "step3.1", "step3.2"])
            for i in range(n)
        ]

    def legacy_combine_subspec():
        return [
            sum(_to_arr([series_slice[k][i] or 0])[0] for k in
                ["step1.0", "step1.1", "step1.2", "step1.3", "step2.1", "step2.2"])
            for i in range(n)
        ]

    fullsym_heights = heights_for_bar_type("fullsym", legacy_combine_fullsym)
    subspecns_heights = heights_for_bar_type("subspecns", legacy_combine_subspecns)
    subspec_heights = heights_for_bar_type("subspec", legacy_combine_subspec)

    fs_cases = case_bar_heights["fullsym"] if case_bar_heights else None
    sns_cases = case_bar_heights["subspecns"] if case_bar_heights else None
    ss_cases = case_bar_heights["subspec"] if case_bar_heights else None

    # FullSym=blue plain; SubSpec_NS=green +; SubSpec=orange /
    draw_single_bar(
        x + off1, fullsym_heights, "#3A7AB8", "", zorder=2,
        hatch_offset=hatch_offset, case_lists=fs_cases,
    )
    draw_single_bar(
        x + off2, subspecns_heights, "#2FA18C", "+", zorder=1,
        hatch_offset=hatch_offset, case_lists=sns_cases,
    )
    draw_single_bar(
        x + off3, subspec_heights, "#F2994A", "/", zorder=1,
        hatch_offset=hatch_offset, case_lists=ss_cases,
    )


def plot_stacked_bars(
    x_values: list[str],
    series: dict[str, list],
    xlabel: str,
    out_path: Path,
    case_bar_heights: dict[str, list[list[float]]] | None = None,
) -> None:
    """绘制柱状图：上 30–4200s，下 0–30s。case_bar_heights 非空时柱高为 10 case 均值。"""
    n = len(x_values)
    if n == 0:
        return
    # 柱宽与间距：柱子变细，组别之间间距明显，组内柱子距离紧凑
    bar_width = 0.24  # 减小柱子宽度（从0.28改为0.22）
    gap = 0.10  # 组别之间的间距（从0.12减小到0.08，让组内柱子更紧凑）

    # 创建两个独立的子图：上面（30-3600秒，包含timeout），下面（0-30秒）
    # 减小上面子图的高度比例，减小两个子图之间的间距
    # 增加图片宽度以确保第四组完整显示
    fig = plt.figure(figsize=(11, 6.5))  # 宽度从8增加到10
    gs = fig.add_gridspec(2, 1, height_ratios=[2.5, 1.3], hspace=0.2)  # 减小高度比例和间距
    ax_top_normal = fig.add_subplot(gs[0])  # 上面：30-3600秒（60分钟），包含timeout（4200秒位置）
    ax_bottom = fig.add_subplot(gs[1])  # 下面：0-30秒

    # 上面：30-3600秒（60分钟），包含timeout（timeout显示在4200秒位置）
    ax_top_normal.set_ylim(30, TIMEOUT_DISPLAY)  # 30-4200秒（包含timeout）
    # x轴范围需要根据组间距调整，确保前后间距一致
    # 第一个柱子最左边位置：x[0] + off1 = -(bar_width + gap/2)
    # 最后一个柱子最右边位置：x[n-1] + off3 = (n-1)*1.3 + bar_width + gap/2
    # 为了让前后间距一致，左右边距都设为 bar_width + gap/2 + 额外边距
    margin = bar_width + gap / 2 + 0.3  # 统一的边距
    x_min = -(bar_width + gap / 2) - margin
    x_max = (n - 1) * 1.3 + bar_width + gap / 2 + margin
    ax_top_normal.set_xlim(x_min, x_max)
    _draw_three_bars(
        ax_top_normal, n, series, bar_width, gap, TOP_Y_BOTTOM_MAX,
        is_bottom=False, show_timeout_only=False, x_values=x_values,
        case_bar_heights=case_bar_heights,
    )

    # 下部分：0-30秒
    ax_bottom.set_ylim(0, BOTTOM_Y_MAX_SEC)
    # x轴范围需要根据组间距调整，确保前后间距一致
    ax_bottom.set_xlim(x_min, x_max)
    _draw_three_bars(
        ax_bottom, n, series, bar_width, gap, BOTTOM_Y_MAX_SEC,
        is_bottom=True, x_values=x_values, case_bar_heights=case_bar_heights,
    )

    # 上面（30-3600秒，包含timeout）坐标轴设置
    # Y轴刻度：显示30, 900, 1800, 2700, 3600和timeout（4200）
    ax_top_normal.set_yticks([30, 900, 1800, 2700, 3600, TIMEOUT_DISPLAY])  # 30, 900, 1800, 2700, 3600秒和4200秒（timeout）
    # 自定义格式化函数：3600显示"3600"，4200显示"TimeOut"，其他显示秒数
    def format_y_tick(v, _):
        if v == TIMEOUT_DISPLAY:
            return "TimeOut"
        else:
            return f"{int(v)}"
    ax_top_normal.yaxis.set_major_formatter(plt.FuncFormatter(format_y_tick))
    ax_top_normal.set_xticks([])  # 完全移除X轴刻度
    ax_top_normal.set_xticklabels([])  # 不显示x轴标签
    # 确保顶部不显示任何刻度：隐藏X轴和Y轴顶部的所有刻度和标签
    ax_top_normal.tick_params(top=False, labeltop=False, right=False, labelright=False)
    ax_top_normal.xaxis.set_ticks_position('none')  # X轴不显示刻度
    ax_top_normal.yaxis.set_ticks_position('left')  # Y轴刻度只在左侧显示
    # 额外确保顶部spine不显示刻度
    ax_top_normal.spines['top'].set_visible(True)  # 保留边框但隐藏刻度
    # Y轴刻度字体大小：22 -> 26（增大4号）
    for label in ax_top_normal.get_yticklabels():
        label.set_fontsize(26)
    # 网格线（与plot_line_charts.py一致）
    ax_top_normal.grid(True, axis="y", linestyle="--", linewidth=0.3, alpha=0.25, color="#CCCCCC")
    ax_top_normal.set_axisbelow(True)
    # 坐标轴边框（与plot_line_charts.py一致：linewidth=1.0, color="black"）
    ax_top_normal.spines['top'].set_visible(True)
    ax_top_normal.spines['bottom'].set_visible(True)
    ax_top_normal.spines['left'].set_visible(True)
    ax_top_normal.spines['right'].set_visible(True)
    for spine in ax_top_normal.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("black")

    # 下部分坐标轴设置
    # 纵坐标：0, 10, 20, 30秒
    ax_bottom.set_yticks([0, 10, 20, 30])
    ax_bottom.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}"))
    ax_bottom.set_xticks(np.arange(n)*1.3 )  # x轴刻度位置需要匹配组间距
    ax_bottom.set_xticklabels([str(x) for x in x_values], fontsize=28)  # X轴刻度字体大小：24 -> 28（增大4号）
    if xlabel:  # 只有当xlabel不为空时才设置
        ax_bottom.set_xlabel(xlabel, fontsize=28)  # X轴标题字体大小：24 -> 28（增大4号）
    # 不在这里设置ylabel，后面用fig.text添加以对齐
    ax_bottom.set_ylabel("")  # 先清空
    # Y轴刻度字体大小：22 -> 26（增大4号）
    for label in ax_bottom.get_yticklabels():
        label.set_fontsize(26)
    # 网格线（与plot_line_charts.py一致）
    ax_bottom.grid(True, axis="y", linestyle="--", linewidth=0.3, alpha=0.25, color="#CCCCCC")
    ax_bottom.set_axisbelow(True)
    # 坐标轴边框（与plot_line_charts.py一致：linewidth=1.0, color="black"）
    ax_bottom.spines['top'].set_visible(True)
    ax_bottom.spines['bottom'].set_visible(True)
    ax_bottom.spines['left'].set_visible(True)
    ax_bottom.spines['right'].set_visible(True)
    for spine in ax_bottom.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("black")

    # 图例已单独生成，此处不显示
    
    # 在y=30的位置添加四组的标记线（与y=0处的x轴刻度线类似）
    x_positions = np.arange(n) * 1.3  # 每个组的位置
    # 为每个组在y=30处添加短的垂直标记线（类似x轴刻度线）
    tick_length = 0.02 * (TIMEOUT_DISPLAY - 30)  # 刻度线长度，根据y轴范围计算
    for x_pos in x_positions:
        # 添加垂直标记线，从y=30向下延伸一小段
        ax_top_normal.plot([x_pos, x_pos], [30 - tick_length, 30], color="black", linewidth=1.0, zorder=10, clip_on=False)

    # 右侧留一些空间，因为左边Time标签占了一些空间
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="This figure includes Axes that are not compatible with tight_layout",
            category=UserWarning,
        )
        fig.tight_layout(rect=[0, 0, 0.85, 1])  # rect=[left, bottom, right, top]，right=0.85在右侧留15%空间
    
    # tight_layout之后，使用子图的bbox来计算准确位置
    # 将"Time (second)"放在整张图的中间位置
    # 计算整张图的中间y位置
    top_bbox = ax_top_normal.get_position()
    bottom_bbox = ax_bottom.get_position()
    overall_middle_y = (top_bbox.y1 + bottom_bbox.y0) / 2
    fig.text(0.01, overall_middle_y, "Time (seconds)", fontsize=28, rotation=90, va='center', ha='center')  # 24 -> 28（增大4号）
    pdf_path, png_path = save_figure_pdf_png(fig, out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
