"""Data normalization for evaluation.ipynb."""

from __future__ import annotations

import ast
from collections import defaultdict
import json
import re

import numpy as np
import pandas as pd

from .efficiency import (
    ALL_STEP_KEYS as EFFICIENCY_STEP_KEYS,
    _step_seconds,
    _steps_from_row,
    compute_three_bar_heights,
)
from .scalability import (
    ALL_STEP_KEYS as SCALABILITY_STEP_KEYS,
    FATTREE_TO_DEVICES,
    TIMEOUT_SEC,
)

CORRECT_ANSWERS = [
    {"option_1"},
    {"option_2"},
    {"option_2", "option_3"},
    {"option_2", "option_3"},
    {"option_1", "option_3"},
]
ALL_OPTIONS = {"option_1", "option_2", "option_3"}
EXPERIMENTAL_GROUPS = {"A": {2, 4}, "B": {1, 3}}

EFFICIENCY_BENCHMARKS = [
    ("Internet2", "internet2", True),
    ("Bics", "bics", False),
    ("Columbus", "columbus", False),
    ("USCarrier", "uscarrier", False),
]
SCALABILITY_DATASETS = [
    ("fattrees", "Device(s)", "fig-scalability-fattrees"),
    ("lines", "Configuration Line(s)", "fig-scalability-lines"),
    ("threads", "Core(s)", "fig-scalability-threads"),
]


def _parse_literal(value, default):
    if value is None or pd.isna(value):
        return default
    try:
        return ast.literal_eval(str(value))
    except (SyntaxError, ValueError):
        return default


def _parse_times(value):
    if value is None or pd.isna(value):
        return []
    fixed = re.sub(
        r'("?\d{1,2}:\d{2}"?)\.\s*("?\d{1,2}:\d{2}"?)',
        r'\1, \2',
        str(value),
    )
    times = _parse_literal(fixed, [])
    try:
        return [
            int(minutes) * 60 + int(seconds)
            for minutes, seconds in (str(item).split(":") for item in times)
        ]
    except (TypeError, ValueError):
        return []


def _parse_sus_scores(value):
    if value is None or pd.isna(value):
        return {}
    try:
        scores = json.loads(str(value).replace("'", '"'))
        return scores if isinstance(scores, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _question_score(selected, correct):
    selected = set(selected)
    return sum((option in selected) == (option in correct) for option in ALL_OPTIONS)


def _process_userstudy(df):
    df = df[df["userGroup"].notna()]
    data = {
        "experimental_scores": [[] for _ in range(5)],
        "control_scores": [[] for _ in range(5)],
        "experimental_times": [[] for _ in range(5)],
        "control_times": [[] for _ in range(5)],
        "sus_scores": defaultdict(list),
        "total_count": len(df),
    }

    for row in df.itertuples(index=False):
        answers = _parse_literal(row.answers, [])
        if len(answers) == 5:
            scores = [_question_score(answer, CORRECT_ANSWERS[index]) for index, answer in enumerate(answers)]
            for index in range(1, 5):
                prefix = "experimental" if index in EXPERIMENTAL_GROUPS.get(row.userGroup, ()) else "control"
                data[f"{prefix}_scores"][index].append(scores[index])

        times = _parse_times(row.questionTimes)
        if len(times) == 5:
            for index in range(1, 5):
                prefix = "experimental" if index in EXPERIMENTAL_GROUPS.get(row.userGroup, ()) else "control"
                data[f"{prefix}_times"][index].append(times[index])

        sus_scores = _parse_sus_scores(row.susScores)
        for question in range(1, 11):
            key = f"question{question}"
            if key in sus_scores:
                data["sus_scores"][question].append(sus_scores[key])
    return data


def prepare_userstudy(frames):
    data = {name: _process_userstudy(frame) for name, frame in frames.items()}
    data["combined"] = _process_userstudy(pd.concat(frames.values(), ignore_index=True))
    return data


def prepare_efficiency(df):
    rows_by_benchmark = {}
    for row in df.to_dict("records"):
        key = (row.get("benchmark") or "").strip().lower()
        rows_by_benchmark.setdefault(key, []).append(row)

    labels = []
    case_heights = {"fullsym": [], "subspecns": [], "subspec": []}
    series = {key: [] for key in EFFICIENCY_STEP_KEYS}

    for label, key, include_step14 in EFFICIENCY_BENCHMARKS:
        cases = sorted(rows_by_benchmark.get(key, []), key=lambda row: row.get("case", ""))
        if not cases:
            continue
        labels.append(label)
        totals = {"fullsym": [], "subspecns": [], "subspec": []}
        step_values = {step: [] for step in EFFICIENCY_STEP_KEYS}
        for row in cases:
            steps = _steps_from_row(row)
            fullsym, subspec_ns, subspec = compute_three_bar_heights(steps, include_step14)
            totals["fullsym"].append(fullsym)
            totals["subspecns"].append(subspec_ns)
            totals["subspec"].append(subspec)
            for step in EFFICIENCY_STEP_KEYS:
                if step != "step1.4" or include_step14:
                    step_values[step].append(_step_seconds(steps, step))
        for method in case_heights:
            case_heights[method].append(totals[method])
        for step, values in step_values.items():
            series[step].append(float(np.mean(values)) if values else None)
    return labels, series, case_heights


def _scalability_x(benchmark, case):
    pattern = {
        "fattrees": r"fattree(\d+)",
        "lines": r"line(\d+)",
        "threads": r"thread(\d+)",
    }[benchmark]
    match = re.search(pattern, case, re.I)
    if not match:
        return None
    return FATTREE_TO_DEVICES.get(match.group(1)) if benchmark == "fattrees" else int(match.group(1))


def prepare_scalability(df):
    payloads = {}
    records = df.to_dict("records")
    for benchmark, xlabel, stem in SCALABILITY_DATASETS:
        by_x = {}
        for row in records:
            if (row.get("benchmark") or "").strip().lower() != benchmark:
                continue
            x_value = _scalability_x(benchmark, row["case"])
            if x_value is not None:
                by_x[x_value] = _steps_from_row(row)
        for steps in by_x.values():
            if steps.get("step4.1") == TIMEOUT_SEC and not steps.get("step4.2"):
                steps["step4.2"] = TIMEOUT_SEC
        if benchmark == "lines":
            for x_value in (5000, 10000):
                for step in ("step2.2", "step3.1", "step3.2"):
                    if x_value in by_x and not by_x[x_value].get(step):
                        by_x[x_value][step] = TIMEOUT_SEC
        x_values = sorted(by_x)
        series = {
            step: [by_x[x_value].get(step) for x_value in x_values]
            for step in SCALABILITY_STEP_KEYS
        }
        payloads[benchmark] = {
            "x_values": x_values,
            "series": series,
            "xlabel": xlabel,
            "stem": stem,
        }
    return payloads
