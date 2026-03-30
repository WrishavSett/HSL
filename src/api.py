#!/usr/bin/python3
"""
api.py — FastAPI endpoint for structured data extraction from PDF invoices.

Usage (start server):
    uvicorn api:app --host 0.0.0.0 --port 8000

Usage (PowerShell client):
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -ContentType "application/pdf" `
        -Headers @{ "type" = "tax-invoice" } `
        -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"

Install dependencies:
    pip install fastapi uvicorn python-dotenv pdf2image google-genai
"""

import os
import re

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from gemini_client import GeminiClient
from helper import cleanup_temp_file, search_fields, _TEMP_DIR

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIGS_DIR  = os.path.join(_PROJECT_ROOT, "configs")

# To add a new document type: drop a .json into configs/ and add its entry here.
_SUPPORTED_TYPES: dict[str, str] = {
    "tax-invoice": "tax_invoice.json",
}

# Add or remove field names here without touching any other code.
_FIELDS_OF_INTEREST: list[str] = [
    "company_name",
    "invoice_no",
    "order_no",
    "total_amount_before_tax",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_config(doc_type: str) -> str:
    """
    Map the ``type`` header value to an absolute config file path.

    Args:
        doc_type (str): Value of the ``type`` request header.

    Returns:
        str: Absolute path to the matching .json config file.

    Raises:
        HTTPException 400 : Empty header or invalid characters.
        HTTPException 404 : Unrecognised document type.
        HTTPException 500 : Config file registered but absent from disk.
    """
    if not doc_type or not doc_type.strip():
        raise HTTPException(
            status_code=400,
            detail=f"Missing or empty 'type' header. Supported types: {sorted(_SUPPORTED_TYPES)}",
        )

    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", doc_type):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid 'type' header value {doc_type!r}. "
                "Only alphanumeric characters, hyphens, and underscores are allowed."
            ),
        )

    normalised = doc_type.strip().lower()

    if normalised not in _SUPPORTED_TYPES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown document type {doc_type!r}. Supported types: {sorted(_SUPPORTED_TYPES)}",
        )

    config_path = os.path.join(_CONFIGS_DIR, _SUPPORTED_TYPES[normalised])

    if not os.path.exists(config_path):
        raise HTTPException(
            status_code=500,
            detail=(
                f"Config file for type {doc_type!r} is registered but missing on disk: "
                f"{config_path!r}. Contact the server administrator."
            ),
        )

    return config_path


def _save_upload(pdf_bytes: bytes, doc_type: str) -> str:
    """
    Persist raw PDF bytes to a temporary file in ``HSL/temp/``.

    Args:
        pdf_bytes (bytes): Raw PDF content from the request body.
        doc_type (str):    Normalised document type (used in the filename).

    Returns:
        str: Absolute path to the saved temporary PDF file.
    """
    os.makedirs(_TEMP_DIR, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", doc_type)
    temp_path = os.path.join(_TEMP_DIR, f"{safe_name}_upload.pdf")

    with open(temp_path, "wb") as f:
        f.write(pdf_bytes)

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON matching the schema for the given document type",
)
async def extract(
    request: Request,
    type: str = Header(..., description="Document type, e.g. 'tax-invoice'"),
) -> JSONResponse:
    """
    Accept a raw PDF body and return structured extraction results as JSON.

    **Request requirements**

    - ``Content-Type`` must be ``application/pdf``.
    - ``type`` header must identify a supported document type (e.g. ``tax-invoice``).
    - Request body must be the raw binary content of a single-page PDF.

    **PowerShell example**

    ```powershell
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -ContentType "application/pdf" `
        -Headers @{ "type" = "tax-invoice" } `
        -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"
    ```

    **Errors**

    | Status | Reason                                              |
    |--------|-----------------------------------------------------|
    | 400    | Missing / invalid ``type`` header or empty PDF body |
    | 404    | Unrecognised document type                          |
    | 415    | ``Content-Type`` is not ``application/pdf``         |
    | 500    | Config missing on disk / Gemini / Poppler error     |
    """
    # 1. Validate Content-Type
    content_type = request.headers.get("content-type", "")
    if "application/pdf" not in content_type:
        raise HTTPException(
            status_code=415,
            detail=f"Expected Content-Type 'application/pdf', got {content_type!r}.",
        )

    # 2. Read raw body
    pdf_bytes = await request.body()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Request body is empty. Send a PDF file.")

    # 3. Resolve config path from the 'type' header
    config_path = _resolve_config(type)

    # 4. Save upload → run extraction → always clean up temp file
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes, type.strip().lower())
        result   = GeminiClient().extract_invoice_data(temp_pdf, config_path)

    except HTTPException:
        raise

    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    except (ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

    finally:
        if temp_pdf:
            cleanup_temp_file(temp_pdf)

    # 5. Return only the fields of interest
    return JSONResponse(content=search_fields(result, _FIELDS_OF_INTEREST))