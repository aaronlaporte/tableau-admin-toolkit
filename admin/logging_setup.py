"""
Centralized logging configuration for the Tableau admin toolkit.
"""
from __future__ import annotations

import logging
import sys
from os import getenv


def setup_logging(level: str | None = None) -> None:
    """
    Configure the root logger for the toolkit.

    Log level is resolved in order: explicit *level* argument, ``LOG_LEVEL``
    environment variable, then ``INFO`` as default.  Log messages are written to
    stderr so that JSON data output on stdout remains pipeable.
    """
    resolved_level = (level or getenv("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, resolved_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
        force=True,
    )
