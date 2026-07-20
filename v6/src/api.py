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
        -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }

Install dependencies:
    pip install fastapi uvicorn python-dotenv pdf2image google-genai python-multipart
    # CORS is handled by Starlette's CORSMiddleware, included with fastapi.
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File as FastAPIFile, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gemini_client import _DEFAULT_CONFIG_PATH, GeminiClient
from helper import cleanup_temp_file, load_config, resolve_paths, _TEMP_DIR

# ---------------------------------------------------------------------------
# Import logger
# ---------------------------------------------------------------------------

from logger import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Initialise GeminiClient and load extraction config
# ---------------------------------------------------------------------------

try:
    _client = GeminiClient()
except Exception as exc:
    raise RuntimeError(f"Failed to initialise GeminiClient: {exc}") from exc

try:
    _, _, _, _fields_of_interest = load_config(_DEFAULT_CONFIG_PATH)
except Exception as exc:
    raise RuntimeError(f"Failed to load extraction config at {_DEFAULT_CONFIG_PATH}: {exc}") from exc

# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logging
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("HSL Invoice Extraction API is ready.")
    yield
    log.info("HSL Invoice Extraction API is shutting down.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="5.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_upload(pdf_bytes: bytes) -> str:
    """
    Persist raw PDF bytes to a uniquely-named temporary file in HSL/temp/.

    A UUID-based filename is used (rather than one derived from a document
    type) so concurrent requests never collide on the same temp path.

    Args:
        pdf_bytes (bytes): Raw PDF content from the request body.

    Returns:
        str: Absolute path to the saved temporary PDF file.
    """
    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    try:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
    except OSError as exc:
        raise RuntimeError(f"Failed to write temporary PDF file at {temp_path}: {exc}") from exc

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", summary="Health check")
async def health_check() -> JSONResponse:
    """Return a simple status payload confirming the service is running."""
    return JSONResponse(content={"status": "ok"})


@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON: company_name, invoice_no, po_no, subtotal",
)
async def extract(File: UploadFile = FastAPIFile(...)) -> JSONResponse:
    """
    Accept a raw PDF body and return structured extraction results as JSON.

    Format-agnostic — works for tax invoices, commercial invoices, bills, and
    similar documents from any issuer or layout. No document-type header is
    required; the same four fields are always extracted: company_name,
    invoice_no, po_no, subtotal.

    **Request requirements**

    - Request body must be multipart/form-data with a single file field named File.
    - The uploaded file must be a PDF (validated by content-type and/or filename extension).

    **PowerShell example**

    `powershell
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }
    `

    **Errors**

    | Status | Reason                                            |
    |--------|---------------------------------------------------|
    | 400    | Uploaded file is empty                            |
    | 415    | File is not a PDF (wrong content-type/extension)  |
    | 500    | Config missing / Gemini / Poppler error           |
    """
    # 1. Validate Content-Type / filename extension
    is_pdf_content_type = File.content_type in ("application/pdf", "application/octet-stream")
    is_pdf_extension    = (File.filename or "").lower().endswith(".pdf")
    if not is_pdf_content_type and not is_pdf_extension:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Expected a PDF file. "
                f"Got content-type {File.content_type!r} and filename {File.filename!r}."
            ),
        )

    # 2. Read uploaded file
    pdf_bytes = await File.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty. Send a valid PDF file."
        )

    # 3. Save upload → run extraction → always clean up temp file
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes)
        result   = _client.extract_invoice_data(temp_pdf)

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
    return JSONResponse(content=resolve_paths(result, _fields_of_interest))