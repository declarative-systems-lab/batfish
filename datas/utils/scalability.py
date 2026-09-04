"""Scalability constants and line plotting used by evaluation.ipynb."""

from __future__ import annotations

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
    "axes.labelsize": 9,
    "axes.titlesize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "mathtext.default": "regular",
})

TIMEOUT_SEC = 4 * 3600
TIMEOUT_MIN = 240
Y_BOTTOM_MAX = 120
Y_BOTTOM_TICKS = [0, 40, 80, 120]
Y_TOP_MIN = 235
Y_TOP_MAX = 245
TIMEOUT_DISPLAY = 240
FIG_SIZE = (8, 6.5)

STEPS_FROM_TIMES = ["step4.1", "step4.2"]
STEPS_FROM_SUBSPECS = [
    "step1.0", "step1.1", "step1.2", "step1.3",
    "step2.1", "step2.2", "step3.1", "step3.2",
]
ALL_STEP_KEYS = STEPS_FROM_TIMES + STEPS_FROM_SUBSPECS

FATTREE_TO_DEVICES = {"04": 20, "12": 180, "16": 320, "20": 500, "24": 720, "32": 1280}
_FATTREE_DEVICE_X = sorted(FATTREE_TO_DEVICES.values())
FATTREE_X_POS = {}
for index, value in enumerate(_FATTREE_DEVICE_X):
    if index == 0:
        FATTREE_X_POS[value] = float(value)
    else:
        previous = _FATTREE_DEVICE_X[index - 1]
        FATTREE_X_POS[value] = FATTREE_X_POS[previous] + (value - previous) * 1.5

CORE_X = [1, 4, 8, 12, 16, 20]
CORE_X_POS = {}
for index, value in enumerate(CORE_X):
    if index == 0:
        CORE_X_POS[value] = float(value)
    else:
        previous = CORE_X[index - 1]
        CORE_X_POS[value] = CORE_X_POS[previous] + (value - previous) * 1.5

LINE_X_POS = {10: 0, 100: 0.7, 1000: 1.6, 2000: 2.8, 5000: 4.2, 10000: 6.5}


def save_figure_pdf_png(fig: Figure, out_base: Path, **savefig_kw) -> tuple[Path, Path]:
    """Save the same figure as PDF and PNG (same basename)."""
    stem = out_base.with_suffix("")
    pdf_path = stem.with_suffix(".pdf")
    png_path = stem.with_suffix(".png")
    fig.savefig(pdf_path, format="pdf", **savefig_kw)
    fig.savefig(png_path, format="png", **savefig_kw)
    return pdf_path, png_path


