"""Structured logging via loguru.

Provides a single :func:`get_logger` entrypoint so every module obtains a
consistently configured logger. Defaults:

* INFO level on stderr.
* ``LOREWIKI_LOG_LEVEL`` env var overrides the default level.
* ``LOREWIKI_LOG_FILE`` env var, if set, additionally writes to that file.

The configuration is applied lazily on first import so that downstream
applications (e.g. an MCP stdio server) can reconfigure before the first log
is emitted if needed.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from loguru import logger as _logger

if TYPE_CHECKING:
    from loguru import Logger

# Use a mutable container to track "already configured" state instead of a
# module-level ``global`` variable (ruff PLW0603). This keeps the helper
# idempotent without violating lint rules.
_state: dict[str, bool] = {"configured": False}
_DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def _configure() -> None:
    """Idempotently configure loguru sinks based on environment variables."""
    if _state["configured"]:
        return

    level = os.environ.get("LOREWIKI_LOG_LEVEL", "INFO").upper()
    _logger.remove()
    _logger.add(
        sys.stderr,
        level=level,
        format=_DEFAULT_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    log_file = os.environ.get("LOREWIKI_LOG_FILE")
    if log_file:
        _logger.add(
            log_file,
            level=level,
            rotation="10 MB",
            retention=5,
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )

    _state["configured"] = True


def reset_for_tests() -> None:
    """Reset the configured-flag. Intended for unit tests that need to exercise
    different environment-variable combinations within a single process."""
    _state["configured"] = False
    _logger.remove()


def get_logger(name: str | None = None) -> Logger:
    """Return a loguru logger bound to ``name`` (defaults to caller module)."""
    _configure()
    if name:
        return _logger.bind(scope=name)
    return _logger


__all__ = ["get_logger", "reset_for_tests"]
