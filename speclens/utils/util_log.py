#!/usr/bin/env python3
"""Shared logging helpers."""

import logging
import sys
from typing import NoReturn


def get_logger(name: str) -> logging.Logger:
    """Return a legacy module logger for utility-level warnings and errors."""
    module_logger = logging.getLogger(name)
    if not module_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        module_logger.addHandler(handler)
    module_logger.setLevel(logging.WARNING)
    module_logger.propagate = False
    return module_logger


def _format_message(message: str, args: tuple) -> str:
    """Apply logging-style percent interpolation to one message."""
    if not args:
        return message
    try:
        return message % args
    except (TypeError, ValueError):
        return " ".join([message, *(str(argument) for argument in args)])


def _emit(level: str, message: str, args: tuple) -> None:
    """Write one consistently formatted log message to stderr."""
    print(f"{level}: {_format_message(message, args)}", file=sys.stderr)


def log_info(message: str, *args, **kwargs) -> None:
    """Log an INFO message."""
    _emit("INFO", message, args)


def log_debug(message: str, *args, **kwargs) -> None:
    """Log a DEBUG message."""
    _emit("DEBUG", message, args)


def log_warning(message: str, *args, **kwargs) -> None:
    """Log a WARNING message."""
    _emit("WARNING", message, args)


def log_error(message: str, *args, **kwargs) -> None:
    """Log an ERROR message."""
    _emit("ERROR", message, args)


def exit_with_error(message: str, *args, **kwargs) -> NoReturn:
    """Log an ERROR message and terminate the current CLI command."""
    log_error(message, *args, **kwargs)
    sys.exit(1)


def verbose_info(verbose: bool, message: str, *args, **kwargs) -> None:
    """Log an INFO message only when verbose output is enabled."""
    if verbose:
        log_info(message, *args, **kwargs)


def verbose_debug(verbose: bool, message: str, *args, **kwargs) -> None:
    """Log a DEBUG message only when verbose output is enabled."""
    if verbose:
        log_debug(message, *args, **kwargs)


def verbose_error(verbose: bool, message: str, *args, **kwargs) -> None:
    """Log an ERROR message only when verbose output is enabled."""
    if verbose:
        log_error(message, *args, **kwargs)
