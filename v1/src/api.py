#!/usr/bin/python3
"""
api.py — FastAPI endpoint for structured data extraction from PDF invoices.

Format-agnostic: a single extraction config (configs/extraction.json) is used
for every request, regardless of document type. No 'type' header is required —
the same four fields (company_name, invoice_no, po_no, subtotal) are always
extracted.

Usage (start server):
    uvicorn api:app --host 0.0.0.0 --port 8000

Usage (PowerShell client):
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -ContentType "application/pdf" `
        -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"

Install dependencies:
    pip install fastapi uvicorn python-dotenv pdf2image google-genai
"""

import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from gemini_client import DEFAULT_CONFIG_PATH, GeminiClient
from helper import cleanup_temp_file, load_config, resolve_paths, _TEMP_DIR

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_upload(pdf_bytes: bytes) -> str:
    """
    Persist raw PDF bytes to a uniquely-named temporary file in ``HSL/temp/``.

    A UUID-based filename is used (rather than one derived from a document
    type) so concurrent requests never collide on the same temp path.

    Args:
        pdf_bytes (bytes): Raw PDF content from the request body.

    Returns:
        str: Absolute path to the saved temporary PDF file.
    """
    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    with open(temp_path, "wb") as f:
        f.write(pdf_bytes)

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON: company_name, invoice_no, po_no, subtotal",
)
async def extract(request: Request) -> JSONResponse:
    """
    Accept a raw PDF body and return structured extraction results as JSON.

    Format-agnostic — works for tax invoices, commercial invoices, bills, and
    similar documents from any issuer or layout. No document-type header is
    required; the same four fields are always extracted: ``company_name``,
    ``invoice_no``, ``po_no``, ``subtotal``.

    **Request requirements**

    - ``Content-Type`` must be ``application/pdf``.
    - Request body must be the raw binary content of a single-page PDF.

    **PowerShell example**

    ```powershell
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -ContentType "application/pdf" `
        -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"
    ```

    **Errors**

    | Status | Reason                                       |
    |--------|-----------------------------------------------|
    | 400    | Empty PDF body                                 |
    | 415    | ``Content-Type`` is not ``application/pdf``    |
    | 500    | Config missing / Gemini / Poppler error        |
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

    # 3. Save upload → run extraction → always clean up temp file
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes)
        result   = GeminiClient().extract_invoice_data(temp_pdf)

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

    # 4. Load fields_of_interest from the default config and resolve against the result.
    _, _, _, fields_of_interest = load_config(DEFAULT_CONFIG_PATH)
    return JSONResponse(content=resolve_paths(result, fields_of_interest))