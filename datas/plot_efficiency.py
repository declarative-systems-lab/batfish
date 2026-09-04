#!/usr/bin/env python3
"""Plot efficiency timing reports produced by run_efficiency.sh."""

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


WORKFLOWS = (
    ("SubSpec", "step2.1", "step2.2", True, "#177e89"),
    ("NoScope", "step3.1", "step3.2", True, "#e9c46a"),
    ("FullSym", "step4.1", "step4.2", False, "#e76f51"),
)
PREPARATION_STEPS = ("step1.0", "step1.1", "step1.2", "step1.3")
TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)(h|min|m|s)")


def parse_duration(value, timeout):
    value = (value or "").strip()
    if not value or value.endswith("+") or value.upper() == "ERROR":
        return timeout, True
    try:
        return float(value), False
    except ValueError:
        pass
    compact = value.replace(" ", "")
    tokens = TOKEN_RE.findall(compact)
    if not tokens or "".join(number + unit for number, unit in tokens) != compact:
        return timeout, True
    units = {"h": 3600, "min": 60, "m": 60, "s": 1}
    return sum(float(number) * units[unit] for number, unit in tokens), False


def workflow_runtime(row, first, second, include_preparation, timeout):
    first_seconds, first_timeout = parse_duration(row.get(first), timeout)
    second_seconds, second_timeout = parse_duration(row.get(second), timeout)
    if first_timeout or second_timeout:
        return timeout, True
    preparation = 0
    if include_preparation:
        preparation = sum(
            parse_duration(row.get(step), timeout)[0]
            for step in PREPARATION_STEPS
        )
        if row.get("benchmark", "").lower() == "internet2":
            preparation += parse_duration(row.get("step1.4"), timeout)[0]
    return min(preparation + first_seconds + second_seconds, timeout), False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--mode", choices=("lite", "fast", "full"), required=True)
    args = parser.parse_args()

    with args.input.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise SystemExit("No benchmark rows found in the timing summary")

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["benchmark"].lower()].append(row)
    preferred = ("bics", "columbus", "uscarrier", "internet2")
    benchmarks = [name for name in preferred if name in grouped]
    benchmarks.extend(sorted(set(grouped) - set(benchmarks)))

    columns = 2
    row_count = math.ceil(len(benchmarks) / columns)
    figure, axes_grid = plt.subplots(
        row_count,
        columns,
        figsize=(11, 3.5 * row_count),
        constrained_layout=True,
        squeeze=False,
    )
    axes = list(axes_grid.flat)
    width = 0.24

    for axis, benchmark in zip(axes, benchmarks):
        benchmark_rows = grouped[benchmark]
        positions = list(range(len(benchmark_rows)))
        for workflow_index, workflow in enumerate(WORKFLOWS):
            label, first, second, include_preparation, color = workflow
            results = [
                workflow_runtime(
                    row,
                    first,
                    second,
                    include_preparation,
                    args.timeout_seconds,
                )
                for row in benchmark_rows
            ]
            offsets = [
                position + (workflow_index - 1) * width
                for position in positions
            ]
            bars = axis.bar(
                offsets,
                [seconds / 60 for seconds, _ in results],
                width,
                label=label,
                color=color,
            )
            for bar, (_, timed_out) in zip(bars, results):
                if timed_out:
                    bar.set_hatch("///")
                    axis.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height(),
                        "TO",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                        fontweight="bold",
                    )
        axis.axhline(
            args.timeout_seconds / 60,
            color="#263238",
            linewidth=0.8,
            linestyle="--",
        )
        title = "Internet2" if benchmark == "internet2" else benchmark.upper()
        axis.set_title(title)
        axis.set_xticks(
            positions,
            [row.get("case", str(i + 1)) for i, row in enumerate(benchmark_rows)],
        )
        axis.set_xlabel("Property")
        axis.set_ylabel("Runtime (minutes)")
        axis.grid(axis="y", color="#d8d3c8", linewidth=0.6, alpha=0.8)
        axis.set_axisbelow(True)

    for axis in axes[len(benchmarks):]:
        axis.remove()
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    figure.suptitle(f"Efficiency reproduction ({args.mode})", fontweight="bold")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output_dir / "efficiency.png", dpi=220, bbox_inches="tight")
    figure.savefig(args.output_dir / "efficiency.pdf", bbox_inches="tight")


if __name__ == "__main__":
    main()
