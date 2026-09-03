#!/usr/bin/env python3
"""Interactive terminal progress display shared by SpecLens runners."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional


SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    if seconds < 3600:
        minutes, remaining = divmod(seconds, 60)
        return f"{int(minutes)}m {remaining:.2f}s"
    hours, remaining = divmod(seconds, 3600)
    minutes, remaining = divmod(remaining, 60)
    return f"{int(hours)}h {int(minutes)}m {remaining:.2f}s"


class TerminalSpinner:
    """Render one updating progress line on an interactive terminal."""

    def __init__(self, message: str, *, enabled: bool = True) -> None:
        self._message = message
        self._enabled = (
            enabled
            and sys.stdout.isatty()
            and os.environ.get("TERM") != "dumb"
        )
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._started_at = 0.0

    def __enter__(self) -> "TerminalSpinner":
        if self._enabled:
            self._started_at = time.monotonic()
            self._thread = threading.Thread(
                target=self._animate,
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if not self._enabled:
            return
        self._stop_event.set()
        assert self._thread is not None
        self._thread.join()
        with self._lock:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()

    def update(self, message: str) -> None:
        """Replace the progress message displayed on the next frame."""
        with self._lock:
            self._message = message

    def _animate(self) -> None:
        frame_index = 0
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - self._started_at
            with self._lock:
                frame = SPINNER_FRAMES[frame_index % len(SPINNER_FRAMES)]
                sys.stdout.write(
                    f"\r\033[2K {frame}  {self._message} "
                    f"({_format_elapsed(elapsed)})"
                )
                sys.stdout.flush()
            frame_index += 1
            self._stop_event.wait(0.1)
