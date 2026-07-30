#!/usr/bin/python3
"""
helper.py
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# Import logger
# ---------------------------------------------------------------------------

from logger import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Import errors
# ---------------------------------------------------------------------------

from error import (
    ConfigNotFoundError,
    ConfigInvalidJSONError,
    ConfigMissingKeyError,
    ConfigValueError,
    PDF2ImageNotInstalledError,
    PDFNotFoundError,
    PopplerNotInstalledError,
    PDFPageCountError,
    PDFTooManyPagesError,
    PDFConversionError,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP_DIR     = os.path.join(_PROJECT_ROOT, "temp")

# ---------------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------------

_SEGMENT      = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?$")
_PATH_SEGMENT = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<idx>\d+)\])?$")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, str, dict, dict[str, str]]:
    if not os.path.exists(config_path):
        log.error(f"Config file not found: {config_path}. Ensure the path is correct and the file exists.")
        raise ConfigNotFoundError(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        log.error(f"Config file {config_path} contains invalid JSON. Parser error: {str(exc)}")
        raise ConfigInvalidJSONError(config_path, str(exc)) from exc

    required_keys = ("system_instruction", "prompt", "response_schema", "fields_of_interest")
    missing = [k for k in required_keys if k not in config]
    if missing:
        log.error(f"Config file {config_path} is missing required key(s): {missing}.")
        raise ConfigMissingKeyError(config_path, missing)

    if not isinstance(config["system_instruction"], str):
        message = f'"system_instruction" must be a string, got {type(config["system_instruction"]).__name__}.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not isinstance(config["prompt"], str):
        message = f'"prompt" must be a string, got {type(config["prompt"]).__name__}.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not isinstance(config["response_schema"], dict):
        message = f'"response_schema" must be an object/dict, got {type(config["response_schema"]).__name__}.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not isinstance(config["fields_of_interest"], dict):
        message = f'"fields_of_interest" must be an object/dict, got {type(config["fields_of_interest"]).__name__}.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not config["system_instruction"].strip():
        message = '"system_instruction" is empty. Provide non-empty extraction rules.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not config["prompt"].strip():
        message = '"prompt" is empty. Provide a non-empty extraction prompt.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not config["response_schema"]:
        message = '"response_schema" is an empty object. Provide a valid JSON schema.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    if not config["fields_of_interest"]:
        message = '"fields_of_interest" is an empty object. Provide at least one alias to dot-path entry.'
        log.error(f"Config file {config_path} has an invalid value: {message}")
        raise ConfigValueError(config_path, message)

    for alias, path in config["fields_of_interest"].items():
        if not isinstance(alias, str) or not alias.strip():
            message = '"fields_of_interest" contains a non-string or empty alias.'
            log.error(f"Config file {config_path} has an invalid value: {message}")
            raise ConfigValueError(config_path, message)

        if not isinstance(path, str) or not path.strip():
            message = f'"fields_of_interest[{alias!r}]" must be a non-empty dot-path string.'
            log.error(f"Config file {config_path} has an invalid value: {message}")
            raise ConfigValueError(config_path, message)

        segments = path.split(".")
        for seg in segments:
            if not _SEGMENT.match(seg):
                message = f'"fields_of_interest[{alias!r}]" contains an invalid path segment {seg!r}.\nSegments must be identifiers, optionally followed by an array index like [0].'
                log.error(f"Config file {config_path} has an invalid value: {message}")
                raise ConfigValueError(config_path, message)

    return (
        config["prompt"],
        config["system_instruction"],
        config["response_schema"],
        config["fields_of_interest"],
    )

# ---------------------------------------------------------------------------
# PDF to image
# ---------------------------------------------------------------------------

def pdf_to_images(
    pdf_path: str,
    temp_dir: str = _TEMP_DIR,
    dpi: int = 200,
    fmt: str = "jpeg",
    max_pages: int = 30,
) -> list[str]:
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import (
            PDFInfoNotInstalledError,
            PDFPageCountError as Pdf2ImagePageCountError,
        )
    except ImportError:
        log.critical(
            f"pdf2image is required for PDF support.\n"
            f"Install it with: pip install pdf2image\n"
            f"You also need Poppler on your system PATH:\n"
            f"  Ubuntu/Debian : sudo apt-get install poppler-utils\n"
            f"  macOS         : brew install poppler\n"
            f"  Windows       : download poppler and add its bin/ to PATH"
        )
        raise PDF2ImageNotInstalledError()

    if not os.path.exists(pdf_path):
        log.error(f"PDF file not found: {pdf_path!r}.")
        raise PDFNotFoundError(pdf_path)

    os.makedirs(temp_dir, exist_ok=True)
    extension = "jpg" if fmt.lower() in ("jpeg", "jpg") else fmt.lower()

    try:
        pages = convert_from_path(pdf_path, dpi=dpi, fmt=fmt)
        log.debug(
            f"Converted PDF {pdf_path!r} to {len(pages)} image(s) "
            f"at {dpi} DPI in {fmt.upper()} format."
        )
    except PDFInfoNotInstalledError:
        log.error("Poppler's pdfinfo utility was not found.")
        raise PopplerNotInstalledError()
    except Pdf2ImagePageCountError as exc:
        log.error(f"Could not read page count from {pdf_path!r}: {exc}")
        raise PDFPageCountError(pdf_path, str(exc)) from exc
    except Exception as exc:
        log.error(f"PDF conversion failed for {pdf_path!r}: {exc}")
        raise PDFConversionError(pdf_path, str(exc)) from exc

    if len(pages) > max_pages:
        log.critical(
            f"PDF has {len(pages)} pages, which exceeds the limit of {max_pages}."
        )
        raise PDFTooManyPagesError(len(pages), max_pages)

    pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
    page_fmt = "JPEG" if extension == "jpg" else fmt.upper()
    saved: list[str] = []
    for i, page in enumerate(pages, start=1):
        out_path = os.path.join(temp_dir, f"{pdf_stem}_p{i}.{extension}")
        page.save(out_path, page_fmt)
        saved.append(out_path)
    return saved

# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

def cleanup_temp_file(path: str) -> None:
    try:
        os.remove(path)
        log.debug(f"Cleaned up temporary file: {path}")
    except FileNotFoundError:
        pass

def cleanup_temp_files(paths: list[str]) -> None:
    for path in paths:
        cleanup_temp_file(path)

# ---------------------------------------------------------------------------
# Subtotal normalisation
# ---------------------------------------------------------------------------

def normalize_subtotal(value: str) -> str:
    first = re.search(r'\d', value)
    if not first:
        return value

    last = re.search(r'\d(?=[^\d]*$)', value)
    span = value[first.start(): last.end()]

    result = re.sub(r'[^\d.]', '', span)
    if result.count('.') > 1:
        log.debug(
            f"normalize_subtotal: multiple decimal points found in {result!r}, "
            f"returning original value {value!r}"
        )
        return value

    return result

# ---------------------------------------------------------------------------
# Dot-path field resolution
# ---------------------------------------------------------------------------

def resolve_paths(
    data: dict,
    fields_of_interest: dict[str, str],
) -> dict[str, object]:
    result: dict[str, object] = {}

    for alias, path in fields_of_interest.items():
        node: object = data

        for segment in path.split("."):
            match = _PATH_SEGMENT.match(segment)
            if not match:
                node = None
                break

            key = match.group("key")
            idx = match.group("idx")

            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]

            if idx is not None:
                i = int(idx)
                if not isinstance(node, list) or i >= len(node):
                    node = None
                    break
                node = node[i]

        if alias == "subtotal" and isinstance(node, str):
            node = normalize_subtotal(node)
        result[alias] = node

    return result