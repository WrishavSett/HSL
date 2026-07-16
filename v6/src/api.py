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
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File as FastAPIFile, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from errors import EmptyUploadError, HSLError, UnsupportedMediaTypeError
from gemini_client import DEFAULT_CONFIG_PATH, GeminiClient
from helper import cleanup_temp_file, load_config, resolve_paths, _TEMP_DIR
from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level initialisation — runs before the lifespan handler.
# Errors here are fatal: the server cannot serve requests without them.
# Each is logged before re-raising so the failure is visible in the log file.
# ---------------------------------------------------------------------------

try:
    _client = GeminiClient()
except HSLError as exc:
    log.critical(
        "Startup failed — could not initialise GeminiClient. "
        "code=%s description=%r detail=%r",
        exc.code, exc.description, exc.detail,
    )
    raise
log.info("GeminiClient initialised successfully. model=%r", _client.model_name)

try:
    _, _, _, _fields_of_interest = load_config(DEFAULT_CONFIG_PATH)
except HSLError as exc:
    log.critical(
        "Startup failed — could not load extraction config at %r. "
        "code=%s description=%r detail=%r",
        DEFAULT_CONFIG_PATH, exc.code, exc.description, exc.detail,
    )
    raise
log.info("Extraction config loaded successfully. path=%r", DEFAULT_CONFIG_PATH)

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
    lifespan=lifespan,
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

    A UUID-based filename is used so concurrent requests never collide.

    Args:
        pdf_bytes (bytes): Raw PDF content from the request body.

    Returns:
        str: Absolute path to the saved temporary PDF file.

    Raises:
        TempFileWriteError: If the file cannot be written (disk full, permissions).
    """
    from errors import TempFileWriteError

    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    try:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
    except OSError as exc:
        raise TempFileWriteError(
            detail=(
                f"Could not write uploaded PDF to temporary path {temp_path!r}: {exc}\n"
                "Check available disk space and directory permissions."
            )
        )

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
    Accept a PDF upload and return structured extraction results as JSON.

    Format-agnostic — works for tax invoices, commercial invoices, bills, and
    similar documents. No document-type header is required.

    **Request requirements**

    - Multipart/form-data with a single file field named File.
    - The uploaded file must be a PDF.

    **PowerShell example**

    `powershell
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }
    `

    **Error response body**

    All errors return a JSON object with:
        - code        (int) : HSL error code
        - description (str) : human-readable explanation
        - detail      (str) : low-level context (present when available)

    **Error codes**

    | HTTP | HSL Code | Reason                                        |
    |------|----------|-----------------------------------------------|
    | 400  | 502      | Uploaded file is empty                        |
    | 415  | 501      | File is not a PDF                             |
    | 422  | 301      | PDF conversion failed                         |
    | 422  | 302      | PDF exceeds maximum page count                |
    | 422  | 407      | Gemini returned no structured output          |
    | 422  | 408      | Gemini blocked the request (safety filters)   |
    | 429  | 403      | Gemini rate limit exceeded                    |
    | 429  | 404      | Gemini project quota exhausted                |
    | 500  | 101–108  | Configuration or environment error            |
    | 500  | 202–205  | File I/O or temp directory error              |
    | 500  | 303–304  | Poppler or pdf2image not installed            |
    | 500  | 409      | Gemini rejected the request payload           |
    | 502  | 401      | Gemini authentication failed                  |
    | 502  | 402      | Gemini permission denied                      |
    | 502  | 405      | Gemini service unavailable                    |
    | 502  | 406      | Network error reaching Gemini                 |
    | 502  | 410      | Unexpected Gemini API error                   |
    """
    # 1. Validate Content-Type / filename extension
    is_pdf_content_type = File.content_type in ("application/pdf", "application/octet-stream")
    is_pdf_extension    = (File.filename or "").lower().endswith(".pdf")
    if not is_pdf_content_type and not is_pdf_extension:
        exc = UnsupportedMediaTypeError(
            detail=(
                f"Expected a PDF file. "
                f"Got content-type {File.content_type!r} and filename {File.filename!r}."
            )
        )
        log.warning(
            "Rejected upload — unsupported media type. "
            "filename=%r content_type=%r code=%s",
            File.filename, File.content_type, exc.code,
        )
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    # 2. Read uploaded file
    pdf_bytes = await File.read()
    if not pdf_bytes:
        exc = EmptyUploadError(
            detail="Uploaded file is empty. Send a valid PDF file."
        )
        log.warning("Rejected upload — empty file. filename=%r code=%s", File.filename, exc.code)
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    # 3. Save, extract, clean up
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes)
        log.info("Processing upload: filename=%r size=%d bytes temp=%r", File.filename, len(pdf_bytes), temp_pdf)

        result = _client.extract_invoice_data(temp_pdf)

    except HSLError as exc:
        log.error(
            "Extraction failed. filename=%r code=%s description=%r detail=%r",
            File.filename, exc.code, exc.description, exc.detail,
        )
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    except Exception as exc:
        log.exception("Unhandled exception during extraction. filename=%r", File.filename)
        raise HTTPException(
            status_code=500,
            detail={
                "code":        0,
                "description": "An unexpected internal error occurred.",
                "detail":      str(exc),
            },
        )

    finally:
        if temp_pdf:
            cleanup_temp_file(temp_pdf)

    # 4. Resolve fields and return
    log.info("Extraction successful. filename=%r", File.filename)
    return JSONResponse(content=resolve_paths(result, _fields_of_interest))