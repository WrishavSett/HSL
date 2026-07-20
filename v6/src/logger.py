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
_LOG_LEVEL    = "INFO"
_MAX_BYTES    = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_FMT      = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# One-time setup during startup on first import
# ---------------------------------------------------------------------------

def _build_logger() -> logging.Logger:
    """
    Construct and return the "hsl" root logger with a console handler and a
    rotating file handler.

    Called exactly once at module import time. The result is stored in the
    module-level _logger variable; every subsequent get_logger call
    returns a child of this logger so all output shares the same handler set
    and format, with no duplicate lines.

    Returns:
        logging.Logger: The configured "hsl" logger.

    Raises:
        OSError: If the log directory cannot be created.
    """
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
    """
    Return a child of the "hsl" logger identified by *name*.

    All child loggers inherit the handlers and level set in _build_logger,
    so no further configuration is needed at the call site.

    Args:
        name (str): Typically __name__ of the calling module (e.g.
                    "api", "gemini_client", "helper"). When
                    omitted or empty, the shared "hsl" logger itself is
                    returned.

    Returns:
        logging.Logger: A logger named "hsl.<name>" (or "hsl" when
                        *name* is empty), ready for immediate use.

    Example:
        >>> log = get_logger(__name__)
        >>> log.info("Extraction started for %s", pdf_path)
        2025-01-01 12:00:00 | INFO     | hsl.gemini_client | Extraction started for data/invoice.pdf
    """
    if not name:
        return _logger
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")