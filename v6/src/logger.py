#!/usr/bin/python3
"""
logger.py
=========

Centralised logging for the HSL Invoice Extraction pipeline.

Configures a single named logger (``"hsl"``) that writes to both the console
and a rotating log file located at ``<project_root>/logs/hsl.log``.  All
child loggers obtained via :func:`get_logger` share the same handler set, so
there is no duplicate output across modules.

Usage
-----
Import :func:`get_logger` in any module and call it with ``__name__``::

    from logger import get_logger
    log = get_logger(__name__)

    log.info("Starting extraction for %s", pdf_path)
    log.warning("Gemini returned empty parsed output.")
    log.error("PDF conversion failed: %s", exc)
    log.exception("Unhandled error in extract()")

Log levels used in this pipeline
---------------------------------
- ``DEBUG``    — verbose internal state (raw API responses, file paths, etc.)
- ``INFO``     — normal lifecycle events (startup, shutdown, client init)
- ``WARNING``  — recoverable anomalies
- ``ERROR``    — operation failures that are caught and reported to the caller
- ``CRITICAL`` — unrecoverable failures that halt startup (missing credentials, etc.)
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
    """
    Construct and configure the root ``"hsl"`` logger.

    Attaches a :class:`logging.StreamHandler` for console output and a
    :class:`logging.handlers.RotatingFileHandler` for persistent log storage.
    Both handlers share the same log format.  The function is idempotent: if
    the logger already has handlers attached (e.g. during hot-reload or test
    re-imports), it is returned unchanged.

    Returns
    -------
    logging.Logger
        The fully configured ``"hsl"`` logger instance.

    Side Effects
    ------------
    - Creates ``<project_root>/logs/`` if it does not already exist.
    - Writes log output to ``<project_root>/logs/hsl.log`` (rotating at 5 MB,
      keeping up to 5 backup files).
    - Disables propagation to the root logger to prevent duplicate output.
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
    Return a logger suitable for use in a pipeline module.

    When ``name`` is provided (recommended: pass ``__name__``), a child logger
    named ``"hsl.<name>"`` is returned.  Child loggers inherit the level and
    handlers of the ``"hsl"`` root logger and prefix their records with the
    module name, making log output easier to trace.

    When ``name`` is omitted or empty, the ``"hsl"`` root logger itself is
    returned.

    Parameters
    ----------
    name : str, optional
        Dotted module name, typically ``__name__``.  Defaults to ``""``
        (returns the root ``"hsl"`` logger).

    Returns
    -------
    logging.Logger
        A configured :class:`logging.Logger` instance.

    Examples
    --------
    Standard per-module usage::

        from logger import get_logger
        log = get_logger(__name__)
        log.info("Module loaded.")

    Retrieve the root logger directly::

        from logger import get_logger
        log = get_logger()
        log.debug("Root logger message.")
    """
    if not name:
        return _logger
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")