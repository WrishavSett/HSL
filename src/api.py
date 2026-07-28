#!/usr/bin/python3
"""
api.py
======

FastAPI application and HTTP endpoint definitions for the HSL Invoice
Extraction pipeline.

Exposes a single ``POST /extract`` endpoint that accepts a multipart PDF
upload, passes it through the Gemini extraction pipeline, and returns a flat
JSON object containing the fields declared in the extraction configuration's
``fields_of_interest`` map.

Usage
-----
Start the server::

    uvicorn api:app --host 0.0.0.0 --port 8000

Send a PDF (PowerShell)::

    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }

Send a PDF (curl)::

    curl -X POST http://localhost:8000/extract \\
         -F "File=@/path/to/invoice.pdf;type=application/pdf"

Install Dependencies
--------------------
::

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

_client = GeminiClient()
_, _, _, _fields_of_interest = load_config(_DEFAULT_CONFIG_PATH)

# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logging
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown lifecycle events.

    Logs an informational message when the server is ready to accept requests
    and another when it begins shutting down.  Used as the ``lifespan``
    argument to :class:`fastapi.FastAPI`.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance (provided automatically by the
        framework).

    Yields
    ------
    None
        Yields control to the running application between the startup and
        shutdown log messages.
    """
    log.info("HSL Invoice Extraction API is ready.")
    yield
    log.info("HSL Invoice Extraction API is shutting down.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="1.0.0",
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
    Write raw PDF bytes to a uniquely named temporary file.

    Creates ``_TEMP_DIR`` if it does not already exist, then writes
    ``pdf_bytes`` to a new file named ``<uuid_hex>_upload.pdf`` inside that
    directory.

    Parameters
    ----------
    pdf_bytes : bytes
        Raw binary content of the uploaded PDF.

    Returns
    -------
    str
        Absolute path to the newly created temporary file.

    Raises
    ------
    RuntimeError
        If the file cannot be written due to an :class:`OSError` (e.g.
        permission denied or disk full).

    Example
    -------
    ::

        temp_path = _save_upload(pdf_bytes)
        # "/tmp/hsl/a3f9c1d2e8b74f0a9c6d1e2f3a4b5c6d_upload.pdf"
    """
    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    try:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
        log.debug(f"Saved uploaded PDF to temporary file: {temp_path}")
    except OSError as exc:
        log.error(f"Failed to write temporary PDF file at {temp_path}: {exc}")
        raise RuntimeError(f"Failed to write temporary PDF file at {temp_path}: {exc}") from exc

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", summary="Health check")
async def health_check() -> JSONResponse:
    """
    Return a simple health-check response.

    Useful for load-balancer probes and uptime monitoring.  Always returns
    HTTP 200 with ``{"status": "ok"}`` as long as the server process is
    running.

    Returns
    -------
    fastapi.responses.JSONResponse
        ``{"status": "ok"}`` with HTTP status ``200``.

    Example
    -------
    ::

        GET http://localhost:8000/
        # 200 OK
        # {"status": "ok"}
    """
    return JSONResponse(content={"status": "ok"})


@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON: company_name, invoice_no, po_no, subtotal",
)
async def extract(File: UploadFile = FastAPIFile(...)) -> JSONResponse:
    """
    Extract structured invoice data from an uploaded PDF file.

    Accepts a multipart/form-data upload under the field name ``File``,
    validates the content type and file extension, enforces a 20 MB size
    limit, saves the PDF to a temporary file, runs the Gemini extraction
    pipeline, and returns a flat JSON object whose keys are the aliases
    declared in ``fields_of_interest`` (from the extraction config).  The
    temporary file is always deleted after extraction, regardless of outcome.

    Parameters
    ----------
    File : fastapi.UploadFile
        The uploaded PDF file.  Must have a ``.pdf`` extension or a
        ``Content-Type`` of ``application/pdf`` or
        ``application/octet-stream``.

    Returns
    -------
    fastapi.responses.JSONResponse
        A flat JSON object with the extracted invoice fields.  Example::

            {
                "company_name": "Acme Corp",
                "invoice_no":   "INV-0042",
                "po_no":        "PO-9876",
                "subtotal":     "1234.56"
            }

    HTTP Errors
    -----------
    400 Bad Request
        The uploaded file is empty.
    413 Request Entity Too Large
        The uploaded file exceeds 20 MB.
    415 Unsupported Media Type
        The uploaded file is not a PDF (wrong content type and missing
        ``.pdf`` extension).
    500 Internal Server Error
        The temporary file could not be written, the PDF could not be
        converted to images, or the Gemini API call failed.

    Example
    -------
    PowerShell::

        Invoke-WebRequest -Uri "http://localhost:8000/extract" `
            -Method POST `
            -Form @{ File = Get-Item "C:/invoices/tax_invoice.pdf" }

    curl::

        curl -X POST http://localhost:8000/extract \\
             -F "File=@invoice.pdf;type=application/pdf"
    """
    # 1. Validate Content-Type / filename extension
    is_pdf_content_type = File.content_type in ("application/pdf", "application/octet-stream")
    is_pdf_extension    = (File.filename or "").lower().endswith(".pdf")
    if not is_pdf_content_type and not is_pdf_extension:
        log.error(
            f"Expected a PDF file. "
            f"Got content-type {File.content_type!r} and filename {File.filename!r}."
        )
        raise HTTPException(
            status_code=415,
            detail=(
                f"Expected a PDF file. "
                f"Got content-type {File.content_type!r} and filename {File.filename!r}."
            ),
        )

    # 2. Read uploaded file
    _MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
    pdf_bytes = await File.read(_MAX_UPLOAD_SIZE + 1)
    if not pdf_bytes:
        log.error("Uploaded file is empty. Send a valid PDF file.")
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty. Send a valid PDF file."
        )
    if len(pdf_bytes) > _MAX_UPLOAD_SIZE:
        log.error(f"Uploaded file exceeds maximum size of {_MAX_UPLOAD_SIZE} bytes.")
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds maximum size of {_MAX_UPLOAD_SIZE} bytes."
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
        log.error(f"Extraction failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

    finally:
        if temp_pdf:
            cleanup_temp_file(temp_pdf)

    # 4. Load fields_of_interest from the default config and resolve against the result.
    return JSONResponse(content=resolve_paths(result, _fields_of_interest))