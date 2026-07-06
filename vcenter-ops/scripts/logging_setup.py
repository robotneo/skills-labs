"""
Module: scripts.logging_setup

Provides the single :func:`configure_logging` entry point used by
``handler.py`` and the standalone tools (``healthcheck.py`` etc.).

Design
------
All logs are written to ``stderr`` so that ``stdout`` can safely be used for
machine-readable JSON output. The format matches the previous inline
configuration in ``handler.py`` to keep log parsers stable.
"""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Install a stderr-only root logger with a stable text format.

    Args:
        level: Log level applied to the root logger. Defaults to ``INFO``.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stderr)
