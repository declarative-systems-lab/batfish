#!/usr/bin/env python3
"""Read and validate one artifact reproduction profile."""

import argparse
import json
import re
from pathlib import Path


DURATION_PATTERN = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?"
    r"(?:(\d+(?:\.\d+)?)m)?"
    r"(?:(\d+(?:\.\d+)?)s)?"
)


def duration_seconds(value):
    match = DURATION_PATTERN.fullmatch(value)
    if match is None or not any(match.groups()):
        raise ValueError(f"invalid timeout: {value!r}")
    hours, minutes, seconds = (float(part or 0) for part in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("timeout must be positive")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=("lite", "fast", "full"))
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("config.json"),
    )
    args = parser.parse_args()

    try:
        root = json.loads(args.config.read_text(encoding="utf-8"))
        profile = root["profiles"][args.profile]
        threads = profile["threads"]
        timeout = profile["timeout"]
        if isinstance(threads, bool) or not isinstance(threads, int) or threads <= 0:
            raise ValueError("threads must be a positive integer")
        if not isinstance(timeout, str):
            raise ValueError("timeout must be a compact duration string")
        seconds = duration_seconds(timeout)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"Invalid artifact configuration: {error}")

    print(threads, timeout, f"{seconds:g}")


if __name__ == "__main__":
    main()