def plot_line_chart(x_values: list[int], series: dict[str, list], xlabel: str, out_path: Path) -> None:
    """绘制折线图并保存。"""
    n = len(x_values)
    if n == 0:
        return
    
    # lines：自定义间距；fattrees / cores：横轴间距放大至原先的 3/2
    is_lines = "Line" in xlabel or "line" in xlabel.lower()
    is_fattrees = xlabel == "Device(s)"
    is_cores = xlabel == "Core(s)"
    if is_lines and set(x_values) == set(LINE_X_POS):
        x_arr = np.array([LINE_X_POS[x] for x in x_values])
    elif is_fattrees and set(x_values) == set(FATTREE_X_POS):
        x_arr = np.array([FATTREE_X_POS[x] for x in x_values])
    elif is_cores and set(x_values) == set(CORE_X_POS):
        x_arr = np.array([CORE_X_POS[x] for x in x_values])
    else:
        x_arr = np.array(x_values)
    
    # 计算三个柱组的总时间（分钟）
    s113 = [(series["step1.0"][i] or 0) + (series["step1.1"][i] or 0) + (series["step1.2"][i] or 0) + (series["step1.3"][i] or 0) for i in range(n)]
    
    # 柱组1：1.0-1.3 + 3.1 + 3.2（第一个，用三角形）
    group1 = [(s113[i] + (series["step3.1"][i] or 0) + (series["step3.2"][i] or 0)) / 60.0 for i in range(n)]
    
    # 柱组2：4.1 + 4.2（第二个，用正方形）
    group2 = [((series["step4.1"][i] or 0) + (series["step4.2"][i] or 0)) / 60.0 for i in range(n)]
    
    # 柱组3：1.0-1.3 + 2.1 + 2.2（第三个，用圆形）
    group3 = [(s113[i] + (series["step2.1"][i] or 0) + (series["step2.2"][i] or 0)) / 60.0 for i in range(n)]
    
    # x_arr已在函数开始处处理（lines数据集需要调整位置）
    g1_arr = np.array(group1)
    g2_arr = np.array(group2)
    g3_arr = np.array(group3)
    
    # 判断哪些点是timeout（>= 240分钟）
    timeout1 = g1_arr >= TIMEOUT_MIN
    timeout2 = g2_arr >= TIMEOUT_MIN
    timeout3 = g3_arr >= TIMEOUT_MIN
    
    # 创建截断的Y轴：timeout部分在上面
    fig = plt.figure(figsize=FIG_SIZE)
    
    # 创建两个独立的子图：上面（timeout）和下面（正常数据），中间有空间
    gs = fig.add_gridspec(2, 1, height_ratios=[0.6, 3], hspace=0.15)  # 减小timeout子图的图形高度
    ax_top = fig.add_subplot(gs[0])  # 上面：timeout
    ax_bottom = fig.add_subplot(gs[1])  # 下面：正常数据
    
    # 上面部分：235-245分钟（timeout，减小高度）
    ax_top.set_ylim(Y_TOP_MIN, Y_TOP_MAX)
    # 扩大x轴范围，确保边上的标记点完整显示
    x_range = max(x_arr) - min(x_arr)
    ax_top.set_xlim(min(x_arr) - 0.1 * x_range - 0.5, max(x_arr) + 0.1 * x_range + 0.5)
    
    # 下面部分：0-120分钟
    ax_bottom.set_ylim(0, Y_BOTTOM_MAX)
    # 扩大x轴范围，确保边上的标记点完整显示
    ax_bottom.set_xlim(min(x_arr) - 0.1 * x_range - 0.5, max(x_arr) + 0.1 * x_range + 0.5)
    
    # 绘制折线（移除label，legend单独生成）
    # 先定义所有的mask
    mask_bottom1 = ~timeout1
    mask_top1 = timeout1
    mask_bottom2 = ~timeout2
    mask_top2 = timeout2
    mask_bottom3 = ~timeout3
    mask_top3 = timeout3
    
    # 统一虚线样式：使用 '--'（matplotlib默认虚线），线宽3，与cores数据集一致
    LINE_WIDTH = 3
    
    # 柱组1：三角形，颜色 #2FA18C（绿色），空心标记，透明填充
    # 非timeout的点：在下面部分用实线连接
    if np.any(mask_bottom1):
        ax_bottom.plot(x_arr[mask_bottom1], g1_arr[mask_bottom1], '-', color='#2FA18C', 
                      marker='^', markersize=19, linewidth=3, markeredgewidth=2, 
                      markerfacecolor='none', markeredgecolor='#2FA18C', clip_on=False)
    # timeout的点：在上面部分先绘制虚线连接，再单独绘制标记（避免标记内部出现细线）
    if np.any(mask_top1):
        # 先绘制虚线连接（不包含标记）
        if np.sum(mask_top1) > 1:  # 如果有多个timeout点，需要连接
            ax_top.plot(x_arr[mask_top1], np.full(np.sum(mask_top1), TIMEOUT_DISPLAY), 
                       '--', color='#2FA18C', linewidth=LINE_WIDTH, marker='None', clip_on=False)
        # 再绘制标记（不包含线）
        ax_top.plot(x_arr[mask_top1], np.full(np.sum(mask_top1), TIMEOUT_DISPLAY), 
                   linestyle='None', color='#2FA18C',
                   marker='^', markersize=18, markeredgewidth=2,
                   markerfacecolor='none', markeredgecolor='#2FA18C', clip_on=False)
    
    # 收集需要连接的点的信息，在tight_layout之后绘制虚线以确保精确对齐
    connection_info = []  # [(group_color, last_bottom_idx, first_top_idx, g_arr)]
    
    # 柱组2：正方形，颜色 #5B9BD5（浅蓝色），空心标记，透明填充
    if np.any(mask_bottom2):
        ax_bottom.plot(x_arr[mask_bottom2], g2_arr[mask_bottom2], '-', color='#5B9BD5',
                      marker='s', markersize=18, linewidth=3, markeredgewidth=2,
                      markerfacecolor='none', markeredgecolor='#5B9BD5', clip_on=False)
    if np.any(mask_top2):
        # 先绘制虚线连接（不包含标记）
        if np.sum(mask_top2) > 1:  # 如果有多个timeout点，需要连接
            ax_top.plot(x_arr[mask_top2], np.full(np.sum(mask_top2), TIMEOUT_DISPLAY), 
                       '--', color='#5B9BD5', linewidth=LINE_WIDTH, marker='None', clip_on=False)
        # 再绘制标记（不包含线）
        ax_top.plot(x_arr[mask_top2], np.full(np.sum(mask_top2), TIMEOUT_DISPLAY), 
                   linestyle='None', color='#5B9BD5',
                   marker='s', markersize=18, markeredgewidth=2,
                   markerfacecolor='none', markeredgecolor='#5B9BD5', clip_on=False)
    
    # 收集柱组2的连接信息
    if np.any(mask_bottom2) and np.any(mask_top2):
        bottom_indices = np.where(mask_bottom2)[0]
        top_indices = np.where(mask_top2)[0]
        if len(bottom_indices) > 0 and len(top_indices) > 0:
            connection_info.append(('#5B9BD5', bottom_indices[-1], top_indices[0], g2_arr))
    
    # 柱组3：圆形，颜色 #F2994A（橙色），空心标记，透明填充
    if np.any(mask_bottom3):
        ax_bottom.plot(x_arr[mask_bottom3], g3_arr[mask_bottom3], '-', color='#F2994A',
                      marker='o', markersize=18, linewidth=3, markeredgewidth=2,
                      markerfacecolor='none', markeredgecolor='#F2994A', clip_on=False)
    if np.any(mask_top3):
        # 先绘制虚线连接（不包含标记）
        if np.sum(mask_top3) > 1:  # 如果有多个timeout点，需要连接
            ax_top.plot(x_arr[mask_top3], np.full(np.sum(mask_top3), TIMEOUT_DISPLAY), 
                       '--', color='#F2994A', linewidth=LINE_WIDTH, marker='None', clip_on=False)
        # 再绘制标记（不包含线）
        ax_top.plot(x_arr[mask_top3], np.full(np.sum(mask_top3), TIMEOUT_DISPLAY), 
                   linestyle='None', color='#F2994A',
                   marker='o', markersize=18, markeredgewidth=2,
                   markerfacecolor='none', markeredgecolor='#F2994A', clip_on=False)
    
    # 收集柱组3的连接信息
    if np.any(mask_bottom3) and np.any(mask_top3):
        bottom_indices = np.where(mask_bottom3)[0]
        top_indices = np.where(mask_top3)[0]
        if len(bottom_indices) > 0 and len(top_indices) > 0:
            connection_info.append(('#F2994A', bottom_indices[-1], top_indices[0], g3_arr))
    
    # 收集柱组1的连接信息
    if np.any(mask_bottom1) and np.any(mask_top1):
        bottom_indices = np.where(mask_bottom1)[0]
        top_indices = np.where(mask_top1)[0]
        if len(bottom_indices) > 0 and len(top_indices) > 0:
            connection_info.append(('#2FA18C', bottom_indices[-1], top_indices[0], g1_arr))
    
    # 设置坐标轴
    # 下面部分：显示 x 轴和 y 轴，显示 0, 40, 80, 120
    ax_bottom.set_xticks(x_arr)
    ax_bottom.set_xticklabels([str(x) for x in x_values], fontsize=26)  
    # ax_bottom.set_xlabel(xlabel, fontsize=28, fontweight='500')  # 去掉X轴标签  
    # 不在这里设置ylabel，后面统一设置
    ax_bottom.set_yticks(Y_BOTTOM_TICKS)
    for label in ax_bottom.get_yticklabels():
        label.set_fontsize(26)  
    
    # 上面部分：x轴只显示刻度，不显示数字；Y轴显示TimeOut
    ax_top.set_xticks(x_arr)
    ax_top.set_xticklabels([""] * len(x_values))  # x轴不显示数字，只保留刻度
    ax_top.set_yticks([TIMEOUT_DISPLAY])  # 只显示240分钟位置
    ax_top.set_yticklabels(["TimeOut"], fontsize=23)
    
    # 在整张图的中间位置添加Y轴标签
    fig.text(0.02, 0.5, "Time (minutes)", fontsize=28, rotation=90, va='center', ha='center', fontweight='500')
    
    # 对于 lines / fattrees / cores 数据集，调整 x 轴范围
    if (is_lines and set(x_values) == set(LINE_X_POS)) or (
        is_fattrees and set(x_values) == set(FATTREE_X_POS)
    ) or (
        is_cores and set(x_values) == set(CORE_X_POS)
    ):
        # 使用映射后的位置范围，稍微扩展边距
        x_min, x_max = min(x_arr), max(x_arr)
        x_range = x_max - x_min
        ax_bottom.set_xlim(x_min - 0.1 * x_range, x_max + 0.1 * x_range)
        ax_top.set_xlim(x_min - 0.1 * x_range, x_max + 0.1 * x_range)
    # 设置边框，让两个图看起来独立
    ax_top.spines['bottom'].set_visible(True)  # 显示底部边框
    ax_top.spines['top'].set_visible(True)  # 显示顶部边框
    ax_top.spines['left'].set_visible(True)
    ax_top.spines['right'].set_visible(True)
    
    ax_bottom.spines['top'].set_visible(True)  # 显示顶部边框
    ax_bottom.spines['bottom'].set_visible(True)  # 显示底部边框
    ax_bottom.spines['left'].set_visible(True)
    ax_bottom.spines['right'].set_visible(True)
    
    # 不需要截断标记，因为两个图是独立的
    
    # 网格线
    ax_bottom.grid(True, axis="y", linestyle="--", linewidth=0.3, alpha=0.25, color="#CCCCCC")
    ax_bottom.set_axisbelow(True)
    
    # 坐标轴边框：全部设为黑色
    for spine in ax_bottom.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("black")
    for spine in ax_top.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("black")
    
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="This figure includes Axes that are not compatible with tight_layout",
            category=UserWarning,
        )
        fig.tight_layout(rect=[0, 0, 0.80, 1])  # 右边留白多一点，rect=[left, bottom, right, top]
    
    # 在tight_layout之后绘制虚线，确保使用最终稳定的坐标系统，起点和终点精确对应标记中心
    # 注意：标记的中心就是数据坐标位置，所以直接使用数据坐标转换即可
    line_width = LINE_WIDTH
    for color, last_bottom_idx, first_top_idx, g_arr in connection_info:
        # 起点：最后一个非timeout点的标记中心 (x_arr[last_bottom_idx], g_arr[last_bottom_idx])
        # 终点：第一个timeout点的标记中心 (x_arr[first_top_idx], TIMEOUT_DISPLAY)
        # 使用figure坐标系统，用虚线连接
        # 确保使用正确的坐标转换：数据坐标 -> 显示坐标 -> figure坐标
        bottom_point = (x_arr[last_bottom_idx], g_arr[last_bottom_idx])
        top_point = (x_arr[first_top_idx], TIMEOUT_DISPLAY)
        
        # 转换坐标：数据坐标 -> 显示坐标（像素）
        fig_coords_bottom = ax_bottom.transData.transform([bottom_point])
        fig_coords_top = ax_top.transData.transform([top_point])
        
        # 转换坐标：显示坐标 -> figure坐标（归一化）
        fig_coords_bottom_norm = fig.transFigure.inverted().transform(fig_coords_bottom)
        fig_coords_top_norm = fig.transFigure.inverted().transform(fig_coords_top)
        
        # 直接画斜虚线连接，使用 '--' 样式，起点和终点精确对应标记中心
        # 使用zorder确保虚线在标记下方，但连接点精确对齐
        line = plt.Line2D([fig_coords_bottom_norm[0][0], fig_coords_top_norm[0][0]], 
                         [fig_coords_bottom_norm[0][1], fig_coords_top_norm[0][1]],
                         transform=fig.transFigure, color=color, linestyle='--', linewidth=line_width, zorder=0)
        fig.lines.append(line)
    
    pdf_path, png_path = save_figure_pdf_png(fig, out_path, bbox_inches="tight")
    plt.close(fig)
