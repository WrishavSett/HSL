#!/usr/bin/python3
"""
helper.py — Shared utilities for the HSL Invoice Extraction pipeline.

Provides:
  - Config loading and validation  (load_config)
  - PDF → image conversion         (pdf_to_image)
  - Temp file cleanup              (_cleanup_temp_file)
  - Recursive field search         (search_fields)
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP_DIR     = os.path.join(_PROJECT_ROOT, "temp")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, dict]:
    """
    Load and validate a document config .json file.

    The file must be a JSON object with exactly two keys:
        - ``"prompt"``          (str)  : extraction instructions for the model.
        - ``"response_schema"`` (dict) : JSON schema that constrains model output.

    Args:
        config_path (str): Absolute or relative path to the .json config file.

    Returns:
        tuple[str, dict]: ``(prompt, response_schema)``

    Raises:
        FileNotFoundError : If *config_path* does not exist on disk.
        ValueError        : If the file is invalid JSON, is missing required
                            keys, has wrong types, or contains empty values.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found: {config_path!r}\n"
            "Ensure the path is correct and the file exists."
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Config file {config_path!r} contains invalid JSON.\n"
            f"Parser error: {exc}"
        )

    missing = [k for k in ("prompt", "response_schema") if k not in config]
    if missing:
        raise ValueError(
            f"Config file {config_path!r} is missing required key(s): {missing}\n"
            'Expected: { "prompt": "...", "response_schema": { ... } }'
        )

    if not isinstance(config["prompt"], str):
        raise ValueError(
            f'"prompt" in {config_path!r} must be a string, '
            f'got {type(config["prompt"]).__name__}.'
        )
    if not isinstance(config["response_schema"], dict):
        raise ValueError(
            f'"response_schema" in {config_path!r} must be an object/dict, '
            f'got {type(config["response_schema"]).__name__}.'
        )
    if not config["prompt"].strip():
        raise ValueError(
            f'"prompt" in {config_path!r} is empty. Provide a non-empty extraction prompt.'
        )
    if not config["response_schema"]:
        raise ValueError(
            f'"response_schema" in {config_path!r} is an empty object. '
            "Provide a valid JSON schema."
        )

    return config["prompt"], config["response_schema"]

# ---------------------------------------------------------------------------
# PDF → image
# ---------------------------------------------------------------------------

def pdf_to_image(
    pdf_path: str,
    temp_dir: str = _TEMP_DIR,
    dpi: int = 400,
    fmt: str = "jpeg",
) -> str:
    """
    Rasterise the first page of a PDF into an image file stored in *temp_dir*.

    Uses ``pdf2image`` (which wraps Poppler's ``pdftoppm``).
    Install dependencies with::

        pip install pdf2image
        # Ubuntu/Debian : sudo apt-get install poppler-utils
        # macOS         : brew install poppler
        # Windows       : download poppler and add its bin/ to PATH

    Args:
        pdf_path (str):  Absolute or relative path to the source PDF file.
        temp_dir (str):  Directory to write the converted image into.
                         Created automatically if it does not exist.
                         Defaults to ``HSL/temp/``.
        dpi (int):       Rendering resolution in dots per inch (default 400).
                         Higher values improve OCR accuracy at the cost of
                         larger files and slower processing.
        fmt (str):       Output image format — ``"jpeg"`` (default) or ``"png"``.

    Returns:
        str: Absolute path to the generated image file
             (e.g. ``".../temp/tax_invoice.jpg"``).

    Raises:
        ImportError       : If ``pdf2image`` is not installed.
        FileNotFoundError : If *pdf_path* does not exist.
        RuntimeError      : If Poppler is absent from PATH or conversion fails.
    """
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
    except ImportError:
        raise ImportError(
            "pdf2image is required for PDF support.\n"
            "Install it with: pip install pdf2image\n"
            "You also need Poppler on your system PATH:\n"
            "  Ubuntu/Debian : sudo apt-get install poppler-utils\n"
            "  macOS         : brew install poppler\n"
            "  Windows       : download poppler and add its bin/ to PATH"
        )

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF file not found: {pdf_path!r}\n"
            "Ensure the path is correct and the file exists."
        )

    os.makedirs(temp_dir, exist_ok=True)
    extension = "jpg" if fmt.lower() in ("jpeg", "jpg") else fmt.lower()

    try:
        pages = convert_from_path(pdf_path, dpi=dpi, fmt=fmt)
    except PDFInfoNotInstalledError:
        raise RuntimeError(
            "Poppler's pdfinfo utility was not found.\n"
            "Install Poppler and make sure its executables are on your PATH."
        )
    except PDFPageCountError as exc:
        raise RuntimeError(f"Could not read page count from {pdf_path!r}: {exc}")
    except Exception as exc:
        raise RuntimeError(f"PDF conversion failed for {pdf_path!r}: {exc}")

    pdf_stem  = os.path.splitext(os.path.basename(pdf_path))[0]
    full_path = os.path.join(temp_dir, f"{pdf_stem}.{extension}")
    page_fmt  = "JPEG" if extension == "jpg" else fmt.upper()
    pages[0].save(full_path, page_fmt)

    return full_path

# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

def cleanup_temp_file(path: str) -> None:
    """
    Delete a temporary file, silently ignoring missing-file errors.

    Args:
        path (str): File path to remove.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def search_fields(data: dict | list, fields: list[str]) -> dict[str, str | None]:
    """
    Recursively walk *data* and return the first value found for each name in
    *fields*, regardless of nesting depth.

    If the same key appears more than once (e.g. ``"name"`` under both receiver
    and consignee), the first occurrence in a depth-first traversal is returned.
    Missing fields are returned as ``None``.

    Args:
        data (dict | list): Parsed Gemini response (or any sub-tree).
        fields (list[str]): Field names to search for.

    Returns:
        dict[str, str | None]: Mapping of field name → first matched value (or None).

    Example:
        >>> search_fields(parsed, ["company_name", "invoice_no"])
        {"company_name": "DCG Data-Core Systems ...", "invoice_no": "DC/25-26/03/0020"}
    """
    found: dict[str, str] = {}

    def _walk(node: dict | list) -> None:
        if len(found) == len(fields):
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in fields and key not in found:
                    found[key] = value
                if isinstance(value, (dict, list)):
                    _walk(value)
                if len(found) == len(fields):
                    return
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    _walk(item)
                if len(found) == len(fields):
                    return

    _walk(data)
    return {field: found.get(field) for field in fields}