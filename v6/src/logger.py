#!/usr/bin/python3
"""
logger.py — Centralised logging for the HSL Invoice Extraction pipeline.

Provides a single configured logger ("hsl") that writes to both the console
and a rotating log file. Import get_logger() in any module; all calls share
the same handler set, so there is no duplicate output.

Usage:
    from logger import get_logger
    log = get_logger(__name__)

    log.info("Starting extraction for %s", pdf_path)
    log.warning("Gemini returned empty parsed output.")
    log.error("PDF conversion failed: %s", exc)
    log.exception("Unhandled error in extract()")
"""

import logging
import logging.handlers
import os

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGGER_NAME  = "hsl"
_ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR      = os.path.join(_ROOT_DIR, "logs")
_LOG_FILE     = os.path.join(_LOG_DIR, "hsl.log")
_LOG_LEVEL    = "DEBUG"
_MAX_BYTES    = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_FMT      = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# One-time setup during startup on first import
# ---------------------------------------------------------------------------

def _build_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)

    # Guard against duplicate handler registration if the module is somehow
    # imported more than once (e.g. during testing or hot-reload).
    if logger.handlers:
        return logger

    logger.setLevel(_LOG_LEVEL)

    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATE_FMT)

    # Console handler.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating file handler.
    os.makedirs(_LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=_LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Prevent log records from propagating to the root logger, which would
    # cause duplicate output if the root logger has its own handlers.
    logger.propagate = False

    return logger

_logger = _build_logger()

# ---------------------------------------------------------------------------
# Public API for access
# ---------------------------------------------------------------------------

def get_logger(name: str = "") -> logging.Logger:
    if not name:
        return _logger
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")